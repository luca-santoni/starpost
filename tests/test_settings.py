from starpost.core.settings import LicenseConfig, Settings


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
