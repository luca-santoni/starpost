"""Layer 1: residual health. Includes validation cases V7, V8 and V15."""
import numpy as np
import pytest

from starpost.core.convergence.config import ConvergenceConfig
from starpost.core.convergence.models import EquationClass, ResidualState
from starpost.core.convergence.residuals import assess_residual


def geometric(rho: float, n: int, r0: float = 1.0, floor: float = 0.0) -> np.ndarray:
    return r0 * rho ** np.arange(n, dtype=float) + floor


def test_v1_decay_factor_recovered_to_within_one_percent():
    """V1: a clean geometric decay at rho = 0.97 with a 1e-12 noise floor. The
    recovered per-iteration decay factor is the basis of every projection."""
    a = assess_residual("Continuity", geometric(0.97, 400, floor=1e-12),
                        ConvergenceConfig(), precision="double")
    assert a.decay_factor == pytest.approx(0.97, rel=0.01)
    assert a.log_slope < 0
    assert a.fit_r2 > 0.99
    assert a.state is ResidualState.CONVERGING


def test_decades_dropped_uses_the_trailing_median_not_the_last_value():
    """A single lucky final sample must not inflate the drop."""
    y = np.concatenate([np.full(50, 1.0), np.full(950, 1e-3)])
    y[-1] = 1e-9
    a = assess_residual("Continuity", y, ConvergenceConfig(), precision="double")
    assert a.decades_dropped == pytest.approx(3.0, abs=0.01)


def test_v8_a_plateau_after_one_and_a_half_decades_is_stalled():
    """V8: STALLED, not CONVERGED. A stall is almost always a setup problem —
    a handful of bad cells holding up an RMS-over-cells monitor — not a
    'run it longer' problem."""
    y = np.concatenate([
        np.full(50, 10 ** -0.5),
        np.linspace(10 ** -0.5, 1e-2, 200),
        np.full(750, 1e-2),
    ])
    a = assess_residual("Continuity", y, ConvergenceConfig(), precision="double")
    assert a.decades_dropped == pytest.approx(1.5, abs=0.05)
    assert a.state is ResidualState.STALLED


def test_a_plateau_below_the_required_drop_is_a_normal_terminal_state():
    """Same flat shape, four decades lower: PLATEAU_LOW, which is healthy."""
    y = np.concatenate([np.full(50, 1.0), np.full(950, 1e-4)])
    a = assess_residual("Continuity", y, ConvergenceConfig(), precision="double")
    assert a.decades_dropped == pytest.approx(4.0, abs=0.01)
    assert a.state is ResidualState.PLATEAU_LOW


def test_turbulence_equations_are_held_to_a_lower_threshold():
    """Tke stalling two orders above continuity is normal and must not read as
    STALLED — turbulence residuals can never alone force a NOT_CONVERGED."""
    y = np.concatenate([np.full(50, 1.0), np.full(950, 10 ** -2.5)])
    config = ConvergenceConfig()
    tke = assess_residual("Tke", y, config, precision="double")
    continuity = assess_residual("Continuity", y, config, precision="double")
    assert tke.equation_class is EquationClass.TURBULENCE
    assert tke.state is ResidualState.PLATEAU_LOW
    assert continuity.state is ResidualState.STALLED


def test_v7_runaway_growth_is_divergence():
    """V7: a residual growing without bound. Caught by the growth-vs-reference
    rung before any slope fit matters."""
    y = 10.0 ** (np.arange(500) / 50.0)
    a = assess_residual("Continuity", y, ConvergenceConfig(), precision="double")
    assert a.state is ResidualState.DIVERGING


def test_v7_divergence_is_caught_within_fifty_iterations_of_onset():
    """The published requirement is detection within 50 iterations. A long
    healthy decay followed by only 50 growing iterations must already trip the
    sustained-slope rung, even though the trailing median is still low."""
    decay = geometric(0.98, 1000)
    onset = decay[-1] * 10.0 ** (np.arange(1, 51) / 10.0)
    a = assess_residual("Continuity", np.concatenate([decay, onset]),
                        ConvergenceConfig(), precision="double")
    assert a.state is ResidualState.DIVERGING


def test_an_oscillating_residual_is_not_diverging_regardless_of_truncation_point():
    """R1: a residual that oscillates about a flat plateau must not read as
    DIVERGING, and the verdict must not depend on which phase of the
    oscillation the record happens to end on. This is the failure mode a real
    STAR-CCM+ run exposed: the last-50-iteration tail fit lands on whatever
    phase the record stops in, so its slope is oscillation phase, not trend
    (r^2 near 0), yet the un-gated slope alone was enough to declare the
    strongest verdict the tool makes."""
    transient = np.linspace(0.0, -2.0, 200)
    i = np.arange(900, dtype=float)
    plateau = -2.0 + 0.25 * np.sin(2.0 * np.pi * i / 40.0)
    y = 10.0 ** np.concatenate([transient, plateau])
    config = ConvergenceConfig()
    for end in range(700, 1100, 37):
        a = assess_residual("Continuity", y[:end], config, precision="double")
        assert a.state is not ResidualState.DIVERGING, end


def test_d1_the_r2_floor_alone_is_insufficient_a_level_shift_is_also_required():
    """D1: the r^2 floor closed most of R1's hole but not all of it. A
    half-cycle of an oscillation is itself well fitted by a straight line, so
    its r^2 lands wherever the phase puts it — this period/amplitude
    combination (60-iteration period, 0.3 decade amplitude) drives the tail
    fit's r^2 above s_div_min_r2 (measured up to ~0.84) with a positive slope
    in some phases, which is exactly the false-DIVERGING mechanism a real
    STAR-CCM+ run exposed (see config.py's s_div_level_ratio comment for the
    measured separation between real oscillations and synthetic
    divergences). Every truncation point across a full period is swept so
    the verdict is proven phase-independent, not just lucky for one offset."""
    period, amplitude = 60.0, 0.3
    transient = np.linspace(0.0, -2.0, 200)
    i = np.arange(900, dtype=float)
    plateau = -2.0 + amplitude * np.sin(2.0 * np.pi * i / period)
    y = 10.0 ** np.concatenate([transient, plateau])
    config = ConvergenceConfig()
    for end in range(700, 700 + int(period) + 1):
        a = assess_residual("Continuity", y[:end], config, precision="double")
        assert a.state is not ResidualState.DIVERGING, end


def test_a_non_finite_value_is_immediate_divergence():
    y = geometric(0.97, 500)
    y[-3] = np.nan
    a = assess_residual("Continuity", y, ConvergenceConfig(), precision="double")
    assert a.state is ResidualState.DIVERGING


def test_v15_single_precision_floor_is_machine_precision_not_stalled():
    """V15: a single-precision build bottoms out near 1e-7 relative. Judged
    against a double-precision floor it would be permanently STALLED."""
    y = np.concatenate([np.full(50, 1.0), np.full(950, 1e-7)])
    a = assess_residual("Continuity", y, ConvergenceConfig(), precision="single")
    assert a.state is ResidualState.MACHINE_PRECISION


def test_v15_unknown_precision_suppresses_the_machine_verdict():
    """With precision unknown the machine rung is skipped entirely, so the
    signal falls through to PLATEAU_LOW rather than being guessed either way."""
    y = np.concatenate([np.full(50, 1.0), np.full(950, 1e-7)])
    a = assess_residual("Continuity", y, ConvergenceConfig(), precision=None)
    assert a.state is ResidualState.PLATEAU_LOW


def test_double_precision_floor_is_far_lower_than_the_single_one():
    """The same 1e-7 floor in a double-precision build is not at the floor."""
    y = np.concatenate([np.full(50, 1.0), np.full(950, 1e-7)])
    assert assess_residual("Continuity", y, ConvergenceConfig(),
                           precision="double").state is ResidualState.PLATEAU_LOW


def test_iterations_to_target_projects_from_the_current_decay_rate():
    """A clean decay that has dropped only ~2.2 of the required 3 decades
    projects a positive, finite iteration count from its current rate."""
    a = assess_residual("Continuity", geometric(0.99, 600), ConvergenceConfig(),
                        precision="double")
    assert a.state is ResidualState.CONVERGING
    assert a.iterations_to_target is not None
    assert a.iterations_to_target > 0


def test_no_projection_offered_for_a_flat_residual():
    """Extrapolating a zero decay rate would divide by ~0; offer nothing."""
    y = np.concatenate([np.full(50, 1.0), np.full(950, 1e-4)])
    a = assess_residual("Continuity", y, ConvergenceConfig(), precision="double")
    assert a.iterations_to_target is None


def test_non_positive_residual_samples_do_not_raise():
    """Log-space fitting must survive a non-positive sample in the analysis window.

    The positive-mask filter in _log_fit is exercised by placing a zero inside
    the trailing window that the fit actually sees (y[800:1000]). The fit must
    produce a finite slope, and classification must not be derailed by the
    zero — with r_ref=1.0 and a trailing median of 1e-4 (four decades dropped),
    the residual should still classify as PLATEAU_LOW."""
    y = np.concatenate([np.full(50, 1.0), np.full(950, 1e-4)])
    y[900] = 0.0
    a = assess_residual("Continuity", y, ConvergenceConfig(), precision="double")
    assert np.isfinite(a.log_slope)
    assert a.state is ResidualState.PLATEAU_LOW


def test_reference_level_uses_the_auto_normalization_sample_count():
    """R_ref is the maximum over the first N0 iterations, matching the solver's
    own auto-normalization reference."""
    y = np.concatenate([[0.1, 5.0, 0.1, 0.1, 0.1], np.full(995, 1e-3)])
    a = assess_residual("Continuity", y, ConvergenceConfig(), precision="double",
                        auto_norm_sample_count=5)
    assert a.r_ref == pytest.approx(5.0)
