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
