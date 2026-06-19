from pathlib import Path

from starpost.core.settings import LicenseConfig, Settings
from starpost.core.starccm_runner import StarRunner, redact_command


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
