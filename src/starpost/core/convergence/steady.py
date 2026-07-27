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
   trend. That combination is a monitor slowly creeping toward its asymptote
   with noise riding on top: the drift gate under-reads the remaining tail by
   a factor of roughly N_W*(1-rho), which is a fraction of a percent at
   rho -> 1, so a monitor 8x from its asymptote can otherwise pass every gate
   with margin to spare. Mann-Kendall is not fooled by the same noise that
   defeats the geometric fit, because it tests rank order rather than
   magnitude.

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
    window_ok = length_ok and n_eff >= config.lambda_ind

    # --- gate 1: projected drift over another window-length ----------------
    projected_drift = n_window * abs(fit.slope)

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
    elif abs(mk.z) > config.mk_trend_z:
        # The escape hatch is for a monitor that has genuinely stopped
        # moving. This one has not: the change series has no geometric
        # structure to extrapolate (so the tail estimator declined), but the
        # window still shows a trend Mann-Kendall can resolve statistically.
        # Judging it on the largest single-iteration change would under-read
        # the remaining approach by orders of magnitude near rho -> 1 (see the
        # module docstring), so the gate fails outright rather than
        # substituting a number that looks reassuring but is not comparable.
        iterative_value = math.inf
        iterative_passed = False
        iterative_detail = (
            "the remaining error could not be bounded: the change series has "
            "no geometric structure to extrapolate "
            f"({iterative.reason}), but the window still shows a "
            f"statistically resolvable monotonic trend (Mann-Kendall z = "
            f"{mk.z:.3g}, |z| > {config.mk_trend_z}); the static-monitor "
            "escape hatch is refused"
        )
    else:
        largest_change = float(np.max(np.abs(np.diff(window)))) if n_window > 1 else 0.0
        iterative_value = largest_change
        iterative_passed = largest_change <= eps
        iterative_detail = (
            "no geometric progression could be fitted; judged on the largest "
            f"single-iteration change instead ({iterative.reason})"
        )

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
            margin=(n_eff / config.lambda_ind) if length_ok else 0.0,
            detail=(f"{n_window} samples, D_N = {d_n:.3g}, "
                    f"{n_eff:.1f} effective"),
        ),
    ]

    binding = min(gates, key=lambda g: g.margin)

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
        mann_kendall_z=mk.z,
        mann_kendall_p=mk.p,
        two_halves_delta=two_halves_delta,
        two_halves_t=two_halves_t,
        d_n=d_n,
        n_eff=n_eff,
        tau0_over_n=tau0_over_n,
        iterative=iterative,
        gates=gates,
        margin=binding.margin,
        binding_gate=binding.name,
    )
