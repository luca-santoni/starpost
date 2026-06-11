from starpost.core.settings import LicenseConfig


def test_podkey_server_args():
    lic = LicenseConfig(mode="podkey_server", podkey="ABC", licpath="1999@licsrv")
    assert lic.cli_args() == ["-power", "-podkey", "ABC", "-licpath", "1999@licsrv"]


def test_license_file_args():
    lic = LicenseConfig(mode="license_file", license_file="/opt/lic/star.lic")
    assert lic.cli_args() == ["-licpath", "/opt/lic/star.lic"]


def test_podkey_server_omits_empty_fields():
    lic = LicenseConfig(mode="podkey_server", podkey="", licpath="")
    assert lic.cli_args() == ["-power"]
