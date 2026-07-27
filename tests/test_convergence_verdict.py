"""Roll-up: state, confidence, convergence index, binding constraint, reasons.
Includes validation case V10 and the end-to-end integration tests."""
import math

import numpy as np
import pytest

from starpost.core.convergence import assess
from starpost.core.convergence.config import ConvergenceConfig, MonitorConfig
from starpost.core.convergence.models import (
    AdvisoryFlag,
    Confidence,
    ConvergenceState,
    MetadataField,
    Provenance,
    RunMetadata,
    Severity,
)
from starpost.core.convergence.steady import assess_monitor
from starpost.core.convergence.verdict import roll_up
from starpost.data.models import (
    MonitorPlot,
    PlotKind,
    PlotSeries,
    PropertyGroup,
    SimProperties,
    SimResult,
)

CLASSIFICATION = {
    "residual_keywords": ["residual", "residuals"],
    "force_keywords": ["force", "drag", "lift", "moment", "cd", "cl"],
}


def converged_qoi(n: int = 3000, mean: float = 100.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return mean + rng.normal(scale=1e-5, size=n)


def qoi_with_geometric_decay(n: int = 3000, seed: int = 1) -> np.ndarray:
    """Unlike ``converged_qoi``, this settles by a genuine exponential
    approach (the same shape as V2 in test_convergence_steady.py), so its
    change series has real geometric structure and the iterative estimator
    is valid. ``converged_qoi``'s pure white noise has no such structure —
    |diff| does not decay with iteration at all — so its iterative estimator
    always declines (NO_ESTIMATE) and, after the F5 fix, ITERATIVE_ERROR_
    UNBOUNDED correctly caps its confidence at Medium. This helper is what a
    genuinely High-confidence end-to-end case looks like."""
    rng = np.random.default_rng(seed)
    return 2.0 * (1.0 - np.exp(-np.arange(n) / 200.0)) + rng.normal(scale=1e-9, size=n)


def healthy_residual(n: int = 3000) -> np.ndarray:
    return 10.0 ** (-np.arange(n, dtype=float) / 400.0) + 1e-12


def make_result(qoi: np.ndarray, residual: np.ndarray | None = None,
                *, models: str = "Steady; Segregated Flow",
                convergence_rows: list[tuple[str, str]] | None = None,
                qoi_name: str = "Drag") -> SimResult:
    plots = [MonitorPlot(
        name=f"{qoi_name} Monitor Plot", kind=PlotKind.FORCE,
        series=[PlotSeries(name=qoi_name, x=list(map(float, range(qoi.size))),
                           y=qoi.tolist())],
    )]
    if residual is not None:
        plots.append(MonitorPlot(
            name="Residuals", kind=PlotKind.RESIDUAL,
            series=[PlotSeries(name="Continuity",
                               x=list(map(float, range(residual.size))),
                               y=residual.tolist())],
        ))
    groups = [PropertyGroup(section="continuum", name="Physics 1",
                            entries=[("models", models)])]
    if convergence_rows:
        groups.append(PropertyGroup(section="convergence", name="",
                                    entries=convergence_rows))
    return SimResult(sim_path="/tmp/case.sim", plots=plots,
                     properties=SimProperties(groups=groups))


def primary(name: str = "Drag", **kw) -> ConvergenceConfig:
    return ConvergenceConfig(monitors={name: MonitorConfig(is_primary=True, **kw)})


def make_multi_monitor_result(monitor_names: list[str], *, n: int = 3000,
                              residual: np.ndarray | None = None,
                              plot_name: str = "Force plots") -> SimResult:
    """A single FORCE-kind plot carrying one series per monitor name — the
    shape STAR-CCM+ actually exports when several report monitors are
    grouped into one plot (see the real SDM25-RW-014 car-aero data set,
    whose naming this backs the aggregate-vs-per-element tests below)."""
    plots = [MonitorPlot(
        name=plot_name, kind=PlotKind.FORCE,
        series=[PlotSeries(name=name, x=list(map(float, range(n))),
                           y=converged_qoi(n, seed=i).tolist())
               for i, name in enumerate(monitor_names)],
    )]
    if residual is not None:
        plots.append(MonitorPlot(
            name="Residuals", kind=PlotKind.RESIDUAL,
            series=[PlotSeries(name="Continuity",
                               x=list(map(float, range(residual.size))),
                               y=residual.tolist())],
        ))
    groups = [PropertyGroup(section="continuum", name="Physics 1",
                            entries=[("models", "Steady; Segregated Flow")])]
    return SimResult(sim_path="/tmp/multi.sim", plots=plots,
                     properties=SimProperties(groups=groups))


# --- aggregate-preferred auto-primary selection -----------------------------

def test_an_aggregate_among_per_element_monitors_is_the_only_auto_primary():
    names = ["Downforce ALL Monitor", "Downforce wing front 1 Monitor",
             "Downforce wing front 2 Monitor"]
    result = make_multi_monitor_result(names, residual=healthy_residual())
    a = assess(result, ConvergenceConfig(), CLASSIFICATION)
    assert {m.name for m in a.monitors if m.is_primary} == {"Downforce ALL Monitor"}
    non_primary = {m.name for m in a.monitors if not m.is_primary}
    assert non_primary == {"Downforce wing front 1 Monitor",
                           "Downforce wing front 2 Monitor"}


def test_no_detectable_aggregate_falls_back_to_marking_every_match_primary():
    names = ["Downforce wing front 1 Monitor", "Downforce wing front 2 Monitor",
             "Drag wing rear 1 Monitor"]
    result = make_multi_monitor_result(names, residual=healthy_residual())
    a = assess(result, ConvergenceConfig(), CLASSIFICATION)
    assert {m.name for m in a.monitors if m.is_primary} == set(names)


def test_whole_word_aggregate_matching_excludes_a_wall_monitor():
    """A naive substring test ('all' in name.lower()) would wrongly treat
    'Downforce wall Monitor' as an aggregate."""
    names = ["Downforce wall Monitor", "Downforce ALL Monitor"]
    result = make_multi_monitor_result(names, residual=healthy_residual())
    a = assess(result, ConvergenceConfig(), CLASSIFICATION)
    assert {m.name for m in a.monitors if m.is_primary} == {"Downforce ALL Monitor"}
    wall = next(m for m in a.monitors if m.name == "Downforce wall Monitor")
    assert wall.is_primary is False


def test_explicit_override_beats_the_auto_aggregate_choice_in_both_directions():
    names = ["Downforce ALL Monitor", "Downforce wing front 1 Monitor"]
    result = make_multi_monitor_result(names, residual=healthy_residual())
    config = ConvergenceConfig(monitors={
        "Downforce ALL Monitor": MonitorConfig(is_primary=False),
        "Downforce wing front 1 Monitor": MonitorConfig(is_primary=True),
    })
    a = assess(result, config, CLASSIFICATION)
    assert {m.name for m in a.monitors if m.is_primary} == {
        "Downforce wing front 1 Monitor"
    }


def test_the_real_car_aero_naming_shape_selects_only_the_two_all_monitors():
    """Mirrors the naming shape of the real SDM25-RW-014 car-aero data set
    (see .superpowers/sdd/aggregate-primary-report.md for the actual run):
    40 monitors total, 36 of which match a force keyword — 18 Downforce
    sub-components (17 per-element + 1 ALL) and the same 18-way split for
    Drag. Before this change all 36 became primary and the headline verdict
    rode on whichever sub-component was noisiest; now only the two ALL
    monitors gate it."""
    downforce_parts = [
        "Downforce undertray Monitor",
        *(f"Downforce wing front {i} Monitor" for i in range(1, 7)),
        *(f"Downforce wing rear {i} Monitor" for i in range(1, 6)),
        *(f"Downforce wing side {i} Monitor" for i in range(1, 4)),
        "Downforce duct Monitor", "Downforce Center body Monitor",
    ]
    drag_parts = [name.replace("Downforce", "Drag") for name in downforce_parts]
    names = (downforce_parts + ["Downforce ALL Monitor"]
             + drag_parts + ["Drag ALL Monitor"])
    assert len(names) == 36
    result = make_multi_monitor_result(names, residual=healthy_residual())
    a = assess(result, ConvergenceConfig(), CLASSIFICATION)
    assert len(a.monitors) == 36
    assert {m.name for m in a.monitors if m.is_primary} == {
        "Downforce ALL Monitor", "Drag ALL Monitor"
    }


def test_the_reasons_explain_which_monitors_were_auto_selected_and_why():
    names = ["Downforce ALL Monitor", "Downforce wing front 1 Monitor"]
    result = make_multi_monitor_result(names, residual=healthy_residual())
    a = assess(result, ConvergenceConfig(), CLASSIFICATION)
    info = [r for r in a.reasons if r.severity is Severity.INFO]
    assert any("Downforce ALL Monitor" in r.message
               and "aggregate" in r.message.lower() for r in info)


def test_the_reasons_explain_the_fallback_when_no_aggregate_is_detected():
    names = ["Downforce wing front 1 Monitor", "Downforce wing front 2 Monitor"]
    result = make_multi_monitor_result(names, residual=healthy_residual())
    a = assess(result, ConvergenceConfig(), CLASSIFICATION)
    info = [r for r in a.reasons if r.severity is Severity.INFO]
    assert any("no aggregate" in r.message.lower() for r in info)


def test_an_auto_selected_reason_is_not_added_when_every_match_is_overridden():
    """The auto-selection note names what the auto rule decided; a monitor
    the user explicitly overrode is that override's doing, not the rule's, so
    it must not be credited to the auto note."""
    result = make_result(converged_qoi(), healthy_residual())
    a = assess(result, primary(), CLASSIFICATION)
    info = [r for r in a.reasons if r.severity is Severity.INFO]
    assert not any("auto-selected" in r.message.lower() for r in info)


# --- end-to-end states -----------------------------------------------------

def test_a_healthy_settled_run_is_converged():
    """Uses qoi_with_geometric_decay rather than converged_qoi: a genuine
    decaying approach is what lets the iterative estimator produce a real
    bound, so this is the case that legitimately earns High confidence."""
    result = make_result(qoi_with_geometric_decay(), healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.CONVERGED
    assert a.convergence_index > 1.0
    assert a.confidence is Confidence.HIGH


def test_a_static_noisy_run_keeps_its_flag_but_not_the_confidence_cap():
    """converged_qoi has no geometric decay to fit — the change series is pure
    noise around a fixed mean — so the iterative estimator always declines and
    the remaining error is never bounded. The flag and the reason must still
    be raised, because that is true and worth telling the user.

    Confidence must NOT be capped here, though. The estimator declines for
    *every* settled monitor with ordinary noise, so capping on decline alone
    made High unreachable for essentially every well-converged run — the same
    trap INCOMPLETE_EVIDENCE is deliberately kept out of the confidence rule
    to avoid. This monitor's largest single-iteration change is ~0.05% of its
    tolerance; it is as static as a signal gets, and the missing bound on a
    tail that small is immaterial."""
    result = make_result(converged_qoi(), healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.CONVERGED
    assert a.confidence is Confidence.HIGH
    assert AdvisoryFlag.ITERATIVE_ERROR_UNBOUNDED in a.flags
    assert any("iterative error could not be bounded" in r.message.lower()
              and r.target == "Drag" for r in a.reasons)
    assert "unbounded" not in a.confidence_rule.lower()


def test_the_unbounded_confidence_cap_scales_with_the_fallback_evidence():
    """The cap must discriminate, not fire on everything. Sweeping the noise
    scale moves the only evidence the escape hatch has — the largest
    single-iteration change — across the threshold, and confidence must
    follow it. A monitor barely moving keeps High; one still moving at an
    appreciable fraction of its tolerance drops to Medium.

    Asserted against the gate's own tested quantity rather than against the
    noise scale, so the test pins the rule and not a particular fixture."""
    seen = set()
    for scale in (1e-6, 1e-5, 1e-4, 1e-3, 1e-2):
        rng = np.random.default_rng(0)
        qoi = 100.0 + rng.normal(scale=scale, size=3000)
        result = make_result(qoi, healthy_residual(),
                             convergence_rows=[("precision", "double"),
                                               ("residual_normalization", "auto")])
        a = assess(result, primary(), CLASSIFICATION)
        monitor = a.monitors[0]
        gate = next(g for g in monitor.gates if g.name == "iterative error")
        ratio = gate.value / monitor.tolerance_abs
        cap = ConvergenceConfig().iterative_unbounded_confidence_fraction
        assert a.state is ConvergenceState.CONVERGED, scale
        assert AdvisoryFlag.ITERATIVE_ERROR_UNBOUNDED in a.flags, scale
        expected = Confidence.MEDIUM if ratio > cap else Confidence.HIGH
        assert a.confidence is expected, f"scale={scale} ratio={ratio:.5f}"
        seen.add(expected)
    # Both outcomes must actually occur, or the sweep proves nothing.
    assert seen == {Confidence.HIGH, Confidence.MEDIUM}


def test_a_drifting_run_is_slow_drift_and_names_its_binding_constraint():
    """R2: this linear drift fails the drift gate with a real, finite margin,
    but a pure linear ramp has no geometric structure for the iterative
    estimator to fit, and Mann-Kendall resolves the trend overwhelmingly
    strongly (see steady.py) — so the static-monitor escape hatch is denied
    and the iterative gate's tested quantity is +inf, the exact R2 mechanism.
    With only one primary monitor and it unbounded, the index is honestly
    None (never the 0.0 a bare limit/inf division would give) and the
    binding constraint says so by name rather than a false-precision number."""
    n, window = 3000, 600
    eps = ConvergenceConfig().tolerance_fraction * 100.0
    qoi = 100.0 + (4.0 * eps / window) * np.arange(n, dtype=float)
    a = assess(make_result(qoi, healthy_residual()), primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.SLOW_DRIFT
    assert a.convergence_index is None
    assert a.unbounded_primary_count == 1
    assert a.binding_constraint == (
        "the remaining error could not be bounded for any primary monitor"
    )
    assert any("drift" in r.message.lower() for r in a.reasons)


def test_a_stalled_residual_outranks_a_settled_qoi():
    """The dangerous case: the QoI looks perfectly converged while the solve is
    stuck. The residual state has to win."""
    stalled = np.concatenate([np.full(50, 10 ** -0.5), np.full(2950, 1e-2)])
    result = make_result(converged_qoi(), stalled,
                         convergence_rows=[("precision", "double")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.STALLED


def test_a_diverging_residual_outranks_everything():
    diverging = 10.0 ** (np.arange(3000, dtype=float) / 200.0)
    a = assess(make_result(converged_qoi(), diverging), primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.DIVERGED


def test_an_unsteady_run_is_refused_not_assessed():
    """Applying steady gates to a URANS record produces a confident wrong
    answer, which is worse than no answer."""
    result = make_result(converged_qoi(), healthy_residual(),
                         models="Implicit Unsteady; Coupled Flow")
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.UNSTEADY_UNSUPPORTED
    assert a.monitors == []
    assert any("unsteady" in r.message.lower() for r in a.reasons)


# --- I5: regime handling has to positively recognise steady ----------------

def test_i5_a_harmonic_balance_run_is_refused_not_silently_assessed_steady():
    """harmonic_balance does not end with 'unsteady', so the old
    is_unsteady-based gate silently ran the steady tests on it. is_steady must
    positively recognise 'steady' and refuse everything else."""
    result = make_result(converged_qoi(), healthy_residual(),
                         models="Harmonic Balance; Segregated Flow")
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.UNSTEADY_UNSUPPORTED
    assert a.monitors == []
    assert any("harmonic balance" in r.message.lower() for r in a.reasons)


def test_i5_an_absent_regime_is_refused_with_a_distinct_message():
    """An absent regime must not default to steady, and the reason text must
    be distinguishable from a confirmed-unsteady run: 'we don't know' is a
    different situation from 'we know and it's unsteady'."""
    result = make_result(converged_qoi(), healthy_residual(), models="")
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.UNSTEADY_UNSUPPORTED
    message = next(r.message for r in a.reasons if r.target == "run")
    assert "could not be determined" in message.lower()
    assert "unsteady run" not in message.lower()


def test_i5_a_steady_run_is_still_assessed_normally():
    result = make_result(converged_qoi(), healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.CONVERGED


def test_an_empty_result_fails_integrity():
    a = assess(SimResult(sim_path="/tmp/empty.sim"), ConvergenceConfig(),
               CLASSIFICATION)
    assert a.state is ConvergenceState.INTEGRITY_FAIL


# --- C1: a malformed final segment must not crash assess() -----------------

def test_c1_a_duplicated_final_iteration_index_does_not_crash_assess():
    """split_segments breaks wherever diff(x) <= 0, so a single duplicated
    index near the end of an otherwise clean series — ordinary in an exported
    CSV — yields a one-point final segment. Before the fix, assess() re-fit
    that segment without re-validating it and ols_fit raised, which propagated
    out of the Qt menu slot with no try and made the window fail to open."""
    n = 3000
    result = make_result(converged_qoi(n), healthy_residual(n),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    result.plots[0].series[0].x[-1] = result.plots[0].series[0].x[-2]
    a = assess(result, primary(), CLASSIFICATION)     # must not raise
    assert a.monitors == []
    assert any("Drag" in msg and "final segment" in msg for msg in a.integrity_errors)


def test_c1_the_residual_loop_is_also_protected():
    n = 3000
    result = make_result(converged_qoi(n), healthy_residual(n))
    result.plots[1].series[0].x[-1] = result.plots[1].series[0].x[-2]
    a = assess(result, primary(), CLASSIFICATION)     # must not raise
    assert a.residuals == []
    assert any("Continuity" in msg for msg in a.integrity_errors)


# --- C2: one bad series must not poison the whole run -----------------------

def test_c2_a_bad_series_is_dropped_with_a_named_warning_and_the_run_continues():
    """A healthy residual and a settled, primary Drag monitor alongside a
    single-sample Probe monitor must not produce a run-level INTEGRITY_FAIL
    that contradicts its own body (a passing Drag reason) and names no
    culprit. The bad series is dropped and named; the run is judged on what
    is left."""
    n = 3000
    result = make_result(converged_qoi(n), healthy_residual(n),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    result.plots.append(MonitorPlot(
        name="Probe Monitor", kind=PlotKind.OTHER,
        series=[PlotSeries(name="Probe", x=[0.0], y=[5.0])],
    ))
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is not ConvergenceState.INTEGRITY_FAIL
    assert a.state is ConvergenceState.CONVERGED
    assert any("Probe" in msg for msg in a.integrity_errors)
    warnings = [r for r in a.reasons
               if r.severity is Severity.WARNING and r.target == "Probe"]
    assert warnings
    assert "fewer than 2 points" in warnings[0].message


def test_c2_integrity_fail_is_reserved_for_when_nothing_usable_remains():
    """The terminal INTEGRITY_FAIL state must only fire when every series
    failed its integrity check, not whenever any one of them did."""
    result = make_result(converged_qoi(3), None,
                         convergence_rows=[("precision", "double")])
    result.plots[0].series[0].x = result.plots[0].series[0].x[:1]
    result.plots[0].series[0].y = result.plots[0].series[0].y[:1]
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.INTEGRITY_FAIL
    assert a.monitors == [] and a.residuals == []
    assert any(r.severity is Severity.ERROR and r.target == "Drag" for r in a.reasons)


# --- F1: dropping every residual must not leave a silent CONVERGED --------

def test_f1_a_dropped_diverging_residual_no_longer_certifies_a_false_converged():
    """Reproduction from the re-review: a hard-diverging continuity residual
    whose iteration column has one duplicated row near the end (C1's own
    'ordinary in an exported CSV' scenario) fails its final-segment integrity
    check and is dropped entirely — every residual equation in a STAR-CCM+
    export shares one iteration column, so this is the likely shape of the
    failure, not a narrow corner case. Before this fix that left zero
    residuals and the QoI gates alone decided the verdict: CONVERGED, High
    confidence, with no trace beyond a WARNING buried in the Reasons tab.
    Residuals are necessary, never sufficient (this module's own stated
    rule), so with no residual evidence surviving at all the strongest
    available verdict is CONVERGING, and confidence must not read High."""
    n = 3000
    diverging = 10.0 ** (np.arange(n, dtype=float) / 200.0)
    result = make_result(converged_qoi(n), diverging,
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    result.plots[1].series[0].x[-1] = result.plots[1].series[0].x[-2]
    a = assess(result, primary(), CLASSIFICATION)

    assert a.residuals == []
    assert any("Continuity" in msg and "final segment" in msg
              for msg in a.integrity_errors)
    assert a.state not in (ConvergenceState.CONVERGED, ConvergenceState.CONVERGED_MACHINE)
    assert a.state is ConvergenceState.CONVERGING
    assert a.confidence is not Confidence.HIGH
    assert AdvisoryFlag.NO_RESIDUAL_EVIDENCE in a.flags
    assert any("no residual" in r.message.lower() for r in a.reasons)


def test_f1_any_integrity_error_caps_confidence_at_medium():
    """A single dropped series among otherwise-clean evidence must not still
    read High: evidence was thrown away, so the record is not complete
    enough to call High regardless of how clean what remains looks."""
    n = 3000
    result = make_result(converged_qoi(n), healthy_residual(n),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    result.plots.append(MonitorPlot(
        name="Probe Monitor", kind=PlotKind.OTHER,
        series=[PlotSeries(name="Probe", x=[0.0], y=[5.0])],
    ))
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.CONVERGED
    assert a.confidence is Confidence.MEDIUM
    assert "dropped" in a.confidence_rule.lower()


def test_a_healthy_but_unsettled_run_is_converging():
    n = 800
    qoi = 100.0 * (1.0 - np.exp(-np.arange(n) / 300.0))
    a = assess(make_result(qoi, healthy_residual(n)), primary(), CLASSIFICATION)
    assert a.state in (ConvergenceState.CONVERGING, ConvergenceState.SLOW_DRIFT)


def test_machine_precision_residuals_with_passing_gates_give_converged_machine():
    floored = np.concatenate([np.full(50, 1.0), np.full(2950, 1e-14)])
    result = make_result(converged_qoi(), floored,
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.CONVERGED_MACHINE


def test_a_converged_machine_run_explains_its_residual():
    """CONVERGED_MACHINE is a good terminal state, but before this test nothing
    asserted that the reasons list actually says so — MACHINE_PRECISION had no
    branch in build_reasons, so the primary explanation surface stayed silent
    about the residual that got the run there."""
    floored = np.concatenate([np.full(50, 1.0), np.full(2950, 1e-14)])
    result = make_result(converged_qoi(), floored,
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.CONVERGED_MACHINE
    assert any("Continuity" in r.message and "precision" in r.message.lower()
               for r in a.reasons)


# --- V10: restarts ---------------------------------------------------------

def test_v10_only_the_final_segment_is_analysed():
    """A restart resets the auto-normalization baseline, so no fit may span the
    boundary. The first segment is drifting hard; the second is settled. The
    verdict must come from the second alone."""
    drifting = 100.0 + np.arange(3000, dtype=float) * 0.5
    settled = converged_qoi(3000)
    qoi = np.concatenate([drifting, settled])
    x = list(map(float, range(3000))) * 2       # the index resets: a restart
    result = SimResult(
        sim_path="/tmp/restart.sim",
        plots=[MonitorPlot(
            name="Drag Monitor Plot", kind=PlotKind.FORCE,
            series=[PlotSeries(name="Drag", x=x, y=qoi.tolist())],
        )],
        properties=SimProperties(groups=[PropertyGroup(
            section="continuum", name="P", entries=[("models", "Steady")])]),
    )
    a = assess(result, primary(), CLASSIFICATION)
    assert a.n_segments == 2
    assert a.monitors[0].n_window == 600        # 0.2 * 3000, not 0.2 * 6000
    assert a.monitors[0].mean == pytest.approx(100.0, rel=1e-3)


# --- confidence ------------------------------------------------------------

def test_missing_metadata_caps_confidence_at_medium_or_low():
    """Data sets extracted before the macro change carry no precision or
    normalization, and must assess at reduced confidence rather than pretending
    to know."""
    a = assess(make_result(converged_qoi(), healthy_residual()), primary(),
               CLASSIFICATION)
    assert a.confidence is Confidence.LOW           # normalization unknown
    assert AdvisoryFlag.PRECISION_UNKNOWN in a.flags
    assert AdvisoryFlag.NORMALIZATION_UNKNOWN in a.flags


def test_no_primary_qoi_gives_low_confidence():
    """A verdict from an inadequate monitor set is worse than no verdict,
    because it manufactures false confidence. The monitor here is deliberately
    not force-like, so the auto-primary rule does not rescue it."""
    result = make_result(converged_qoi(), healthy_residual(),
                         qoi_name="Outlet Pressure",
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, ConvergenceConfig(), CLASSIFICATION)
    assert a.confidence is Confidence.LOW
    assert AdvisoryFlag.INCOMPLETE_EVIDENCE in a.flags
    assert "no primary" in a.confidence_rule.lower()


def test_the_confidence_rule_is_reported():
    a = assess(make_result(converged_qoi(), healthy_residual()), primary(),
               CLASSIFICATION)
    assert a.confidence_rule


def test_incomplete_evidence_alone_does_not_cap_confidence():
    """It is raised unconditionally in phase 1 because the conservation check
    is not implemented; letting it cap confidence would make High unreachable.
    Uses qoi_with_geometric_decay so the iterative estimator is valid and
    ITERATIVE_ERROR_UNBOUNDED does not also fire, isolating this test to
    INCOMPLETE_EVIDENCE alone."""
    result = make_result(qoi_with_geometric_decay(), healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert AdvisoryFlag.INCOMPLETE_EVIDENCE in a.flags
    assert a.confidence is Confidence.HIGH


# --- advisory flags --------------------------------------------------------

def test_oscillatory_suspected_when_the_mean_is_steady_but_the_band_is_wide():
    """The reduced limit-cycle check: no drift, wide band. Full
    CONVERGED_OSCILLATORY detection needs a periodogram and is out of scope,
    but the user must not be told this is simply 'not converged'."""
    n = 3000
    # A whole number of periods per half-window, so the two-halves gate is not
    # tripped by a partial cycle rather than by real drift. The period is kept
    # short for a second reason: OLS on a sinusoid has a commensurability
    # artifact that scales with period, and at T=20 over a 600-sample window it
    # spuriously fails the drift gate (0.126 against a 0.1 tolerance), which
    # would stop OSCILLATORY_SUSPECTED firing at all.
    qoi = 100.0 + 2.0 * np.sin(2.0 * np.pi * np.arange(n, dtype=float) / 6.0)
    result = make_result(qoi, healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert AdvisoryFlag.OSCILLATORY_SUSPECTED in a.flags
    assert any("limit cycle" in r.message.lower() for r in a.reasons)


def test_a_short_window_raises_window_too_short():
    a = assess(make_result(converged_qoi(120)), primary(), CLASSIFICATION)
    assert AdvisoryFlag.WINDOW_TOO_SHORT in a.flags


# --- I2: tau0_over_n_warn was declared and never read ----------------------

def test_i2_a_high_tau0_over_n_raises_autocorrelation_unreliable():
    """The design promises: when tau_0/N > 0.05 the decorrelation estimate's
    own validity assumption fails, so N_eff and the window gate that depends
    on it should be treated as approximate. Before this fix,
    config.tau0_over_n_warn was declared, provenance-tagged and stored on
    every MonitorAssessment, but nothing ever compared them."""
    n = 3000
    rng = np.random.default_rng(3)
    phi = 0.995
    noise = rng.normal(scale=1e-2, size=n)
    ar = np.empty(n)
    ar[0] = noise[0]
    for i in range(1, n):
        ar[i] = phi * ar[i - 1] + noise[i]
    result = make_result(100.0 + ar, healthy_residual(n),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.monitors[0].tau0_over_n > ConvergenceConfig().tau0_over_n_warn
    assert AdvisoryFlag.AUTOCORRELATION_UNRELIABLE in a.flags
    assert any("decorrelation" in r.message.lower() for r in a.reasons)


def test_i2_a_well_behaved_monitor_does_not_raise_autocorrelation_unreliable():
    a = assess(make_result(converged_qoi(), healthy_residual()), primary(),
              CLASSIFICATION)
    assert AdvisoryFlag.AUTOCORRELATION_UNRELIABLE not in a.flags


def test_a_residual_jump_without_an_index_reset_is_advisory_only():
    residual = np.concatenate([
        10.0 ** (-np.arange(1500, dtype=float) / 400.0),
        10.0 ** (-np.arange(1500, dtype=float) / 400.0) * 1e3,
    ])
    a = assess(make_result(converged_qoi(3000), residual), primary(),
              CLASSIFICATION)
    assert AdvisoryFlag.RESTART_SUSPECTED in a.flags
    assert a.n_segments == 1        # advisory: we did not segment


def test_restart_suspected_ignores_a_sustained_shift_on_a_turbulence_equation():
    """R3: only primary-class equations feed RESTART_SUSPECTED. This uses a
    *sustained* level shift (not a single spike -- that is covered by the
    persistence fix in signals.py and would not distinguish this filter) on a
    turbulence-only equation (Sdr), which the class filter must exclude even
    though ``restart_suspected`` on its own would flag it. Turbulence
    residuals are held to weaker standards everywhere else in this codebase;
    this is the same principle applied to the restart check."""
    n = 1500
    continuity = 10.0 ** (-np.arange(n, dtype=float) / 400.0)
    sdr = np.concatenate([np.full(750, 1e-2), np.full(750, 1e-2 * 31.0)])
    plots = [
        MonitorPlot(name="Drag Monitor Plot", kind=PlotKind.FORCE,
                   series=[PlotSeries(name="Drag", x=list(map(float, range(3000))),
                                      y=converged_qoi(3000).tolist())]),
        MonitorPlot(name="Residuals", kind=PlotKind.RESIDUAL, series=[
            PlotSeries(name="Continuity", x=list(map(float, range(n))),
                      y=continuity.tolist()),
            PlotSeries(name="Sdr", x=list(map(float, range(n))), y=sdr.tolist()),
        ]),
    ]
    groups = [PropertyGroup(section="continuum", name="Physics 1",
                            entries=[("models", "Steady; Segregated Flow")])]
    result = SimResult(sim_path="/tmp/case.sim", plots=plots,
                       properties=SimProperties(groups=groups))
    a = assess(result, primary(), CLASSIFICATION)
    assert AdvisoryFlag.RESTART_SUSPECTED not in a.flags


# --- R2: an unbounded primary monitor must not collapse the index to 0 ----

def _bare_metadata() -> RunMetadata:
    absent = MetadataField(None, Provenance.ABSENT)
    return RunMetadata(solver_regime=MetadataField("steady", Provenance.EXTRACTED),
                       solver_type=absent, precision=absent,
                       residual_normalization=absent)


def _mk_denied_monitor(name: str = "Drag", seed: int = 0):
    """A creeping monitor whose iterative escape hatch is denied (C3/F2): the
    change series has no geometric structure to fit, but Mann-Kendall still
    resolves a physically meaningful trend, so the iterative gate's tested
    value is set to +inf. This is the exact mechanism R2 is about: ``_margin``
    turns that +inf into a margin of exactly 0.0."""
    n = 3000
    rng = np.random.default_rng(seed)
    y = 100.0 - 1.09 * 0.9999 ** np.arange(n, dtype=float) + rng.normal(scale=1e-2, size=n)
    return assess_monitor(name, y, ConvergenceConfig(), is_primary=True)


def _settled_monitor(name: str = "Lift", seed: int = 1):
    """An ordinary settled monitor with a finite (large) binding margin, for
    contrast with the unbounded one above."""
    n = 3000
    rng = np.random.default_rng(seed)
    y = 50.0 + rng.normal(scale=1e-2, size=n)
    return assess_monitor(name, y, ConvergenceConfig(), is_primary=True)


def test_r2_an_unbounded_monitor_alone_gives_index_none_not_zero():
    """When the only primary monitor is unbounded, the index must be None (a
    stated absence of measurement), never the 0.0 that a bare limit/inf
    division would silently produce."""
    unbounded = _mk_denied_monitor()
    gate = next(g for g in unbounded.gates if g.name == unbounded.binding_gate)
    assert not math.isfinite(gate.value)          # sanity: this is the R2 case

    _, _, index, binding, unbounded_count = roll_up(
        _bare_metadata(), [], [unbounded], False, ConvergenceConfig(),
    )
    assert index is None
    assert index != 0.0
    assert unbounded_count == 1
    assert "could not be bounded" in binding.lower()
    assert "any primary monitor" in binding.lower()


def test_r2_index_is_the_worst_finite_margin_when_some_monitors_are_bounded():
    """One unbounded primary monitor and one ordinary bounded one: the index
    must be a real measurement (the bounded monitor's margin), and the
    binding constraint must still say a monitor could not be bounded rather
    than silently dropping that information."""
    unbounded = _mk_denied_monitor("Drag")
    bounded = _settled_monitor("Lift")

    _, _, index, binding, unbounded_count = roll_up(
        _bare_metadata(), [], [unbounded, bounded], False, ConvergenceConfig(),
    )
    assert index is not None
    assert index == pytest.approx(bounded.margin)
    assert unbounded_count == 1
    assert "Lift" in binding
    assert "Drag" in binding
    assert "unbounded" in binding.lower() or "could not be bounded" in binding.lower()


def test_r2_no_unbounded_monitors_behaves_exactly_as_before():
    """The ordinary case (no unbounded primary monitor at all) must be
    unaffected: index is the worst margin, binding names only that monitor,
    and the count is 0."""
    bounded_a = _settled_monitor("Lift", seed=1)
    bounded_b = _settled_monitor("Drag", seed=2)
    _, _, index, binding, unbounded_count = roll_up(
        _bare_metadata(), [], [bounded_a, bounded_b], False, ConvergenceConfig(),
    )
    worst = min([bounded_a, bounded_b], key=lambda m: m.margin)
    assert index == pytest.approx(worst.margin)
    assert binding == f"{worst.name}: {worst.binding_gate}"
    assert unbounded_count == 0


def test_r2_end_to_end_assess_reports_the_unbounded_count_and_a_sane_index():
    """Through the full assess() pipeline: a single primary monitor whose
    escape hatch is denied must give convergence_index=None (not 0.0) and
    unbounded_primary_count=1, and the ConvergenceAssessment must carry the
    new field."""
    n = 3000
    rng = np.random.default_rng(0)
    qoi = 100.0 - 1.09 * 0.9999 ** np.arange(n, dtype=float) + rng.normal(scale=1e-2, size=n)
    result = make_result(qoi, healthy_residual(n),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.convergence_index is None
    assert a.unbounded_primary_count == 1
    assert "could not be bounded" in a.binding_constraint.lower()


# --- F5: record_departure + the honest iterative-error backstop, verdict --
# --- level. The gate-level sweep lives in test_convergence_steady.py.     --

def _creeping_qoi(rho: float, n: int = 3000, amplitude: float = 1.09,
                  seed: int = 0, noise: float = 1e-2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 - amplitude * rho ** np.arange(n, dtype=float) + rng.normal(
        scale=noise, size=n)


@pytest.mark.parametrize("rho", [0.999, 0.9999, 0.99996])
def test_f5_creeping_monitors_never_reach_converged(rho):
    """record_departure catches these three rho values at the gate level for
    every one of 20 seeds (see test_convergence_steady.py); confirm the full
    assess() pipeline agrees end to end."""
    for seed in range(10):
        result = make_result(_creeping_qoi(rho, seed=seed), healthy_residual(),
                             convergence_rows=[("precision", "double"),
                                               ("residual_normalization", "auto")])
        a = assess(result, primary(), CLASSIFICATION)
        assert a.state not in (ConvergenceState.CONVERGED,
                               ConvergenceState.CONVERGED_MACHINE), (
            f"rho={rho} seed={seed}"
        )


def test_f5_the_boundary_and_extreme_rho_are_never_reported_fully_certain():
    """rho=0.99999 is a mixed population at the gate level (some seeds denied,
    some pass through the escape hatch) and rho=0.999995 always passes — the
    acknowledged residual gap record_departure cannot close (see
    test_convergence_steady.py). Whenever either reaches CONVERGED at the
    verdict level, it must never read High confidence: ITERATIVE_ERROR_
    UNBOUNDED is raised, confidence is capped at Medium, and a reason names
    the monitor. This is what makes the gap safe rather than silent."""
    for rho in (0.99999, 0.999995):
        for seed in range(10):
            result = make_result(_creeping_qoi(rho, seed=seed), healthy_residual(),
                                 convergence_rows=[("precision", "double"),
                                                   ("residual_normalization", "auto")])
            a = assess(result, primary(), CLASSIFICATION)
            if a.state in (ConvergenceState.CONVERGED, ConvergenceState.CONVERGED_MACHINE):
                assert a.confidence is not Confidence.HIGH, f"rho={rho} seed={seed}"
                assert AdvisoryFlag.ITERATIVE_ERROR_UNBOUNDED in a.flags, (
                    f"rho={rho} seed={seed}"
                )
                assert any(
                    "Drag" in r.message
                    and "iterative error could not be bounded" in r.message.lower()
                    for r in a.reasons
                ), f"rho={rho} seed={seed}"


@pytest.mark.parametrize("scale", [1e-2, 1e-3, 1e-4, 1e-5])
def test_f5_settled_noise_still_reaches_converged_at_several_scales(scale):
    """The false-refusal counterpart, at the verdict level: ordinary settled
    noise must still reach CONVERGED (it may or may not reach High
    confidence — see test_a_purely_noisy_settled_run_is_converged_but_capped_
    at_medium — but it must not be refused)."""
    for seed in range(5):
        rng = np.random.default_rng(seed)
        qoi = 100.0 + rng.normal(scale=scale, size=3000)
        result = make_result(qoi, healthy_residual(),
                             convergence_rows=[("precision", "double"),
                                               ("residual_normalization", "auto")])
        a = assess(result, primary(), CLASSIFICATION)
        assert a.state in (ConvergenceState.CONVERGED,
                          ConvergenceState.CONVERGED_MACHINE), f"scale={scale} seed={seed}"


def test_f5_a_stationary_ar1_and_a_small_real_drift_still_reach_converged():
    """AR(1) at phi=0.99 (stationary, no trend in the generating process at
    all) and a small real drift well inside tolerance must both still reach
    CONVERGED — refusing every noisy settled monitor is the bug this whole
    area exists to avoid."""
    n = 3000
    config = ConvergenceConfig()
    eps = config.tolerance_fraction * 100.0

    rng = np.random.default_rng(2)
    noise = rng.normal(size=n)
    raw = np.empty(n)
    raw[0] = noise[0]
    for i in range(1, n):
        raw[i] = 0.99 * raw[i - 1] + noise[i]
    band_target = 0.02 * eps
    ar1_qoi = 100.0 + raw * (band_target / (raw.std() * 4.0))

    rng2 = np.random.default_rng(0)
    drift_per_iter = 0.01 * eps / 600.0
    drift_qoi = (100.0 + drift_per_iter * np.arange(n, dtype=float)
                + rng2.normal(scale=0.01 * eps, size=n))

    for qoi, label in ((ar1_qoi, "ar1"), (drift_qoi, "drift")):
        result = make_result(qoi, healthy_residual(),
                             convergence_rows=[("precision", "double"),
                                               ("residual_normalization", "auto")])
        a = assess(result, primary(), CLASSIFICATION)
        assert a.state in (ConvergenceState.CONVERGED,
                          ConvergenceState.CONVERGED_MACHINE), label


# --- F6: "no residual monitors exist" is not "residual evidence destroyed" --

def test_f6_a_dataset_with_no_residual_monitors_can_still_reach_converged():
    """A data set whose only plot is a Drag monitor (no Residuals plot at
    all — a deleted plot, a monitor-only portable CSV, a classification
    override) has had nothing destroyed. Before the fix this was
    indistinguishable from every residual failing its integrity check: held
    at CONVERGING, NO_RESIDUAL_EVIDENCE flagged, and a confidence_rule
    claiming residual evidence 'survived preconditioning' with a suggested
    action pointing at per-series warnings that were never raised. After the
    fix this reaches CONVERGED, carries no false NO_RESIDUAL_EVIDENCE flag,
    and a distinct reason says plainly that the verdict rests on QoI
    evidence alone."""
    result = make_result(qoi_with_geometric_decay(), residual=None,
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.residuals == []
    assert a.integrity_errors == []
    assert a.state is ConvergenceState.CONVERGED
    assert AdvisoryFlag.NO_RESIDUAL_EVIDENCE not in a.flags
    assert AdvisoryFlag.INCOMPLETE_EVIDENCE in a.flags
    assert any("no residual monitors at all" in r.message.lower()
              and "qoi evidence alone" in r.message.lower()
              for r in a.reasons)
    assert "survived preconditioning" not in a.confidence_rule.lower()


def test_f6_the_destroyed_case_is_unaffected_by_the_fix():
    """The counterpart: when residual evidence did exist and every one of it
    was then dropped by an integrity check, the original behaviour must be
    unchanged — NO_RESIDUAL_EVIDENCE still fires and the state is still held
    at CONVERGING. (Full reproduction in
    test_f1_a_dropped_diverging_residual_no_longer_certifies_a_false_converged;
    this is the minimal version distinguishing 'destroyed' from 'never
    existed'.)"""
    n = 3000
    result = make_result(qoi_with_geometric_decay(), healthy_residual(n),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    result.plots[1].series[0].x[-1] = result.plots[1].series[0].x[-2]
    a = assess(result, primary(), CLASSIFICATION)
    assert a.residuals == []
    assert a.integrity_errors      # the dropped Continuity series
    assert a.state is ConvergenceState.CONVERGING
    assert AdvisoryFlag.NO_RESIDUAL_EVIDENCE in a.flags


def test_f6_a_dataset_with_no_qoi_monitors_is_not_told_evidence_was_destroyed():
    """The identical conflation on the monitor side: a residual-only data set
    (no QoI monitor plot at all) must not have its confidence_rule claim 'no
    monitor evidence survived preconditioning' — nothing failed an integrity
    check, there simply is no QoI monitor here. The state is still held at
    CONVERGING (a verdict needs a primary QoI to certify CONVERGED — a
    different, correct rule, unaffected by this fix), but the confidence
    text must be honest about why."""
    result = SimResult(
        sim_path="/tmp/residual_only.sim",
        plots=[MonitorPlot(name="Residuals", kind=PlotKind.RESIDUAL,
                           series=[PlotSeries(name="Continuity",
                                              x=list(map(float, range(3000))),
                                              y=healthy_residual().tolist())])],
        properties=SimProperties(groups=[
            PropertyGroup(section="continuum", name="P",
                          entries=[("models", "Steady; Segregated Flow")]),
            PropertyGroup(section="convergence", name="",
                          entries=[("precision", "double"),
                                   ("residual_normalization", "auto")]),
        ]),
    )
    a = assess(result, ConvergenceConfig(), CLASSIFICATION)
    assert a.monitors == []
    assert a.integrity_errors == []
    assert a.state is ConvergenceState.CONVERGING     # no primary QoI to certify
    assert "survived preconditioning" not in a.confidence_rule.lower()


# --- F7: a malformed integrity message must not render a nonsense clause --

def test_f7_series_label_falls_back_to_run_for_a_colonless_message():
    """Every per-series integrity message is '<series>: <detail>', but the
    run-level 'no monitor histories were found in this data set' has no
    colon. Splitting on ':' unconditionally (the old code) would fold that
    whole sentence into a bogus series label wherever it is used to build a
    rule clause. Currently confidence_of's low-evidence checks always
    short-circuit before that string is used for such a run (see
    test_an_empty_result_fails_integrity), so this is not reachable today —
    but the extraction is latent breakage waiting for that circuit to
    change, so it gets its own direct, tested helper."""
    from starpost.core.convergence.verdict import _series_label

    assert _series_label("Drag: fewer than 2 points") == "Drag"
    assert _series_label("no monitor histories were found in this data set") == "run"


# --- reasons ---------------------------------------------------------------

def test_a_failing_run_explains_every_failed_gate():
    n, window = 3000, 600
    eps = ConvergenceConfig().tolerance_fraction * 100.0
    qoi = 100.0 + (4.0 * eps / window) * np.arange(n, dtype=float)
    a = assess(make_result(qoi, healthy_residual()), primary(), CLASSIFICATION)
    errors = [r for r in a.reasons if r.severity is Severity.ERROR]
    assert errors
    assert all(r.suggested_action for r in errors)
    assert any("drift" in r.message.lower() for r in errors)


def test_reasons_are_sorted_most_severe_first():
    n, window = 3000, 600
    eps = ConvergenceConfig().tolerance_fraction * 100.0
    qoi = 100.0 + (4.0 * eps / window) * np.arange(n, dtype=float)
    a = assess(make_result(qoi, healthy_residual()), primary(), CLASSIFICATION)
    order = [Severity.ERROR, Severity.WARNING, Severity.INFO]
    ranks = [order.index(r.severity) for r in a.reasons]
    assert ranks == sorted(ranks)


def test_a_stalled_residual_points_at_the_cell_field_not_more_iterations():
    """A stall is a setup problem — a handful of bad cells holding up an
    RMS-over-cells monitor — so 'run it longer' is the wrong advice."""
    stalled = np.concatenate([np.full(50, 10 ** -0.5), np.full(2950, 1e-2)])
    a = assess(make_result(converged_qoi(), stalled), primary(), CLASSIFICATION)
    action = " ".join(r.suggested_action for r in a.reasons).lower()
    assert "field function" in action
    assert "more iterations" not in action


def test_a_converging_run_estimates_the_extra_iterations_needed():
    n = 900
    qoi = 100.0 * (1.0 - np.exp(-np.arange(n) / 400.0))
    a = assess(make_result(qoi, healthy_residual(n)), primary(), CLASSIFICATION)
    assert any(r.estimated_extra_iterations for r in a.reasons)


def test_a_passing_run_still_reports_what_was_checked():
    """The user must be able to see the monitor set the verdict rests on."""
    result = make_result(converged_qoi(), healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert any(r.severity is Severity.INFO for r in a.reasons)


def test_the_thresholds_used_are_recorded_with_their_provenance():
    a = assess(make_result(converged_qoi()), primary(), CLASSIFICATION)
    assert a.thresholds_used["d_min"] == (3.0, "[S]")


def test_the_package_is_qt_free_and_never_reruns_star_ccm():
    """Two invariants at once: STAR-CCM+ runs once per file and everything
    after is cached, and the analysis core stays importable without a GUI.
    Checked against the sources, not the import graph, because other tests in
    the same process legitimately import PySide6."""
    from pathlib import Path

    import starpost.core.convergence as pkg

    sources = sorted(Path(pkg.__file__).parent.glob("*.py"))
    assert len(sources) >= 9        # every module in the package is covered
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "PySide6" not in text, f"{path.name} imports Qt"
        assert "pyqtgraph" not in text, f"{path.name} imports pyqtgraph"
        assert "starccm_runner" not in text, f"{path.name} reaches for the runner"
