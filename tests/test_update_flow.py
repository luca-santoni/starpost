from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from starpost.core.updater import UpdateInfo
from starpost.gui.update import _UpdateFlow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _info() -> UpdateInfo:
    return UpdateInfo(
        current="1.1.0",
        latest="1.2.0",
        asset_name="StarPost-1.2.0-Setup.exe",
        download_url="",
        size=0,
        sha256="",
        release_url="http://example/release",
        notes="",
    )


def test_on_update_available_fires_when_newer(app):
    """When the check finds a newer release, the callback runs (so the UI can
    reveal its 'New update available' note); the install prompt still follows."""
    calls = []
    flow = _UpdateFlow(
        QWidget(), silent_if_current=True, on_update_available=calls.append
    )
    with patch.object(_UpdateFlow, "_prompt_and_apply", lambda self, info: None):
        flow._on_checked(_info())
    assert len(calls) == 1
    assert calls[0].latest == "1.2.0"


def test_on_update_available_silent_when_current(app):
    """No newer release -> the callback is not invoked."""
    calls = []
    flow = _UpdateFlow(
        QWidget(), silent_if_current=True, on_update_available=calls.append
    )
    flow._on_checked(None)
    assert calls == []
