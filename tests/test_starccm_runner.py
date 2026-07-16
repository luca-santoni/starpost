from pathlib import Path

from starpost.core.settings import LicenseConfig, Settings
from starpost.core.starccm_runner import StarRunner, redact_command
from starpost.data.models import SimResult


def _runner(license: LicenseConfig) -> StarRunner:
    s = Settings(starccm_path="/opt/starccm/bin/starccm+")
    s.license = license
    return StarRunner(s)


def test_redact_masks_podkey_and_license_server():
    """The POD key and license server are masked for display, but the real
    command (handed to the subprocess) still carries them verbatim."""
    runner = _runner(
        LicenseConfig(
            mode="podkey_server", podkey="SECRET-POD-123", licpath="1999@flex.example.com"
        )
    )
    cmd = runner.build_command(Path("/tmp/macro.java"), Path("/tmp/run.sim"))
    shown = redact_command(cmd)

    assert "SECRET-POD-123" not in shown
    assert "flex.example.com" not in shown
    # The flags survive, only their values are masked.
    assert "-podkey *** " in shown + " "
    assert "-licpath *** " in shown + " "
    # The real command is untouched, so STAR-CCM+ still authenticates.
    assert "SECRET-POD-123" in cmd
    assert "1999@flex.example.com" in cmd


def test_redact_masks_license_file_path():
    runner = _runner(
        LicenseConfig(mode="license_file", license_file="/secret/license.dat")
    )
    cmd = runner.build_command(Path("/tmp/macro.java"), Path("/tmp/run.sim"))
    shown = redact_command(cmd)

    assert "/secret/license.dat" not in shown
    assert "-licpath ***" in shown
    assert "/secret/license.dat" in cmd


def test_redact_noop_without_secrets():
    """A command with no license flags is rendered unchanged."""
    cmd = ["/opt/starccm/bin/starccm+", "-batch", "/tmp/macro.java", "/tmp/run.sim"]
    assert redact_command(cmd) == " ".join(cmd)


def test_extract_keeps_intermediate_csvs_out_of_user_folders(tmp_path, monkeypatch):
    """The macro's exported CSVs (reports, per-plot data, the scene/screenplay/
    view indexes) are implementation details: extract() must direct them to a
    scratch directory it owns and cleans up, never to a caller-chosen folder —
    they used to pile up, unasked-for, in the user's default output folder."""
    import starpost.core.starccm_runner as sr

    captured = {}

    def fake_render_macro(output_dir, dest_dir):
        captured["macro_export_dir"] = Path(output_dir)
        macro = Path(dest_dir) / "extract_all.java"
        macro.write_text("// fake macro")
        return macro

    def fake_parse(sim_path, output_dir, classification):
        captured["parse_dir"] = Path(output_dir)
        captured["parse_dir_existed"] = Path(output_dir).is_dir()
        return SimResult(sim_path=sim_path)

    monkeypatch.setattr(sr, "render_macro", fake_render_macro)
    monkeypatch.setattr(sr, "parse_sim_output", fake_parse)
    monkeypatch.setattr(sr.StarRunner, "_stream", lambda self, cmd, sink: 0)

    runner = _runner(LicenseConfig())
    result = runner.extract(tmp_path / "case.sim")

    assert result.error is None
    # The macro exported into the same scratch dir the parser read from…
    assert captured["macro_export_dir"] == captured["parse_dir"]
    assert captured["parse_dir_existed"]
    # …which is extract's own temporary dir, gone once it returns.
    assert not captured["parse_dir"].exists()
    assert not captured["parse_dir"].is_relative_to(tmp_path)
    assert not captured["parse_dir"].is_relative_to(Path.home())
