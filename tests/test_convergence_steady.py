"""Layer 3: steady QoI gates. Includes validation cases V2, V5 and V9."""
import numpy as np
import pytest

from starpost.core.convergence.config import ConvergenceConfig, MonitorConfig
from starpost.core.convergence.models import ScaleSource
from starpost.core.convergence.steady import (
    GATE_BAND,
    GATE_DRIFT,
    GATE_ITERATIVE,
    GATE_TWO_HALVES,
    GATE_WINDOW,
    assess_monitor,
    reference_scale,
)


def gate(assessment, name):
    return next(g for g in assessment.gates if g.name == name)


def ar1(n: int, phi: float = 0.5, scale: float = 1.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.normal(scale=scale, size=n)
    y = np.empty(n)
    y[0] = noise[0]
    for i in range(1, n):
        y[i] = phi * y[i - 1] + noise[i]
    return y


# --- reference scale ladder ------------------------------------------------

def test_a_user_supplied_scale_wins():
    y = np.full(1000, 5.0)
    scale, source = reference_scale(y, y, ConvergenceConfig(), manual=2.5)
    assert (scale, source) == (2.5, ScaleSource.USER)


def test_a_well_separated_mean_is_used_as_the_scale():
    """Rung 2 applies only when the mean stands clear of the fluctuation."""
    y = 100.0 + ar1(1000, scale=0.01)
    scale, source = reference_scale(y, y[-200:], ConvergenceConfig())
    assert source is ScaleSource.MEAN
    assert scale == pytest.approx(100.0, rel=0.01)


def test_v9_a_near_zero_mean_falls_back_to_the_record_range():
    """V9. A QoI that legitimately hovers near zero — lift at zero incidence,
    net moment, side force on a symmetric body — would otherwise produce an
    infinite relative error and a spurious NOT_CONVERGED. This is the most
    common practical failure of automated convergence checks."""
    y = ar1(2000, scale=1.0)     # mean ~ 0, std ~ 1
    scale, source = reference_scale(y, y[-400:], ConvergenceConfig())
    assert source is ScaleSource.RANGE
    assert scale > 0


def test_a_degenerate_scale_never_reaches_zero():
    """A constant-zero monitor has no mean and no range. The scale falls back
    to 1.0 rather than producing a zero tolerance and a division by zero."""
    y = np.zeros(1000)
    scale, _ = reference_scale(y, y, ConvergenceConfig())
    assert scale == 1.0


def test_v9_a_zero_mean_monitor_assesses_without_raising():
    a = assess_monitor("Side Force", ar1(2000, scale=1.0), ConvergenceConfig())
    assert np.isfinite(a.tolerance_abs)
    assert a.tolerance_abs > 0
    assert np.isfinite(a.margin)


# --- the five gates --------------------------------------------------------

def test_v2_an_exponential_approach_passes_every_gate():
    """V2: phi_inf * (1 - exp(-n/lambda)) plus small noise. Fully settled by
    the end of a long record, so all five gates pass and the margin clears 1."""
    n = 3000
    rng = np.random.default_rng(1)
    y = 2.0 * (1.0 - np.exp(-np.arange(n) / 200.0)) + rng.normal(scale=1e-9, size=n)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert a.passed is True
    assert a.margin > 1.0
    for name in (GATE_DRIFT, GATE_BAND, GATE_TWO_HALVES, GATE_ITERATIVE, GATE_WINDOW):
        assert gate(a, name).passed is True, name


def test_v2_the_same_signal_truncated_mid_transient_fails_on_drift():
    """Cut the record while the exponential is still moving and the projected
    drift over another window-length exceeds tolerance."""
    n = 400
    y = 2.0 * (1.0 - np.exp(-np.arange(n) / 200.0))
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert gate(a, GATE_DRIFT).passed is False


def test_v5_a_slow_linear_drift_fails_the_drift_gate():
    """V5: stationary noise plus a drift sized to exactly twice the tolerance
    over the trailing window. A single-statistic detector would call this
    converged; the projected-drift gate is what catches it."""
    n, window = 3000, 600
    mean, tol = 100.0, ConvergenceConfig().tolerance_fraction
    eps = tol * mean
    beta = 2.0 * eps / window
    y = mean + beta * np.arange(n, dtype=float) + ar1(n, scale=1e-3, seed=5)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert a.n_window == window
    assert gate(a, GATE_DRIFT).passed is False
    assert gate(a, GATE_DRIFT).value == pytest.approx(2.0 * eps, rel=0.05)
    assert a.margin < 1.0


def test_the_band_gate_uses_the_robust_range_so_one_spike_cannot_veto():
    """The full max-minus-min is reported, but the central 95% interquantile
    range is what gates — a single spike must not veto convergence."""
    y = np.full(3000, 50.0) + ar1(3000, scale=1e-4, seed=2)
    y[2500] += 10.0
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert a.band_full > 5.0
    assert gate(a, GATE_BAND).passed is True


def test_the_two_halves_gate_catches_a_step_the_band_would_tolerate():
    """A clean step between the halves of the window: the band alone is
    ambiguous, the halves comparison is not."""
    n = 3000
    y = np.concatenate([np.full(n - 300, 100.0), np.full(300, 100.5)])
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert gate(a, GATE_TWO_HALVES).passed is False
    assert a.two_halves_delta == pytest.approx(0.5, rel=0.01)


def test_a_static_monitor_passes_the_iterative_gate_without_an_estimate():
    """A monitor that has stopped moving has an all-zero change series, so no
    geometric progression can be fitted. It must still be able to pass, on the
    evidence that its largest change is already inside tolerance."""
    y = np.full(3000, 42.0)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert a.iterative.valid is False
    assert gate(a, GATE_ITERATIVE).passed is True
    assert a.passed is True


def test_a_stagnant_monitor_fails_the_iterative_gate_despite_tiny_changes():
    """rho > 0.999: the per-iteration changes are small but the remaining error
    is enormous. This must not slip through the static-monitor escape hatch."""
    n = 3000
    y = 100.0 - 5.0 * 0.9999 ** np.arange(n, dtype=float)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert "ASYMPTOTICALLY_STAGNANT" in a.iterative.reason
    assert gate(a, GATE_ITERATIVE).passed is False


def test_a_short_record_fails_the_window_gate():
    """Gate 5. Any rule satisfiable by a handful of accidentally-similar
    consecutive samples fires spuriously, so the window must be long enough."""
    a = assess_monitor("Drag", np.full(120, 10.0), ConvergenceConfig())
    assert gate(a, GATE_WINDOW).passed is False
    assert a.passed is False


def test_a_strongly_autocorrelated_record_fails_the_window_gate():
    """N_W >= 20 * D_N. Highly correlated samples are not independent
    evidence, however many of them there are."""
    y = 100.0 + ar1(3000, phi=0.995, scale=1e-2, seed=9)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert a.d_n > 20.0
    assert gate(a, GATE_WINDOW).passed is False


def test_a_smooth_settled_monitor_is_not_punished_for_its_own_trend():
    """The decorrelation factor is estimated from the detrended window. On the
    raw window a smooth signal's autocorrelation stays near 1 for hundreds of
    lags purely because of the trend, D_N explodes, and the best-converged runs
    would be the ones rejected for having too few effective samples."""
    n = 3000
    rng = np.random.default_rng(11)
    y = 2.0 * (1.0 - np.exp(-np.arange(n) / 200.0)) + rng.normal(scale=1e-9, size=n)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert a.d_n == pytest.approx(1.0)
    assert a.n_eff == pytest.approx(600.0)
    assert gate(a, GATE_WINDOW).passed is True


def test_a_genuinely_noisy_monitor_still_gets_a_real_decorrelation_factor():
    """The negligible-fluctuation shortcut must not swallow real correlation."""
    y = 100.0 + ar1(3000, phi=0.8, scale=1e-2, seed=12)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert a.d_n == pytest.approx(9.0, rel=0.35)     # (1+phi)/(1-phi)


# --- margin, binding gate, evidence ---------------------------------------

def test_the_margin_is_at_least_one_exactly_when_every_gate_passes():
    """The invariant the convergence index depends on."""
    good = assess_monitor("Drag", np.full(3000, 42.0), ConvergenceConfig())
    bad = assess_monitor("Drag", np.full(120, 42.0), ConvergenceConfig())
    assert good.passed and good.margin >= 1.0
    assert not bad.passed and bad.margin < 1.0


def test_the_binding_gate_names_the_gate_with_the_smallest_margin():
    """The convergence index is the worst gate's margin, and binding_gate must
    name that gate.

    Asserting a *specific* gate name here would be brittle: a wide-band signal
    fails the band and iterative gates together and their margins are not
    reliably ordered, and for a pure linear ramp the drift and two-halves
    margins are algebraically identical, so which binds is a tie. The period is
    kept short because OLS on a sinusoid has a commensurability artifact that
    scales with period — at T=20 over a 600-sample window it produces a
    spurious projected drift of 0.126 against a 0.1 tolerance."""
    n = 3000
    y = 100.0 + 2.0 * np.sin(2.0 * np.pi * np.arange(n, dtype=float) / 6.0)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    worst = min(a.gates, key=lambda g: g.margin)
    assert a.binding_gate == worst.name
    assert a.margin == worst.margin
    assert a.margin < 1.0
    assert gate(a, GATE_DRIFT).passed is True


def test_both_slopes_and_the_mann_kendall_statistic_are_reported():
    """The parametric and robust slopes are reported side by side; their
    disagreement is itself a useful signal, surfaced later as
    TREND_ESTIMATE_UNSTABLE."""
    n = 3000
    y = 100.0 + 1e-4 * np.arange(n, dtype=float)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert a.ols_slope == pytest.approx(1e-4, rel=0.05)
    assert a.theil_sen_slope == pytest.approx(1e-4, rel=0.05)
    assert a.mann_kendall_z > 4.0


def test_gate_values_are_in_physical_units_not_fractions():
    """Every gate carries an absolute effect size, so statistical significance
    is never mistaken for engineering significance."""
    y = np.full(3000, 100.0) + ar1(3000, scale=1e-4, seed=4)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert a.tolerance_fraction == 1e-3
    assert a.tolerance_abs == pytest.approx(0.1, rel=0.05)   # 0.1% of 100
    assert gate(a, GATE_BAND).limit == pytest.approx(a.tolerance_abs)


def test_a_per_monitor_tolerance_override_is_honoured():
    config = ConvergenceConfig(
        monitors={"Drag": MonitorConfig(is_primary=True, tolerance_fraction=1e-6)}
    )
    y = np.full(3000, 100.0) + ar1(3000, scale=1e-3, seed=6)
    a = assess_monitor("Drag", y, config, is_primary=True)
    assert a.tolerance_fraction == 1e-6
    assert gate(a, GATE_BAND).passed is False
