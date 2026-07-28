"""Layer 3: steady-state QoI convergence.

For a steady run the target is a fixed point, assessed on three independent
axes — drift, oscillation band, and the precision of the estimate — plus a
check that the estimator had enough independent evidence to speak.

Every "is this small enough" test needs a scale, and a bad scale is the single
biggest source of false verdicts. The ladder never defaults to |mean|
unconditionally: QoIs that legitimately hover near zero (lift at zero
incidence, net moment, side force on a symmetric body, a mass imbalance)
otherwise produce infinite relative errors and spurious failures.

Two departures from the design document, both required for correctness:

1. The design gives the margin as ``eps / max(U_iter, drift, band/2, delta)``
   while also asserting that ``margin >= 1`` means "passed". Those cannot both
   hold, because the gates are tested against different limits — the two-halves
   gate against eps/2, the window gate against a sample count and in the
   opposite direction. Here each gate normalises its own margin so that >= 1
   means passed, and the monitor's margin is their minimum. The invariant then
   holds exactly.

2. A monitor that has stopped moving produces an all-zero change series, so no
   geometric progression can be fitted and the iterative estimator declines.
   Failing the gate on that would make a fully converged monitor permanently
   un-passable, so when the estimator declines *and* the largest single
   iteration change is already inside tolerance, the gate passes on that
   evidence. ASYMPTOTICALLY_STAGNANT is excluded: that flag marks precisely the
   signal whose changes look small while its remaining error is enormous.

   The same escape hatch is also denied when the estimator declines for lack
   of geometric structure (a low fit r^2, not stagnation) but the window's
   Mann-Kendall statistic still finds a statistically resolvable monotonic
   trend *and* the monitor has moved by a meaningful fraction of tolerance
   over the whole record (``mk_trend_departure_fraction``). That combination
   is a monitor slowly creeping toward its asymptote with noise riding on top.

   The effect-size term is ``record_departure``
   (``|mean(trailing window) - mean(first block)|``), not the drift gate's
   own ``projected_drift``. Both are candidates, but ``projected_drift`` is
   ``N_W * |slope|`` estimated *within* the trailing window, so as rho -> 1
   the slope itself vanishes there — it under-reads the remaining tail by a
   factor of roughly N_W*(1-rho), which is a fraction of a percent at rho ->
   1, exactly where the under-reading is worst. Conditioning the denial on
   projected_drift therefore switches the denial off closest to where it is
   most needed. ``record_departure`` is measured across the whole record
   instead, so it does not carry that N_W*(1-rho) deflation, and separates the
   creeping population from a small real drift strictly better (see
   ``mk_trend_departure_fraction`` in config.py and the sweep in
   ``.superpowers/sdd/c3-closure-report.md``).

   That sweep is also honest about what it does not fix: at rho close enough
   to 1 (empirically ~0.999995 and beyond, at these settings), the record has
   not moved far enough yet, in absolute terms, for record_departure to clear
   a benign small-real-drift population either — the information is not in
   the record, not merely mis-measured, so no threshold on this quantity
   alone can separate the two populations. That residual gap is exactly why
   the iterative estimator's decline is *also* surfaced independently, as an
   ``ITERATIVE_ERROR_UNBOUNDED`` advisory flag with confidence capped at
   Medium (see ``verdict.py``): whenever the geometric fit declines, this
   module has no bound on the remaining error, whether or not the denial
   above happens to catch this particular case. Passing every gate is then
   never silently reported as fully certain.

   Mann-Kendall's z is pure statistical significance, not effect size: with
   enough points even a trend a tiny fraction of tolerance becomes
   arbitrarily significant, and its variance assumes independent samples,
   which a correlated monitor history is not — an AR(1) record with no trend
   at all can still return a large |z| on noise alone. The effect-size term
   is what keeps the denial from firing on either of those: a trivially small
   real drift, or a stationary but autocorrelated record. Both z and the
   departure fraction must hold together.

A third point, not a departure but easy to get wrong: the decorrelation factor
is estimated from the *detrended* window. A smooth, well-settled monitor has an
autocorrelation that stays near 1 for hundreds of lags purely because of its
trend, so estimating D_N from the raw window would report a handful of
effective samples for exactly the runs that have converged best, and the window
gate would reject them. Below a floor of fluctuation there is nothing
stochastic to correct for at all, and D_N is taken as 1.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from starpost.core.convergence.iterative import estimate_iterative_error
from starpost.core.convergence.models import (
    GateResult,
    MonitorAssessment,
    ScaleSource,
)
from starpost.core.convergence.signals import window_bounds
from starpost.core.convergence.stats import (
    decorrelation_factor,
    mann_kendall,
    ols_fit,
    student_t_ppf,
    theil_sen_slope,
)

GATE_DRIFT = "drift"
GATE_BAND = "band"
GATE_TWO_HALVES = "two-halves"
GATE_ITERATIVE = "iterative error"
GATE_WINDOW = "window adequacy"

# Detrended scatter below this fraction of the tolerance counts as no
# fluctuation at all, so D_N is taken as 1 rather than estimated from dust.
_NEGLIGIBLE_FRACTION = 0.01

# Significance level for the window gate's relaxed-route confidence interval
# (config.window_relax_ci_fraction). Not a ConvergenceConfig field: it is the
# same 95% convention the band gate's own [97.5, 2.5] percentiles already use
# in this module, reused rather than duplicated as a second named constant.
_CI_ALPHA = 0.05


def _margin(limit: float, value: float) -> float:
    """Smaller-is-better margin. A zero value is a perfect pass, not a NaN."""
    if value <= 0:
        return math.inf
    return limit / value


def reference_scale(y_full: np.ndarray, y_window: np.ndarray, config,
                    manual: Optional[float] = None) -> tuple[float, ScaleSource]:
    """The scale S_j that turns a fractional tolerance into a physical one.

    Rung 1 user-supplied; rung 2 the trailing-window mean, but only when it
    stands clear of the fluctuation; rung 3 the robustified full-record range.
    A degenerate result falls back to 1.0 so the tolerance is never zero."""
    if manual is not None and manual > 0:
        return float(manual), ScaleSource.USER

    mean = float(np.mean(y_window))
    std = float(np.std(y_window))
    if abs(mean) > config.gamma * std and abs(mean) > 0:
        return abs(mean), ScaleSource.MEAN

    high, low = np.percentile(y_full, [95.0, 5.0])
    span = float(high - low)
    if span > 0:
        return span, ScaleSource.RANGE
    return 1.0, ScaleSource.RANGE


def assess_monitor(name: str, y: np.ndarray, config,
                   is_primary: bool = False) -> MonitorAssessment:
    """Run the five steady gates over one QoI monitor's final segment."""
    y = np.asarray(y, dtype=float)
    n = y.size
    start, end, length_ok = window_bounds(n, config)
    window = y[start:end]
    n_window = window.size

    monitor_config = config.monitor(name)
    scale, scale_source = reference_scale(
        y, window, config, manual=monitor_config.reference_scale
    )
    tolerance_fraction = config.tolerance_for(name)
    eps = tolerance_fraction * scale

    index = np.arange(n_window, dtype=float)
    fit = ols_fit(index, window)
    robust_slope = theil_sen_slope(index, window)
    mk = mann_kendall(window)

    # The decorrelation factor describes the *fluctuation*, so it is estimated
    # from the detrended window. Feeding it the raw window would make a smooth
    # settled monitor look maximally autocorrelated — its ACF stays near 1 for
    # hundreds of lags purely because of the trend — and every well-converged
    # run would fail the window gate. The trend itself is already the drift
    # gate's business.
    detrended = window - (fit.intercept + fit.slope * index)
    fluctuation = float(np.std(detrended))
    if fluctuation <= _NEGLIGIBLE_FRACTION * eps:
        # Nothing stochastic at the tolerance scale, so there is no sampling
        # uncertainty to correct for. Estimating D_N from numerical dust would
        # produce an arbitrary number.
        d_n, tau0_over_n = 1.0, 0.0
    else:
        decorrelation = decorrelation_factor(detrended)
        d_n, tau0_over_n = decorrelation.d_n, decorrelation.tau0_over_n
    n_eff = n_window / d_n
    lambda_ok = n_eff >= config.lambda_ind
    window_ok = length_ok and lambda_ok
    window_margin = (n_eff / config.lambda_ind) if length_ok else 0.0

    # The n_eff >= lambda_ind requirement is a proxy for "is the mean known to
    # within tolerance?", and on a very smooth, well-settled monitor it can be
    # unsatisfiable on a technicality — smoothness *is* high autocorrelation —
    # while the quantity the proxy stands in for passes by a wide margin. When
    # the direct route fails but the window still meets its length floor, try
    # the quantity itself: the confidence half-width on the mean, well inside
    # tolerance, *and* the immediately preceding equal-length block agreeing
    # with the window's mean (see config.window_relax_ci_fraction). That second
    # condition is what still refuses a brief flat stretch inside a slow
    # oscillation: such a stretch shows a *different* mean in the block right
    # before it, where a genuinely settled monitor agrees closely.
    window_relaxed = False
    if length_ok and not lambda_ok:
        window_std = float(window.std())
        nu_eff = max(n_eff - 1.0, 1.0)
        sem_eff = window_std / math.sqrt(n_eff) if n_eff > 0 else math.inf
        t_crit = student_t_ppf(1.0 - _CI_ALPHA / 2.0, nu_eff)
        ci_half_width = t_crit * sem_eff
        ci_limit = config.window_relax_ci_fraction * eps
        ci_ok = ci_half_width <= ci_limit
        ci_margin = _margin(ci_limit, ci_half_width)

        if start >= n_window:
            preceding = y[start - n_window:start]
            preceding_mean = float(preceding.mean())
            window_mean = float(window.mean())
            departure = abs(window_mean - preceding_mean)
            preceding_ok = departure <= eps
            preceding_margin = _margin(eps, departure)
            preceding_detail = (
                f"preceding block mean {preceding_mean:.6g} vs. window mean "
                f"{window_mean:.6g} (departure {departure:.4g} against a "
                f"tolerance of {eps:.4g})"
            )
        else:
            # Too little record to supply a preceding block of equal length.
            # Conservative: the relaxation is refused, not assumed to hold.
            preceding_ok = False
            preceding_margin = 0.0
            preceding_detail = "record too short for a preceding equal-length block"

        window_relaxed = ci_ok and preceding_ok
        if window_relaxed:
            window_ok = True
            window_margin = min(ci_margin, preceding_margin)
        window_relax_detail = (
            f"relaxation: CI half-width {ci_half_width:.4g} vs. limit "
            f"{ci_limit:.4g}; {preceding_detail}"
        )

    # --- gate 1: projected drift over another window-length ----------------
    projected_drift = n_window * abs(fit.slope)

    # Record-scale departure: how far the monitor has moved across the whole
    # record, trailing-window mean against the mean of a first block at the
    # start. Used only as the escape-hatch denial's effect-size term (below),
    # not as a gate of its own — unlike projected_drift it is not deflated by
    # N_W*(1-rho) as rho -> 1, since it is not confined to the trailing
    # window (see the module docstring). The first-block length reuses
    # window_min: the same floor the window ladder already treats as "enough
    # samples to say something", and it is what the sweep behind
    # mk_trend_departure_fraction was measured with.
    first_block = y[:min(config.window_min, n)]
    record_departure = abs(float(window.mean()) - float(first_block.mean()))

    # --- gate 2: oscillation band ------------------------------------------
    band_full = float(window.max() - window.min())
    high, low = np.percentile(window, [97.5, 2.5])
    band_p95 = float(high - low)

    # --- gate 3: two-halves consistency ------------------------------------
    half = n_window // 2
    first, second = window[:half], window[half:]
    two_halves_delta = abs(float(second.mean()) - float(first.mean()))
    n_eff_half = max(half / d_n, 1.0)
    pooled = float(first.var()) / n_eff_half + float(second.var()) / n_eff_half
    two_halves_t = (two_halves_delta / math.sqrt(pooled)) if pooled > 0 else 0.0

    # --- gate 4: remaining iterative error ---------------------------------
    iterative = estimate_iterative_error(window, config)
    if iterative.valid:
        iterative_value = float(iterative.u_iter)
        iterative_passed = iterative_value <= eps
        iterative_detail = ""
    elif "ASYMPTOTICALLY_STAGNANT" in iterative.reason:
        iterative_value = math.inf
        iterative_passed = False
        iterative_detail = iterative.reason
    elif (abs(mk.z) > config.mk_trend_z
          and record_departure >= config.mk_trend_departure_fraction * eps):
        # The escape hatch is for a monitor that has genuinely stopped
        # moving. This one has not: the change series has no geometric
        # structure to extrapolate (so the tail estimator declined), the
        # window still shows a trend Mann-Kendall can resolve statistically,
        # and the monitor has moved a meaningful fraction of tolerance across
        # the whole record. Judging it on the largest single-iteration change
        # would under-read the remaining approach by orders of magnitude near
        # rho -> 1 (see the module docstring), so the gate fails outright
        # rather than substituting a number that looks reassuring but is not
        # comparable. The effect-size term is what keeps this from firing on
        # a trivially small real drift or a merely autocorrelated stationary
        # record, either of which can make |z| large on significance alone.
        iterative_value = math.inf
        iterative_passed = False
        iterative_detail = (
            "the remaining error could not be bounded: the change series has "
            "no geometric structure to extrapolate "
            f"({iterative.reason}), but the window still shows a "
            f"statistically resolvable monotonic trend (Mann-Kendall z = "
            f"{mk.z:.3g}, |z| > {config.mk_trend_z}) of a physically "
            f"meaningful size (record-scale departure {record_departure:.4g} "
            f">= {config.mk_trend_departure_fraction:.2f} x tolerance "
            f"{eps:.4g}); the static-monitor escape hatch is refused"
        )
    else:
        largest_change = float(np.max(np.abs(np.diff(window)))) if n_window > 1 else 0.0
        iterative_value = largest_change
        iterative_passed = largest_change <= eps
        iterative_detail = (
            "no geometric progression could be fitted; judged on the largest "
            f"single-iteration change instead ({iterative.reason})"
        )

    window_detail = f"{n_window} samples, D_N = {d_n:.3g}, {n_eff:.1f} effective"
    if window_relaxed:
        window_detail += (
            f"; passed via the mean-precision relaxation, not the "
            f"{config.lambda_ind:.0f}-independent-sample requirement "
            f"({window_relax_detail})"
        )
    elif not lambda_ok and length_ok:
        window_detail += f" (relaxation not met: {window_relax_detail})"

    gates = [
        GateResult(
            name=GATE_DRIFT, passed=projected_drift <= eps,
            value=projected_drift, limit=eps,
            margin=_margin(eps, projected_drift),
            detail="change expected from continuing for another window-length",
        ),
        GateResult(
            name=GATE_BAND, passed=band_p95 <= eps,
            value=band_p95, limit=eps, margin=_margin(eps, band_p95),
            detail=f"central 95% interquantile range (full range {band_full:.6g})",
        ),
        GateResult(
            name=GATE_TWO_HALVES, passed=two_halves_delta <= eps / 2.0,
            value=two_halves_delta, limit=eps / 2.0,
            margin=_margin(eps / 2.0, two_halves_delta),
            detail=f"difference of half-window means (t = {two_halves_t:.3g})",
        ),
        GateResult(
            name=GATE_ITERATIVE, passed=iterative_passed,
            value=iterative_value, limit=eps, margin=_margin(eps, iterative_value),
            detail=iterative_detail,
        ),
        GateResult(
            name=GATE_WINDOW, passed=window_ok,
            value=n_eff, limit=float(config.lambda_ind),
            margin=window_margin,
            detail=window_detail,
        ),
    ]

    # A gate whose tested value is infinite (currently only the iterative
    # gate, when the static-monitor escape hatch above is denied) reduces to
    # a margin of exactly 0.0 through _margin's limit/value reciprocal — not
    # a genuine near-zero measurement, but an "unmeasurable" placeholder.
    # Left in the running min, that placeholder erases four otherwise-good
    # finite margins and reports the whole monitor as a false 0.0. Binding is
    # chosen from the finite-valued gates whenever at least one exists; the
    # unbounded gate's own passed=False still fails the monitor regardless
    # (MonitorAssessment.passed checks every gate), so this changes only the
    # magnitude reported, never the verdict.
    finite_gates = [g for g in gates if math.isfinite(g.value)]
    binding = min(finite_gates or gates, key=lambda g: g.margin)
    margin = binding.margin if finite_gates else None

    return MonitorAssessment(
        name=name,
        is_primary=is_primary,
        reference_scale=scale,
        scale_source=scale_source,
        tolerance_fraction=tolerance_fraction,
        tolerance_abs=eps,
        window_start=start,
        window_end=end,
        n_window=n_window,
        mean=float(window.mean()),
        std=float(window.std()),
        band_full=band_full,
        band_p95=band_p95,
        ols_slope=fit.slope,
        theil_sen_slope=robust_slope,
        projected_drift=projected_drift,
        record_departure=record_departure,
        mann_kendall_z=mk.z,
        mann_kendall_p=mk.p,
        two_halves_delta=two_halves_delta,
        two_halves_t=two_halves_t,
        d_n=d_n,
        n_eff=n_eff,
        tau0_over_n=tau0_over_n,
        iterative=iterative,
        gates=gates,
        margin=margin,
        binding_gate=binding.name,
    )
