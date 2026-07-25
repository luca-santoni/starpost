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


def test_legend_scale_slider_opens_at_the_plot_window_default(app, batch_dialog):
    # A new saved plot must start out at the size the plot window itself draws
    # the legend, not at the slider's 1.0x midpoint.
    from starpost.gui.views.plot_view import LEGEND_SCALE_DEFAULT

    dlg = batch_dialog
    assert dlg._legend_scale.value() < 50  # below the natural-size midpoint
    assert dlg._capture_plot()["legend_scale"] == pytest.approx(
        LEGEND_SCALE_DEFAULT, abs=0.01
    )


def test_saved_plot_captures_and_restores_legend_opacity(app, batch_dialog):
    dlg = batch_dialog
    dlg._legend_opacity.setValue(50)
    data = dlg._capture_plot()
    assert data["legend_opacity"] == 0.5
    dlg._legend_opacity.setValue(0)
    dlg._apply_plot(data)
    assert dlg._legend_opacity.value() == 50
