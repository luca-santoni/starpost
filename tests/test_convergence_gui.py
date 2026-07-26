"""The Convergence window. Runs offscreen; touches no real config or cache."""
import numpy as np
import pytest

import starpost.utils.paths as paths
from starpost.core.settings import Settings
from starpost.data.models import (
    MonitorPlot,
    PlotKind,
    PlotSeries,
    PropertyGroup,
    SimProperties,
    SimResult,
)
from starpost.data.store import ResultStore


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
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


def make_result(path: str, drifting: bool = False) -> SimResult:
    n = 3000
    rng = np.random.default_rng(0)
    if drifting:
        qoi = 100.0 + 0.01 * np.arange(n, dtype=float)
    else:
        qoi = 100.0 + rng.normal(scale=1e-5, size=n)
    residual = 10.0 ** (-np.arange(n, dtype=float) / 400.0) + 1e-12
    x = list(map(float, range(n)))
    return SimResult(
        sim_path=path,
        plots=[
            MonitorPlot(name="Drag Monitor Plot", kind=PlotKind.FORCE,
                        series=[PlotSeries(name="Drag", x=x, y=qoi.tolist())]),
            MonitorPlot(name="Residuals", kind=PlotKind.RESIDUAL,
                        series=[PlotSeries(name="Continuity", x=x,
                                           y=residual.tolist())]),
        ],
        properties=SimProperties(groups=[
            PropertyGroup(section="continuum", name="P",
                          entries=[("models", "Steady; Segregated Flow")]),
            PropertyGroup(section="convergence", name="", entries=[
                ("precision", "double"), ("residual_normalization", "auto")]),
        ]),
    )


def store_with(*results) -> ResultStore:
    store = ResultStore()
    for r in results:
        store.put(r)
    return store


def open_dialog(store):
    from starpost.gui.views.convergence_dialog import ConvergenceDialog

    return ConvergenceDialog(store, Settings())


def test_the_window_assesses_every_loaded_data_set(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim"),
                                 make_result("/tmp/b.sim", drifting=True)))
    assert dlg._summary.rowCount() == 2
    dlg.close()


def test_a_settled_run_reads_as_converged(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert "CONVERGED" in dlg._verdict_state.text()
    assert "High" in dlg._verdict_confidence.text()
    dlg.close()


def test_a_drifting_run_names_its_binding_constraint(app):
    dlg = open_dialog(store_with(make_result("/tmp/b.sim", drifting=True)))
    assert "SLOW_DRIFT" in dlg._verdict_state.text()
    assert "Drag" in dlg._verdict_binding.text()
    dlg.close()


def test_the_reasons_list_is_populated_and_severity_ordered(app):
    dlg = open_dialog(store_with(make_result("/tmp/b.sim", drifting=True)))
    assert dlg._reasons.topLevelItemCount() > 0
    severities = [dlg._reasons.topLevelItem(i).text(0)
                  for i in range(dlg._reasons.topLevelItemCount())]
    order = ["error", "warning", "info"]
    assert [order.index(s) for s in severities] == sorted(
        order.index(s) for s in severities
    )
    dlg.close()


def test_the_detail_tabs_show_residuals_and_gates(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert dlg._residual_table.rowCount() == 1        # Continuity
    assert dlg._gate_table.rowCount() == 1            # Drag
    dlg.close()


def test_force_monitors_are_ticked_primary_by_default(app):
    """A verdict with no primary QoI is not a verdict, so force-like monitors
    are primary out of the box."""
    from PySide6.QtCore import Qt

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert dlg._monitor_table.item(0, 0).checkState() == Qt.CheckState.Checked
    dlg.close()


def test_unticking_the_only_primary_monitor_drops_confidence_to_low(app):
    from PySide6.QtCore import Qt

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    dlg._monitor_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert "Low" in dlg._verdict_confidence.text()
    dlg.close()


def test_changing_the_tolerance_preset_re_runs_the_assessment(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    before = dlg._assessments["/tmp/a.sim"].monitors[0].tolerance_abs
    dlg._preset.setCurrentText("Production (0.05%)")
    after = dlg._assessments["/tmp/a.sim"].monitors[0].tolerance_abs
    assert after == pytest.approx(before / 2.0, rel=1e-6)
    dlg.close()


def test_selecting_a_summary_row_switches_the_detail_panes(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim"),
                                 make_result("/tmp/b.sim", drifting=True)))
    dlg._summary.selectRow(1)
    assert "SLOW_DRIFT" in dlg._verdict_state.text()
    dlg._summary.selectRow(0)
    assert "CONVERGED" in dlg._verdict_state.text()
    dlg.close()


def test_an_empty_store_shows_a_placeholder_and_does_not_raise(app):
    dlg = open_dialog(ResultStore())
    assert dlg._summary.rowCount() == 0
    assert "No data sets" in dlg._verdict_state.text()
    dlg.close()


def test_reload_re_snapshots_the_store(app):
    store = store_with(make_result("/tmp/a.sim"))
    dlg = open_dialog(store)
    store.put(make_result("/tmp/b.sim", drifting=True))
    dlg.reload()
    assert dlg._summary.rowCount() == 2
    dlg.close()


def test_failed_extractions_are_skipped(app):
    store = store_with(make_result("/tmp/a.sim"),
                       SimResult(sim_path="/tmp/bad.sim", error="extraction failed"))
    dlg = open_dialog(store)
    assert dlg._summary.rowCount() == 1
    dlg.close()
