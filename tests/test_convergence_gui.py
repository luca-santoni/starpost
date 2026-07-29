"""The Convergence window. Runs offscreen; touches no real config or cache."""
import numpy as np
import pytest

import starpost.utils.paths as paths
from starpost.core.convergence.config import ConvergenceConfig
from starpost.core.convergence.models import ConvergenceState
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
        # A genuine (if tiny) exponential approach, not pure white noise: the
        # iterative estimator needs real geometric structure to fit or it
        # declines (NO_ESTIMATE) and the ITERATIVE_ERROR_UNBOUNDED flag caps
        # confidence at Medium — correct for a monitor that is only noise,
        # but this fixture is meant to demonstrate the genuinely High-
        # confidence, everything-checks-out case end to end.
        qoi = 100.0 + 2.0 * (1.0 - np.exp(-np.arange(n) / 200.0)) + rng.normal(
            scale=1e-9, size=n)
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
    """R2/D2: this fixture's linear drift has no geometric structure for the
    iterative estimator, so the static-monitor escape hatch is denied and
    that gate's tested value is +inf. D2 stops that infinite gate from
    erasing the monitor's other margins, so the binding constraint now names
    the true binding gate with a compact unbounded caveat rather than a
    sentence saying nothing could be measured (see test_convergence_verdict
    .py's version of this test for the full mechanism)."""
    dlg = open_dialog(store_with(make_result("/tmp/b.sim", drifting=True)))
    assert "SLOW_DRIFT" in dlg._verdict_state.text()
    assert "Drag:" in dlg._verdict_binding.text()
    assert "iterative error unbounded" in dlg._verdict_binding.text()
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


def make_aggregate_and_element_result(path: str) -> SimResult:
    """One aggregate monitor ('Downforce ALL Monitor') and one per-element
    sibling ('Downforce wing front 1 Monitor'), so the auto-primary rule
    picks the aggregate and demotes the other."""
    n = 3000
    rng = np.random.default_rng(0)
    x = list(map(float, range(n)))
    qoi_all = 100.0 + 2.0 * (1.0 - np.exp(-np.arange(n) / 200.0)) + rng.normal(
        scale=1e-9, size=n)
    qoi_part = 10.0 + 0.5 * (1.0 - np.exp(-np.arange(n) / 200.0)) + rng.normal(
        scale=1e-9, size=n)
    residual = 10.0 ** (-np.arange(n, dtype=float) / 400.0) + 1e-12
    return SimResult(
        sim_path=path,
        plots=[
            MonitorPlot(name="Downforce plots", kind=PlotKind.FORCE, series=[
                PlotSeries(name="Downforce ALL Monitor", x=x, y=qoi_all.tolist()),
                PlotSeries(name="Downforce wing front 1 Monitor", x=x,
                          y=qoi_part.tolist()),
            ]),
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


def test_auto_primary_prefers_the_aggregate_and_a_manual_swap_still_works(app):
    """Regression for the aggregate-preferred auto-primary default: the
    aggregate starts ticked and its per-element sibling does not; unticking
    the aggregate and ticking the per-element monitor by hand must still
    re-run the assessment without error, honouring the manual choice."""
    from PySide6.QtCore import Qt

    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim")))
    assert dlg._monitor_table.item(0, 1).text() == "Downforce ALL Monitor"
    assert dlg._monitor_table.item(1, 1).text() == "Downforce wing front 1 Monitor"
    assert dlg._monitor_table.item(0, 0).checkState() == Qt.CheckState.Checked
    assert dlg._monitor_table.item(1, 0).checkState() == Qt.CheckState.Unchecked

    dlg._monitor_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    dlg._monitor_table.item(1, 0).setCheckState(Qt.CheckState.Checked)

    assessment = dlg._current()
    gates = {m.name: m.is_primary for m in assessment.monitors}
    assert gates["Downforce ALL Monitor"] is False
    assert gates["Downforce wing front 1 Monitor"] is True
    dlg.close()


def test_parse_percent_tolerates_a_percent_sign_with_no_space():
    """F4: the rendered cell is '0.1 %', but a user typing '0.2%' with no
    space hit float(text.split()[0]) failing on the glued '%' and silently
    reverting to the global preset — no error, just an edit that didn't take."""
    from starpost.gui.views.convergence_dialog import _parse_percent

    assert _parse_percent("0.2%") == pytest.approx(0.002)
    assert _parse_percent("0.2 %") == pytest.approx(0.002)
    assert _parse_percent("0.2") == pytest.approx(0.002)
    assert _parse_percent("not a number") is None


def test_g1_the_tolerance_column_shows_a_percent_suffix_and_edits_round_trip(app):
    """G1: the Tolerance column showed a bare number ('0.1') though the value
    is a percentage, which reads as an absolute tolerance. A '%' suffix must
    appear, and _parse_percent must still recover the value when the cell is
    edited (it already tolerates a trailing token)."""
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    cell = dlg._monitor_table.item(0, 2)
    assert cell.text().strip().endswith("%")
    assert cell.text().strip().startswith("0.1")   # screening preset, 0.1%

    path = dlg._results[0].sim_path
    dlg._monitor_table.item(0, 2).setText("0.2 %")
    assert dlg._monitor_configs[path]["Drag"].tolerance_fraction == pytest.approx(0.002)
    assert dlg._assessments[path].monitors[0].tolerance_fraction == pytest.approx(0.002)
    # the re-populated cell still carries the suffix after the edit round-trip
    assert dlg._monitor_table.item(0, 2).text().strip().endswith("%")
    dlg.close()


def test_f4_editing_the_tolerance_cell_with_no_space_before_the_percent_sign(app):
    """F4: '0.2 %' (with a space) always worked; a user typing '0.2%' with no
    space hit float(text.split()[0]) failing on the glued '%' and silently
    reverted to the global preset, with no error shown."""
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    path = dlg._results[0].sim_path
    dlg._monitor_table.item(0, 2).setText("0.2%")
    assert dlg._monitor_configs[path]["Drag"].tolerance_fraction == pytest.approx(0.002)
    assert dlg._assessments[path].monitors[0].tolerance_fraction == pytest.approx(0.002)
    dlg.close()


def test_g2_the_gate_table_header_names_the_iterative_error_column(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    headers = [dlg._gate_table.horizontalHeaderItem(c).text()
              for c in range(dlg._gate_table.columnCount())]
    assert "Iterative error" in headers
    dlg.close()


def test_g2_the_gate_table_shows_a_real_number_when_u_iter_is_unavailable(app):
    """G2: U_iter is None whenever the geometric-tail estimator declines —
    now common, including for the creeping-but-noisy monitors the C3 fix
    denies the escape hatch for. The iterative gate can still be the binding
    constraint, so the cell must show the value the gate was actually decided
    on rather than a blank dash."""
    n = 3000
    rng = np.random.default_rng(0)
    qoi = (100.0 - 1.09 * 0.9999 ** np.arange(n, dtype=float)
          + rng.normal(scale=1e-2, size=n))
    residual = 10.0 ** (-np.arange(n, dtype=float) / 400.0) + 1e-12
    x = list(map(float, range(n)))
    result = SimResult(
        sim_path="/tmp/creep.sim",
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
    dlg = open_dialog(store_with(result))
    monitor = dlg._assessments["/tmp/creep.sim"].monitors[0]
    assert monitor.iterative.u_iter is None             # the estimator declined

    headers = [dlg._gate_table.horizontalHeaderItem(c).text()
              for c in range(dlg._gate_table.columnCount())]
    column = headers.index("Iterative error")
    cell_text = dlg._gate_table.item(0, column).text()
    # The escape hatch is denied here (C3/F2: no geometric structure, but a
    # statistically and physically significant trend), so the gate's own
    # value is +inf and _iterative_cell must show "unbounded" specifically —
    # not merely "some non-dash string", which a stray blank or a wrong
    # fallback label would also satisfy.
    assert cell_text == "unbounded"
    dlg.close()


def _creeping_single_monitor_result(path: str = "/tmp/creep.sim") -> SimResult:
    """A single primary monitor whose iterative escape hatch is denied (same
    fixture as the G2 test above): the iterative gate's value is +inf, the
    exact R2 mechanism, but D2 stops that infinite gate from erasing the
    monitor's four other, perfectly good margins, so the index comes out a
    real number — never the false 0.0 a bare limit/inf division would give,
    and no longer None either now that the other gates supply a margin."""
    n = 3000
    rng = np.random.default_rng(0)
    qoi = (100.0 - 1.09 * 0.9999 ** np.arange(n, dtype=float)
          + rng.normal(scale=1e-2, size=n))
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


def test_r2_the_verdict_card_reports_an_unbounded_index_honestly(app):
    result = _creeping_single_monitor_result()
    dlg = open_dialog(store_with(result))
    a = dlg._assessments[result.sim_path]
    assert a.convergence_index is not None
    assert a.unbounded_primary_count == 1

    text = dlg._verdict_index.text()
    assert "0.00" not in text
    assert "unbounded" in text.lower()
    dlg.close()


def test_r2_the_summary_table_never_prints_an_unbounded_index_as_zero(app):
    from starpost.gui.views.convergence_dialog import _SUMMARY_COLUMNS

    result = _creeping_single_monitor_result()
    dlg = open_dialog(store_with(result))
    index_column = _SUMMARY_COLUMNS.index("Index")
    cell_text = dlg._summary.item(0, index_column).text()
    assert "0.00" not in cell_text
    assert "unbounded" in cell_text.lower()
    dlg.close()


def test_changing_the_tolerance_preset_re_runs_the_assessment(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    before = dlg._assessments["/tmp/a.sim"].monitors[0].tolerance_abs
    dlg._preset.setCurrentText("Production (0.05%)")
    after = dlg._assessments["/tmp/a.sim"].monitors[0].tolerance_abs
    assert after == pytest.approx(before / 2.0, rel=1e-6)
    dlg.close()


def _result_with_residual_decades(path: str, decades: float) -> SimResult:
    """A settled QoI beside a residual that plateaus after exactly ``decades``.
    Lets a test move the required-drop setting across the plateau and watch the
    verdict follow."""
    n = 3000
    rng = np.random.default_rng(0)
    qoi = 100.0 + 2.0 * (1.0 - np.exp(-np.arange(n) / 200.0)) + rng.normal(
        scale=1e-9, size=n)
    residual = np.concatenate([np.full(50, 1.0), np.full(n - 50, 10.0 ** -decades)])
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


def test_the_required_residual_drop_defaults_to_the_published_figure(app):
    """3 decades is the ASME Journal of Fluids Engineering editorial policy's
    requirement, and the control must not quietly ship something else."""
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert dlg._d_min.value() == pytest.approx(ConvergenceConfig().d_min)
    assert dlg._d_min.value() == pytest.approx(3.0)
    dlg.close()


def test_lowering_the_required_residual_drop_can_clear_a_stalled_verdict(app):
    """The case this control exists for: a run whose loads are settled well
    inside tolerance while its residuals plateau short of 3 decades. Whether
    that counts as converged is the engineer's judgement, so the requirement is
    theirs to set — and changing it must re-run the assessment."""
    dlg = open_dialog(store_with(_result_with_residual_decades("/tmp/a.sim", 2.5)))

    assert dlg._assessments["/tmp/a.sim"].state is ConvergenceState.STALLED
    assert "2.5 of 3 required decades" in \
        dlg._assessments["/tmp/a.sim"].binding_constraint

    dlg._d_min.setValue(2.0)
    dlg._flush_pending_reassess()

    assert dlg._assessments["/tmp/a.sim"].state is ConvergenceState.CONVERGED
    dlg.close()


def test_turbulence_equations_are_never_held_stricter_than_the_primary_ones(app):
    """Turbulence residuals routinely stall one to two orders above the
    momentum residuals without harming the QoIs, which is why they carry a
    weaker requirement. Lowering the primary requirement below that default
    would invert the relationship, so it is clamped."""
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    default_turb = ConvergenceConfig().d_min_turb

    dlg._d_min.setValue(1.0)
    config = dlg._config_for(dlg._results[0])
    assert config.d_min == pytest.approx(1.0)
    assert config.d_min_turb == pytest.approx(1.0)

    dlg._d_min.setValue(4.0)
    config = dlg._config_for(dlg._results[0])
    assert config.d_min == pytest.approx(4.0)
    assert config.d_min_turb == pytest.approx(default_turb)
    dlg.close()


def test_changing_the_required_residual_drop_keeps_the_selected_data_set(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim"),
                                 make_result("/tmp/b.sim", drifting=True)))
    dlg._summary.selectRow(1)
    dlg._d_min.setValue(4.0)
    dlg._flush_pending_reassess()
    assert dlg._summary.currentRow() == 1
    dlg.close()


def test_changing_the_tolerance_preset_keeps_the_selected_data_set(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim"),
                                 make_result("/tmp/b.sim", drifting=True)))
    dlg._summary.selectRow(1)
    assert "SLOW_DRIFT" in dlg._verdict_state.text()

    dlg._preset.setCurrentText("Production (0.05%)")

    assert dlg._summary.currentRow() == 1
    assert dlg._summary.item(dlg._summary.currentRow(), 0).text() == "b"
    assert "SLOW_DRIFT" in dlg._verdict_state.text()
    dlg.close()


def test_editing_a_monitor_checkbox_keeps_the_selected_data_set(app):
    from PySide6.QtCore import Qt

    dlg = open_dialog(store_with(make_result("/tmp/a.sim"),
                                 make_result("/tmp/b.sim", drifting=True)))
    dlg._summary.selectRow(1)
    assert "SLOW_DRIFT" in dlg._verdict_state.text()

    dlg._monitor_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)

    # Unticking the only primary monitor changes the verdict (see
    # test_unticking_the_only_primary_monitor_drops_confidence_to_low), so
    # what this test cares about is that the *selection* survived the edit,
    # not that the verdict text is unchanged.
    assert dlg._summary.currentRow() == 1
    assert dlg._summary.item(dlg._summary.currentRow(), 0).text() == "b"
    assert dlg._current() is dlg._assessments["/tmp/b.sim"]
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


def test_select_all_marks_every_monitor_primary(app):
    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim")))
    dlg._select_all_btn.click()
    assessment = dlg._current()
    assert {m.name for m in assessment.monitors if m.is_primary} == {
        "Downforce ALL Monitor", "Downforce wing front 1 Monitor"}
    dlg.close()


def test_clear_leaves_no_primary_and_says_so_rather_than_erroring(app):
    """Clearing every primary is a valid state, not a failure: it is the
    midpoint of "clear, then tick the one I want". The verdict reports it
    honestly instead of forcing a minimum selection."""
    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim")))
    dlg._clear_btn.click()
    assert not any(m.is_primary for m in dlg._current().monitors)
    assert "no primary QoI declared" in dlg._verdict_binding.text()
    assert "Low" in dlg._verdict_confidence.text()
    dlg.close()


def test_reset_to_auto_restores_the_aggregate_preferred_choice_after_a_clear(app):
    """Without a tri-state override there would be no way back to the tool's
    own choice short of closing and reopening the window."""
    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim")))
    dlg._clear_btn.click()
    assert not any(m.is_primary for m in dlg._current().monitors)
    dlg._reset_btn.click()
    assert {m.name for m in dlg._current().monitors if m.is_primary} == {
        "Downforce ALL Monitor"}
    dlg.close()


def test_reset_to_auto_keeps_a_tolerance_override(app):
    """Reset hands back the *primary* choice only. The button sits in a
    primary-selection group, so silently discarding an unrelated per-monitor
    tolerance edit would be scope the label does not advertise."""
    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim")))
    path = dlg._results[0].sim_path
    assert dlg._monitor_table.item(0, 1).text() == "Downforce ALL Monitor"
    dlg._monitor_table.item(0, 2).setText("0.2 %")
    dlg._reset_btn.click()
    assert dlg._monitor_configs[path]["Downforce ALL Monitor"].tolerance_fraction == (
        pytest.approx(0.002))
    aggregate = next(m for m in dlg._current().monitors
                     if m.name == "Downforce ALL Monitor")
    assert aggregate.tolerance_fraction == pytest.approx(0.002)
    assert aggregate.is_primary is True
    dlg.close()


def test_a_bulk_click_re_assesses_once_not_once_per_monitor(app, monkeypatch):
    """The buttons write the configuration and re-assess once. Driving the
    checkboxes instead would emit itemChanged per row, and _on_monitor_edited
    re-assesses *every* loaded data set — 2 monitors x 2 sims here, but 40 x
    10 on a real workspace, i.e. 400 assessments for one click."""
    import starpost.gui.views.convergence_dialog as module

    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim"),
                                 make_aggregate_and_element_result("/tmp/b.sim")))
    calls = []
    real_assess = module.assess

    def counting_assess(*args, **kwargs):
        calls.append(1)
        return real_assess(*args, **kwargs)

    monkeypatch.setattr(module, "assess", counting_assess)
    dlg._select_all_btn.click()
    # One assess() per loaded data set, for exactly one re-assessment pass.
    assert len(calls) == 2
    dlg.close()


def test_the_bulk_buttons_are_disabled_with_no_data_sets_loaded(app):
    dlg = open_dialog(store_with())
    assert dlg._select_all_btn.isEnabled() is False
    assert dlg._clear_btn.isEnabled() is False
    assert dlg._reset_btn.isEnabled() is False
    dlg.close()


def test_the_bulk_buttons_are_enabled_once_a_data_set_is_loaded(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert dlg._select_all_btn.isEnabled() is True
    assert dlg._clear_btn.isEnabled() is True
    assert dlg._reset_btn.isEnabled() is True
    dlg.close()


def test_the_custom_tolerance_row_greys_out_unless_that_preset_is_picked(app):
    """The custom field only feeds _tolerance_fraction when the preset is
    "Custom", so otherwise both it and the label naming it must read as
    inactive. The label is half of this: a live "Custom" beside a dead field
    still reads as an input you may edit."""
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert dlg._custom.isEnabled() is False
    assert dlg._custom_label.isEnabled() is False

    dlg._preset.setCurrentText("Custom")
    assert dlg._custom.isEnabled() is True
    assert dlg._custom_label.isEnabled() is True

    dlg._preset.setCurrentText("Production (0.05%)")
    assert dlg._custom.isEnabled() is False
    assert dlg._custom_label.isEnabled() is False
    dlg.close()


def test_typing_in_a_spin_box_coalesces_into_one_reassessment(app, monkeypatch):
    """QDoubleSpinBox emits valueChanged once per keystroke, and every
    re-assessment walks *all* loaded data sets. Typing "0.2534" therefore ran
    four full passes — measured at 6.7 s on ten real car-aero exports, with
    the window locked throughout. A burst now collapses into one pass once
    typing stops."""
    import starpost.gui.views.convergence_dialog as module

    dlg = open_dialog(store_with(make_result("/tmp/a.sim"),
                                 make_result("/tmp/b.sim", drifting=True)))
    calls = []
    real_assess = module.assess

    def counting_assess(*args, **kwargs):
        calls.append(1)
        return real_assess(*args, **kwargs)

    monkeypatch.setattr(module, "assess", counting_assess)

    for value in (3.5, 4.0, 4.5, 5.0):
        dlg._d_min.setValue(value)
    # Still mid-burst: no work has been done yet.
    assert calls == []

    dlg._flush_pending_reassess()
    # One pass, i.e. one assess() per loaded data set — not four passes.
    assert len(calls) == 2
    # The pass uses the value typed last, not the first one seen.
    assert dlg._config_for(dlg._results[0]).d_min == pytest.approx(5.0)
    dlg.close()


def test_a_discrete_edit_still_reassesses_immediately(app, monkeypatch):
    """Only the spin boxes debounce. A preset choice, a checkbox and a bulk
    button are each a single deliberate action with no burst to coalesce, so
    they must not make the user wait out a timer."""
    from PySide6.QtCore import Qt

    import starpost.gui.views.convergence_dialog as module

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    calls = []
    real_assess = module.assess

    def counting_assess(*args, **kwargs):
        calls.append(1)
        return real_assess(*args, **kwargs)

    monkeypatch.setattr(module, "assess", counting_assess)

    dlg._preset.setCurrentText("Production (0.05%)")
    assert len(calls) == 1
    dlg._clear_btn.click()
    assert len(calls) == 2
    dlg._monitor_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    assert len(calls) == 3
    dlg.close()


def test_the_export_button_follows_the_loaded_data_sets(app):
    dlg = open_dialog(store_with())
    assert dlg._export_btn.isEnabled() is False
    dlg.close()

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert dlg._export_btn.isEnabled() is True
    dlg.close()


def test_exporting_writes_the_four_tables(app, monkeypatch, tmp_path):
    """The window exports every loaded data set, not just the selected row:
    the summary is a cross-run comparison."""
    import starpost.gui.views.convergence_dialog as module

    dlg = open_dialog(store_with(make_result("/tmp/a.sim"),
                                 make_result("/tmp/b.sim", drifting=True)))
    target = tmp_path / "study.csv"
    monkeypatch.setattr(
        module.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "CSV file (*.csv)")),
    )
    shown: list[str] = []
    monkeypatch.setattr(module.QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a[2])))

    dlg._on_export()

    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["study-qoi-gates.csv", "study-reasons.csv",
                       "study-residuals.csv", "study-summary.csv"]
    # Parse rather than substring-match: a bare "a" appears in almost any CSV.
    import csv as csv_module

    with (tmp_path / "study-summary.csv").open() as fh:
        rows = list(csv_module.DictReader(fh))
    assert [r["Data set"] for r in rows] == ["a", "b"]
    assert shown and "study-summary.csv" in shown[0]
    dlg.close()


def test_every_save_filter_maps_to_a_format_the_writer_supports():
    """The dialog offers four filters and the writer accepts four formats;
    a filter naming a format the writer rejects would fail only at the moment
    the user tried to save."""
    from starpost.core.convergence.export import SUPPORTED_FORMATS
    from starpost.gui.views.convergence_dialog import _EXPORT_FILTERS

    assert set(_EXPORT_FILTERS.values()) == set(SUPPORTED_FORMATS)


def test_a_cancelled_save_dialog_writes_nothing(app, monkeypatch, tmp_path):
    import starpost.gui.views.convergence_dialog as module

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    dlg._on_export()
    assert list(tmp_path.iterdir()) == []
    dlg.close()


def test_an_export_failure_is_reported_rather_than_swallowed(app, monkeypatch,
                                                             tmp_path):
    """Silently failing an export is worse than failing slowly — the user
    would believe they have a record they do not have."""
    import starpost.gui.views.convergence_dialog as module

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    monkeypatch.setattr(
        module.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "x.csv"), "CSV file (*.csv)")),
    )

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(module, "write_assessment", boom)
    errors: list[str] = []
    monkeypatch.setattr(module.QMessageBox, "critical",
                        staticmethod(lambda *a, **k: errors.append(a[2])))

    dlg._on_export()

    assert errors and "disk full" in errors[0]
    dlg.close()
