"""Tests for BatchRunDialog behaviours not already covered in test_main_window.py."""
import pytest

import starpost.utils.paths as paths


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    """Point per-user config/cache at a temp dir so tests touch no real files."""
    monkeypatch.setattr(
        paths.platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path / "config")
    )
    monkeypatch.setattr(
        paths.platformdirs, "user_cache_dir", lambda *a, **k: str(tmp_path / "cache")
    )


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def batch_dialog(app):
    """A BatchRunDialog built exactly as the app does (see
    MainWindow._run_batch), with one result carrying a monitor plot so the
    Plots tab has something to select."""
    import starpost.gui.views.batch_run_dialog as brd
    from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, SimResult

    result = SimResult(
        sim_path="/c/a.sim",
        plots=[MonitorPlot(
            "Forces", [PlotSeries("Drag", [1, 2], [10.0, 9.0])],
            kind=PlotKind.FORCE,
        )],
    )
    dlg = brd.BatchRunDialog(monitor_groups={"Forces": ["Drag"]}, results=[result])
    yield dlg
    dlg.close()


def test_saved_plot_captures_and_restores_unit_system(app, batch_dialog):
    dlg = batch_dialog
    dlg._plot_unit_system.setCurrentIndex(dlg._plot_unit_system.findData("imperial"))
    data = dlg._capture_plot()
    assert data["unit_system"] == "imperial"
    # Round-trips back into the control.
    dlg._plot_unit_system.setCurrentIndex(dlg._plot_unit_system.findData("default"))
    dlg._apply_plot(data)
    assert dlg._plot_unit_system.currentData() == "imperial"
