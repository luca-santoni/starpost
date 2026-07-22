"""Settings dialog: report/plot unit-system dropdowns load from and save to
Settings.report_unit_system / Settings.plot_unit_system."""
from __future__ import annotations

import pytest

import starpost.utils.paths as paths
from starpost.core.settings import Settings
from starpost.gui.views.settings_dialog import SettingsDialog


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    """Point every per-user location (config, cache, profiles) at a temp dir.

    All path helpers resolve through platformdirs, so patching its two directory
    functions isolates settings, profiles and the generated theme icons without
    touching the developer's real files."""
    monkeypatch.setattr(
        paths.platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path / "config")
    )
    monkeypatch.setattr(
        paths.platformdirs, "user_cache_dir", lambda *a, **k: str(tmp_path / "cache")
    )
    return tmp_path


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_unit_dropdowns_load_and_save(app):
    s = Settings()
    s.report_unit_system = "imperial"
    s.plot_unit_system = "si"
    dlg = SettingsDialog(s)
    # Loaded state reflects the settings.
    assert dlg._report_unit_system.currentData() == "imperial"
    assert dlg._plot_unit_system.currentData() == "si"
    # Change and save back into the settings object.
    dlg._report_unit_system.setCurrentIndex(
        dlg._report_unit_system.findData("default")
    )
    dlg._plot_unit_system.setCurrentIndex(
        dlg._plot_unit_system.findData("imperial")
    )
    dlg._on_accept()
    assert s.report_unit_system == "default"
    assert s.plot_unit_system == "imperial"
