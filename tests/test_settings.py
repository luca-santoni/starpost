import os
import stat
import sys

import pytest
import yaml

from starpost.core.settings import LicenseConfig, Profile, Settings


@pytest.fixture(autouse=True)
def isolated_profiles(monkeypatch, tmp_path):
    """Redirect profile storage to a temp dir on every platform.

    Profiles resolve through ``starpost.core.settings.profiles_dir``. Patching it
    directly works on Windows, Linux and macOS alike. (The old approach set
    XDG_CONFIG_HOME, which platformdirs only honors on Linux, so on Windows
    profiles still resolved to the real %LOCALAPPDATA% — the legacy-file tests
    then couldn't find what they had written.) Returns the temp profiles dir.
    """
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr("starpost.core.settings.profiles_dir", lambda: profiles)
    return profiles


@pytest.fixture
def isolated_batch_profiles(monkeypatch, tmp_path):
    """Redirect batch-profile storage to a temp dir (mirrors ``isolated_profiles``).

    ``BatchProfile`` resolves through ``starpost.core.settings.batch_profiles_dir``,
    a separate directory from Profiles; patch it directly so tests never touch
    the real per-OS batch_profiles dir.
    """
    batch_profiles = tmp_path / "batch_profiles"
    batch_profiles.mkdir()
    monkeypatch.setattr(
        "starpost.core.settings.batch_profiles_dir", lambda: batch_profiles
    )
    return batch_profiles


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX mode bits not meaningful on Windows"
)
def test_save_writes_owner_only_settings_file(monkeypatch, tmp_path):
    """The settings file holds the POD key / license server in plaintext, so
    save() must leave it readable only by the owner (0600)."""
    path = tmp_path / "settings.yaml"
    monkeypatch.setattr("starpost.core.settings.settings_path", lambda: path)
    Settings().save()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX mode bits not meaningful on Windows"
)
def test_save_tightens_preexisting_loose_permissions(monkeypatch, tmp_path):
    """A settings file left world-readable by an older version is locked down on
    the next save."""
    path = tmp_path / "settings.yaml"
    path.write_text("starccm_path: ''\n")
    os.chmod(path, 0o664)
    monkeypatch.setattr("starpost.core.settings.settings_path", lambda: path)
    Settings().save()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_podkey_server_args():
    lic = LicenseConfig(mode="podkey_server", podkey="ABC", licpath="1999@licsrv")
    assert lic.cli_args() == ["-power", "-podkey", "ABC", "-licpath", "1999@licsrv"]


def test_license_file_args():
    lic = LicenseConfig(mode="license_file", license_file="/opt/lic/star.lic")
    assert lic.cli_args() == ["-licpath", "/opt/lic/star.lic"]


def test_podkey_server_omits_empty_fields():
    lic = LicenseConfig(mode="podkey_server", podkey="", licpath="")
    assert lic.cli_args() == ["-power"]


def test_monitor_settings_defaults():
    s = Settings.from_dict({})
    assert s.hide_empty_monitors is True
    assert s.monitor_zero_threshold == 1e-5


def test_monitor_settings_round_trip():
    s = Settings.from_dict({"hide_empty_monitors": False, "monitor_zero_threshold": 1e-3})
    d = s.to_dict()
    assert d["hide_empty_monitors"] is False
    assert d["monitor_zero_threshold"] == 1e-3
    # Re-parsing the serialized form preserves the values.
    assert Settings.from_dict(d).hide_empty_monitors is False
    assert Settings.from_dict(d).monitor_zero_threshold == 1e-3


def test_profile_round_trips_monitor_selection():
    Profile(
        name="aero",
        reports=["Cd"],
        plots=["Downforce"],
        monitors={"Downforce": ["Front Downforce (N)"]},
    ).save()

    loaded = Profile.load("aero")
    assert loaded.plots == ["Downforce"]
    assert loaded.monitors == {"Downforce": ["Front Downforce (N)"]}


def test_profile_without_monitors_defaults_to_empty(isolated_profiles):
    # Profiles saved before the monitor selection existed have no "monitors" key.
    (isolated_profiles / "legacy.yaml").write_text(
        yaml.safe_dump({"name": "legacy", "reports": ["Cd"], "plots": ["Drag"]})
    )

    loaded = Profile.load("legacy")
    assert loaded.plots == ["Drag"]
    assert loaded.monitors == {}  # absent -> show all monitors on load


def test_profile_round_trips_region_stats():
    Profile(name="aero", region_stats=["Avg", "Range"]).save()

    loaded = Profile.load("aero")
    assert loaded.region_stats == ["Avg", "Range"]


def test_profile_without_region_stats_is_none(isolated_profiles):
    # Profiles saved before region stats existed have no "region_stats" key;
    # load as None so the current selection is left unchanged.
    (isolated_profiles / "legacy.yaml").write_text(
        yaml.safe_dump({"name": "legacy", "reports": ["Cd"], "plots": ["Drag"]})
    )

    assert Profile.load("legacy").region_stats is None


def test_batch_profile_round_trips_report_settings():
    import starpost.core.settings as cfg

    cfg.BatchProfile(
        name="Nightly", selected_reports=["Drag"],
        report_format="XLSX", include_units=False, combined_report=False,
    ).save()
    loaded = cfg.BatchProfile.load("Nightly")
    assert loaded.report_format == "XLSX"
    assert loaded.include_units is False
    assert loaded.combined_report is False


def test_batch_profile_defaults_when_keys_absent():
    import starpost.core.settings as cfg
    from starpost.utils.paths import batch_profiles_dir

    d = batch_profiles_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "Old.yaml").write_text("name: Old\nselected_reports:\n- A\n", encoding="utf-8")
    loaded = cfg.BatchProfile.load("Old")
    assert loaded.report_format == "CSV"
    assert loaded.include_units is True
    assert loaded.combined_report is True
    assert loaded.saved_screenplays == []


def test_batch_profile_round_trips_saved_screenplays():
    import starpost.core.settings as cfg

    entries = [{
        "name": "Flythrough",
        "data": {"displayers": {"Iso": ["Static Pressure"]}, "views": ["Top"],
                 "resolution": "2160p", "format": "mp4", "fps": 60,
                 "quality": "high"},
    }]
    cfg.BatchProfile(name="Movies", saved_screenplays=entries).save()
    loaded = cfg.BatchProfile.load("Movies")
    assert loaded.saved_screenplays == entries


def test_batch_profile_round_trips_report_unit_system(isolated_batch_profiles):
    from starpost.core.settings import BatchProfile

    bp = BatchProfile(name="p", report_unit_system="imperial")
    bp.save()
    assert BatchProfile.load("p").report_unit_system == "imperial"


def test_batch_profile_defaults_report_unit_system():
    from starpost.core.settings import BatchProfile

    assert BatchProfile(name="p").report_unit_system == "default"


def test_round_trips_saved_view_splits():
    import starpost.core.settings as cfg

    s = cfg.Settings()
    s.saved_view_splits = {"scenes": [400, 120], "screenplays": [150, 360]}
    restored = cfg.Settings.from_dict(s.to_dict())
    assert restored.saved_view_splits == {
        "scenes": [400, 120],
        "screenplays": [150, 360],
    }


def test_saved_view_splits_drops_malformed():
    import starpost.core.settings as cfg

    s = cfg.Settings.from_dict(
        {"saved_view_splits": {"scenes": "oops", "screenplays": [1, 2, 3],
                               "junk": [1, 2]}}
    )
    assert s.saved_view_splits == {}


def test_unit_system_defaults_and_round_trip():
    s = Settings()
    assert s.report_unit_system == "default"
    assert s.plot_unit_system == "default"
    s.report_unit_system = "imperial"
    s.plot_unit_system = "si"
    restored = Settings.from_dict(s.to_dict())
    assert restored.report_unit_system == "imperial"
    assert restored.plot_unit_system == "si"


def test_unit_system_bad_value_coerces_to_default():
    restored = Settings.from_dict(
        {"report_unit_system": "furlongs", "plot_unit_system": 5}
    )
    assert restored.report_unit_system == "default"
    assert restored.plot_unit_system == "default"


def test_legend_opacity_default():
    s = Settings.from_dict({})
    assert s.legend_opacity == 0.2


def test_legend_opacity_round_trip():
    s = Settings.from_dict({"legend_opacity": 0.5})
    d = s.to_dict()
    assert d["legend_opacity"] == 0.5
    assert Settings.from_dict(d).legend_opacity == 0.5


def test_legend_opacity_clamped_on_load():
    assert Settings.from_dict({"legend_opacity": 1.7}).legend_opacity == 1.0
    assert Settings.from_dict({"legend_opacity": -0.3}).legend_opacity == 0.0
