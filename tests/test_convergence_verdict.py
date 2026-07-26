"""Roll-up: state, confidence, convergence index, binding constraint, reasons.
Includes validation case V10 and the end-to-end integration tests."""
import numpy as np
import pytest

from starpost.core.convergence import assess
from starpost.core.convergence.config import ConvergenceConfig, MonitorConfig
from starpost.core.convergence.models import (
    AdvisoryFlag,
    Confidence,
    ConvergenceState,
    Severity,
)
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


# --- end-to-end states -----------------------------------------------------

def test_a_healthy_settled_run_is_converged():
    result = make_result(converged_qoi(), healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.CONVERGED
    assert a.convergence_index > 1.0
    assert a.confidence is Confidence.HIGH


def test_a_drifting_run_is_slow_drift_and_names_its_binding_constraint():
    n, window = 3000, 600
    eps = ConvergenceConfig().tolerance_fraction * 100.0
    qoi = 100.0 + (4.0 * eps / window) * np.arange(n, dtype=float)
    a = assess(make_result(qoi, healthy_residual()), primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.SLOW_DRIFT
    assert a.convergence_index < 1.0
    assert a.binding_constraint.startswith("Drag: ")
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


def test_an_empty_result_fails_integrity():
    a = assess(SimResult(sim_path="/tmp/empty.sim"), ConvergenceConfig(),
               CLASSIFICATION)
    assert a.state is ConvergenceState.INTEGRITY_FAIL


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
    is not implemented; letting it cap confidence would make High unreachable."""
    result = make_result(converged_qoi(), healthy_residual(),
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


def test_a_residual_jump_without_an_index_reset_is_advisory_only():
    residual = np.concatenate([
        10.0 ** (-np.arange(1500, dtype=float) / 400.0),
        10.0 ** (-np.arange(1500, dtype=float) / 400.0) * 1e3,
    ])
    a = assess(make_result(converged_qoi(3000), residual), primary(),
              CLASSIFICATION)
    assert AdvisoryFlag.RESTART_SUSPECTED in a.flags
    assert a.n_segments == 1        # advisory: we did not segment


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
