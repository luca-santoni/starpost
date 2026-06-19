import pytest

from starpost.core import updater


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("1.2.0", "1.1.0", True),
        ("1.1.1", "1.1.0", True),
        ("2.0.0", "1.9.9", True),
        ("1.1.0", "1.1.0", False),   # equal
        ("1.0.0", "1.1.0", False),   # older
        ("1.1", "1.1.0", False),     # 1.1 == 1.1.0 (padding)
        ("1.1.0", "1.1", False),     # symmetric
        ("v1.2.0", "1.1.0", True),   # leading v tolerated
        ("1.2.0-rc1", "1.1.0", True),  # pre-release suffix ignored on core
    ],
)
def test_is_newer(latest, current, expected):
    assert updater.is_newer(latest, current) is expected


def test_parse_version_strips_prefix_and_suffix():
    assert updater._parse_version("v1.2.3-beta2") == (1, 2, 3)
    assert updater._parse_version("1.0") == (1, 0)
    assert updater._parse_version("garbage") == (0,)


def test_select_installer_asset_picks_setup_exe():
    assets = [
        {"name": "StarPost-1.2.0-x86_64.AppImage"},
        {"name": "StarPost-1.2.0-Setup.exe"},
        {"name": "source.zip"},
    ]
    asset = updater._select_installer_asset(assets)
    assert asset is not None
    assert asset["name"] == "StarPost-1.2.0-Setup.exe"


def test_select_installer_asset_none_when_absent():
    assets = [{"name": "StarPost-1.2.0-x86_64.AppImage"}, {"name": "notes.txt"}]
    assert updater._select_installer_asset(assets) is None


def test_check_for_update_returns_none_when_current(monkeypatch):
    # Same version as the running app -> no update.
    monkeypatch.setattr(
        updater,
        "_get_json",
        lambda url, timeout: {"tag_name": updater.current_version(), "assets": []},
    )
    assert updater.check_for_update() is None


def test_check_for_update_returns_info_when_newer(monkeypatch):
    fake = {
        "tag_name": "99.0.0",
        "html_url": "https://example.test/releases/99.0.0",
        "body": "Shiny new things.",
        "assets": [
            {
                "name": "StarPost-99.0.0-Setup.exe",
                "browser_download_url": "https://example.test/StarPost-99.0.0-Setup.exe",
                "size": 1234,
                "digest": "sha256:abc123",
            }
        ],
    }
    monkeypatch.setattr(updater, "_get_json", lambda url, timeout: fake)

    info = updater.check_for_update()
    assert info is not None
    assert info.latest == "99.0.0"
    assert info.asset_name == "StarPost-99.0.0-Setup.exe"
    assert info.sha256 == "abc123"
    assert info.size == 1234
    assert info.notes == "Shiny new things."


def test_check_for_update_raises_without_installer_asset(monkeypatch):
    fake = {"tag_name": "99.0.0", "assets": [{"name": "StarPost-99.0.0.AppImage"}]}
    monkeypatch.setattr(updater, "_get_json", lambda url, timeout: fake)
    with pytest.raises(updater.UpdateError):
        updater.check_for_update()
