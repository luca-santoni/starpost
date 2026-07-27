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


@pytest.mark.parametrize("rho, noise", [(0.999, 1e-3), (0.9999, 1e-3), (0.9999, 1e-2)])
def test_noisy_stagnation_is_still_refused_by_the_drift_gate(rho, noise):
    """A genuinely stagnant monitor buried in noise has no geometric structure
    left in its change series, so the iterative gate stops firing (that is the
    min_fit_r2 guard doing its job, not a bug). It must still be refused, and
    the gate that refuses it is drift: a stagnant monitor is still moving, and
    drift measures that movement directly instead of inferring it from a fit.

    This is the safety property that keeps the min_fit_r2 guard from trading a
    false NOT_CONVERGED for a false CONVERGED."""
    n = 3000
    rng = np.random.default_rng(1)
    y = 100.0 - 5.0 * rho ** np.arange(n, dtype=float) + rng.normal(scale=noise, size=n)
    a = assess_monitor("Drag", y, ConvergenceConfig(), is_primary=True)
    assert a.iterative.fit_r2 < ConvergenceConfig().min_fit_r2
    assert gate(a, GATE_DRIFT).passed is False
    assert a.passed is False


# --- C3: the static-monitor escape hatch must not certify a creeping trend --

def test_c3_a_monitor_eight_x_from_its_asymptote_no_longer_passes_every_gate():
    """The reproduction from the review: rho = 0.9999, noise 1e-2. Before the
    fix this passed drift, band, two-halves and the iterative escape hatch
    (judged on its largest single-iteration change) with margin ~1.5, while
    the true remaining approach was ~8x the tolerance. Drift alone does not
    catch it: at rho -> 1 it under-reads the remaining tail by a factor of
    roughly N_W*(1-rho)."""
    n = 3000
    rng = np.random.default_rng(0)
    y = 100.0 - 1.09 * 0.9999 ** np.arange(n, dtype=float) + rng.normal(scale=1e-2, size=n)
    config = ConvergenceConfig()
    a = assess_monitor("Drag", y, config, is_primary=True)

    true_remaining = 1.09 * 0.9999 ** (n - 1) / (1.0 - 0.9999)
    assert true_remaining > 8.0 * a.tolerance_abs        # the false-pass condition

    assert a.iterative.valid is False                    # r^2 too low to trust rho
    assert abs(a.mann_kendall_z) > config.mk_trend_z      # but MK resolves the trend
    assert gate(a, GATE_ITERATIVE).passed is False
    assert a.passed is False


@pytest.mark.parametrize("rho, noise", [(0.999, 1e-3), (0.999, 1e-2),
                                        (0.9999, 1e-3), (0.9999, 1e-2)])
def test_c3_creeping_monitors_are_refused_across_seeds(rho, noise):
    """The sweep the review asked for: every seed in this regime must fail,
    specifically because the escape hatch is now denied on the iterative
    gate, not only because of whatever the drift gate happens to catch."""
    n = 3000
    config = ConvergenceConfig()
    for seed in range(20):
        rng = np.random.default_rng(seed)
        y = (100.0 - 1.09 * rho ** np.arange(n, dtype=float)
             + rng.normal(scale=noise, size=n))
        a = assess_monitor("Drag", y, config, is_primary=True)
        assert a.passed is False, f"rho={rho} noise={noise} seed={seed}"
        assert gate(a, GATE_ITERATIVE).passed is False, f"seed {seed}"


@pytest.mark.parametrize("scale", [1e-2, 1e-3, 1e-4, 1e-5])
def test_c3_settled_monitors_still_pass_across_seeds(scale):
    """The counterpart to the sweep above: mk_trend_z must not be so sensitive
    that ordinary settled noise starts tripping the same denial."""
    n = 3000
    config = ConvergenceConfig()
    for seed in range(20):
        rng = np.random.default_rng(seed)
        y = 100.0 + rng.normal(scale=scale, size=n)
        a = assess_monitor("Drag", y, config, is_primary=True)
        assert abs(a.mann_kendall_z) <= config.mk_trend_z, f"scale={scale} seed={seed}"
        assert a.passed is True, f"scale={scale} seed={seed}"


# --- F2: the mk_trend_z denial needs an effect-size term, not z alone ------
#
# White noise (the population above) structurally cannot trip Mann-Kendall,
# so it never probes the false-refusal side of the mk_trend_z threshold. The
# cases below reproduce the two false-refusal populations the re-review
# measured: a trivially small *real* drift (z becomes significant with
# enough points even though the drift is a tiny fraction of tolerance), and a
# stationary but autocorrelated AR(1) record with no trend in the generating
# process at all (Mann-Kendall's variance assumes independent samples, which
# this is not). Both must still pass once the escape-hatch denial also
# requires the projected drift to be a meaningful fraction of tolerance.

def test_f2_a_trivially_small_real_drift_is_not_refused():
    """Drifting at 1% of the tolerance the user set. z alone is significant
    (a pure significance test has no notion of 'too small to matter'), but
    the record-scale departure is a small fraction of tolerance (measured at
    ~0.04 x eps), so the denial's effect-size term must let the escape hatch
    through."""
    n = 3000
    config = ConvergenceConfig()
    eps = config.tolerance_fraction * 100.0
    rng = np.random.default_rng(0)
    drift_per_iter = 0.01 * eps / 600.0     # projected drift ~= 1% of eps
    y = (100.0 + drift_per_iter * np.arange(n, dtype=float)
        + rng.normal(scale=0.01 * eps, size=n))
    a = assess_monitor("Drag", y, config, is_primary=True)
    assert a.iterative.valid is False
    assert abs(a.mann_kendall_z) > config.mk_trend_z            # "significant"...
    assert a.record_departure < config.mk_trend_departure_fraction * a.tolerance_abs  # ...but tiny
    assert gate(a, GATE_ITERATIVE).passed is True
    assert a.passed is True


@pytest.mark.parametrize("phi, seed", [(0.99, 2), (0.99, 3)])
def test_f2_a_stationary_ar1_record_is_not_refused_on_correlated_noise(phi, seed):
    """These two (phi, seed) pairs are exactly the ones the re-review
    measured flipping to |z| > mk_trend_z on autocorrelation alone, with
    drift, band and the window gate all passing — there is no trend in the
    generating process, only correlated noise Mann-Kendall's variance formula
    does not expect. The effect-size term (near-zero record-scale departure,
    since a stationary AR(1) does not move the record mean) must still let
    the escape hatch through."""
    n = 30000
    config = ConvergenceConfig()
    rng = np.random.default_rng(seed)
    noise = rng.normal(size=n)
    raw = np.empty(n)
    raw[0] = noise[0]
    for i in range(1, n):
        raw[i] = phi * raw[i - 1] + noise[i]
    eps = config.tolerance_fraction * 100.0
    band_target = 0.02 * eps               # band held to 2% of tolerance
    y = 100.0 + raw * (band_target / (raw.std() * 4.0))
    a = assess_monitor("Drag", y, config, is_primary=True)
    assert abs(a.mann_kendall_z) > config.mk_trend_z
    assert a.record_departure < config.mk_trend_departure_fraction * a.tolerance_abs
    assert gate(a, GATE_ITERATIVE).passed is True
    assert a.passed is True


@pytest.mark.parametrize("rho, noise", [(0.999, 1e-3), (0.999, 1e-2),
                                        (0.9999, 1e-3), (0.9999, 1e-2)])
def test_f2_the_creeping_population_still_denied_with_the_effect_size_term(rho, noise):
    """The counterpart sweep: adding the effect-size term must not reopen the
    hole C3 closed. Every creeping seed's record-scale departure sits at
    roughly 2.5-9.2x tolerance (rho=0.9999 and rho=0.999 respectively),
    comfortably above mk_trend_departure_fraction (0.25 by default), so the
    denial must still fire for all of them."""
    n = 3000
    config = ConvergenceConfig()
    for seed in range(20):
        rng = np.random.default_rng(seed)
        y = (100.0 - 1.09 * rho ** np.arange(n, dtype=float)
             + rng.normal(scale=noise, size=n))
        a = assess_monitor("Drag", y, config, is_primary=True)
        assert a.record_departure >= config.mk_trend_departure_fraction * a.tolerance_abs, (
            f"rho={rho} noise={noise} seed={seed}"
        )
        assert gate(a, GATE_ITERATIVE).passed is False, f"rho={rho} noise={noise} seed={seed}"
        assert a.passed is False, f"rho={rho} noise={noise} seed={seed}"


# --- F5: record_departure replaces projected_drift as the denial's effect- --
# --- size term, closing a hole projected_drift's own N_W*(1-rho) deflation --
# --- reopened right where the under-reading is worst.                     --
#
# All four cases below use the reproduction from the review: n=3000,
# A=1.09, mean 100, screening tolerance, noise=1e-2 — the same population
# that, judged on projected_drift alone, passed every gate at rho=0.99996
# and rho=0.99999 with the true remaining error 10-11x tolerance.

def test_f5_record_departure_catches_creeping_monitors_projected_drift_missed():
    """rho in {0.999, 0.9999, 0.99996}: record_departure sits at roughly
    1.0-9.2x tolerance for every one of 20 seeds, comfortably above
    mk_trend_departure_fraction (0.25x), so every seed must fail. rho=0.99996
    in particular is the case the old projected_drift-gated denial let
    through (departure/eps = 0.242 in the review's measurement, under the old
    threshold) — record_departure catches it (~1.0-1.1x eps here)."""
    n = 3000
    config = ConvergenceConfig()
    for rho in (0.999, 0.9999, 0.99996):
        for seed in range(20):
            rng = np.random.default_rng(seed)
            y = (100.0 - 1.09 * rho ** np.arange(n, dtype=float)
                 + rng.normal(scale=1e-2, size=n))
            a = assess_monitor("Drag", y, config, is_primary=True)
            assert a.record_departure >= config.mk_trend_departure_fraction * a.tolerance_abs, (
                f"rho={rho} seed={seed}"
            )
            assert a.passed is False, f"rho={rho} seed={seed}"


def test_f5_the_boundary_rho_is_a_mixed_population_by_design():
    """rho=0.99999 sits right at the edge record_departure can resolve
    (measured departure/eps in roughly 0.27-0.30 against a 0.25 threshold):
    some seeds clear the threshold and are correctly denied, others fall
    just under it and pass through the escape hatch. Neither outcome is a
    bug — this is the transition zone between what Part 1 can and cannot
    catch. Every seed that does pass must still show iterative.valid is
    False (no geometric fit was trusted), which is exactly what
    ITERATIVE_ERROR_UNBOUNDED and the Medium confidence cap are for (see
    the verdict-level test in test_convergence_verdict.py)."""
    n = 3000
    rho, A = 0.99999, 1.09
    config = ConvergenceConfig()
    outcomes = []
    for seed in range(20):
        rng = np.random.default_rng(seed)
        y = 100.0 - A * rho ** np.arange(n, dtype=float) + rng.normal(scale=1e-2, size=n)
        a = assess_monitor("Drag", y, config, is_primary=True)
        outcomes.append(a.passed)
        if a.passed:
            assert a.iterative.valid is False, seed
    assert any(outcomes), "expected at least one seed to pass at the boundary"
    assert not all(outcomes), "expected at least one seed to still be denied"


def test_f5_the_denial_does_not_fully_close_the_hole_at_extreme_rho():
    """The acknowledged residual gap. At rho=0.999995 the monitor is
    analytically ~2e6x tolerance from its asymptote (A*rho^(n-1)/(1-rho),
    not a fitted estimate — the geometric fit itself declines on this noisy
    data), yet record_departure (~0.13-0.16x eps) falls *below* a benign
    small-real-drift population (~0.22x eps measured in
    test_f2_a_trivially_small_real_drift_is_not_refused) — the record simply
    has not moved far enough yet in absolute terms for record_departure to
    tell the two populations apart, for any threshold. Every seed here passes
    every gate. This is exactly the case Part 2 exists for: verified at the
    verdict level that such a run is never reported as fully certain."""
    n = 3000
    rho, A = 0.999995, 1.09
    config = ConvergenceConfig()
    true_remaining = A * rho ** (n - 1) / (1.0 - rho)
    for seed in range(20):
        rng = np.random.default_rng(seed)
        y = 100.0 - A * rho ** np.arange(n, dtype=float) + rng.normal(scale=1e-2, size=n)
        a = assess_monitor("Drag", y, config, is_primary=True)
        assert true_remaining > 1e6 * a.tolerance_abs
        assert a.passed is True, f"seed={seed}"
        assert a.iterative.valid is False, f"seed={seed}"


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
