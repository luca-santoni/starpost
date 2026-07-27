"""Layer 1: residual diagnostics.

Residuals are a health monitor and a necessary condition, never the convergence
criterion — the verdict lives in the engineering quantities. Two properties of
a STAR-CCM+ residual drive everything here:

* With auto normalization the value is relative to the first few iterations, so
  a threshold like 1e-4 means "four decades below the initial transient peak",
  not an absolute error. Absolute residual levels are not portable across cases
  or even across initialisations of the same case; decades dropped is.
* The monitor is an RMS over cells, so it is dominated by the worst cells. A
  handful of bad cells nobody cares about can hold the whole monitor up. That
  is the mechanism behind most STALLED classifications, and it is why the
  STALLED recommendation points at the per-cell residual field function rather
  than at more iterations.

One deliberate tightening of the published ladder: rungs 5 and 6 test
``s > -s_flat`` rather than ``|s| < s_flat``, which makes the ladder total. As
published, a residual that is rising but not *sustained*-divergent matches no
rung at all; here it is judged on its decades dropped exactly as a flat
residual would be.

A second tightening, of the same shape as the divergence rung's
``s_div_min_r2``: rung 6 (CONVERGING) also requires the main-window fit to
explain at least ``s_conv_min_r2`` of the variance before its negative slope
is trusted. A residual sitting flat within its own noise has a fitted slope
that lands on either side of ``s_flat`` at random, with r^2 near 0 either
way — a real STAR-CCM+ run had four equations behaving identically (all flat,
r^2 <= 0.02) with three landing STALLED and the fourth CONVERGING purely
because its noise happened to nudge the slope past the threshold. Below the
r^2 floor, rung 6 falls through to the same STALLED/PLATEAU_LOW split its
flat siblings use, so equations doing the same thing get the same verdict.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from starpost.core.convergence.models import (
    EquationClass,
    ResidualAssessment,
    ResidualState,
)
from starpost.core.convergence.signals import equation_class, has_non_finite, window_bounds
from starpost.core.convergence.stats import ols_fit


def _log_fit(y: np.ndarray):
    """OLS in log10 space over the strictly positive samples. Residuals are
    positive by construction, but a hard zero appears occasionally and must not
    produce a warning storm or a NaN slope."""
    index = np.arange(y.size, dtype=float)
    positive = y > 0
    if positive.sum() < 3:
        return None
    return ols_fit(index[positive], np.log10(y[positive]))


def _precision_floor(precision: Optional[str], config) -> Optional[float]:
    """The relative residual level that counts as the arithmetic floor.

    None when the precision is unknown, which suppresses the machine-precision
    rung entirely. A single-precision run judged against the double-precision
    floor is permanently STALLED, so guessing here is worse than declining."""
    if precision == "double":
        return config.eps_prec_double
    if precision == "single":
        return config.eps_prec_single
    return None


def assess_residual(name: str, y: np.ndarray, config,
                    precision: Optional[str] = None,
                    auto_norm_sample_count: int = 5) -> ResidualAssessment:
    """Classify one residual equation over its final segment.

    ``y`` is the final contiguous segment only — a restart resets the
    auto-normalization reference, so fitting across one is meaningless."""
    eq_class = equation_class(name)
    d_min = config.d_min if eq_class is EquationClass.PRIMARY else config.d_min_turb

    n0 = max(1, min(auto_norm_sample_count, y.size))
    finite_head = y[:n0][np.isfinite(y[:n0])]
    r_ref = float(finite_head.max()) if finite_head.size else float("nan")

    start, end, _ = window_bounds(y.size, config)
    window = y[start:end]
    finite_window = window[np.isfinite(window)]
    r_terminal = float(np.median(finite_window)) if finite_window.size else float("nan")

    fit = _log_fit(window)
    slope = fit.slope if fit else 0.0
    r2 = fit.r2 if fit else 0.0
    sigma = fit.sigma if fit else 0.0
    decay = 10.0 ** slope

    if r_ref > 0 and r_terminal > 0:
        decades = math.log10(r_ref / r_terminal)
    else:
        decades = 0.0

    # Rung 3 looks only at the most recent s_div_window iterations, so a
    # divergence that begins after a long healthy decay is caught within that
    # many iterations rather than being averaged away by the full window.
    #
    # The slope alone is not enough: on an oscillating residual the window
    # lands on whatever phase the record happens to end on, so the fitted
    # slope is oscillation phase, not trend, and its r^2 is near 0. Divergence
    # is the strongest claim this module makes, so the slope is trusted only
    # when the fit actually explains the tail — the same class of check as
    # iterative.py's min_fit_r2 guarding its own slope-derived rho.
    tail = y[-config.s_div_window:]
    tail_fit = _log_fit(tail) if tail.size >= config.s_div_window else None

    # The r^2 floor is still not enough on its own: a half-cycle of an
    # oscillation is itself well fitted by a straight line, so its r^2 lands
    # wherever the phase happens to put it — a real STAR-CCM+ run measured
    # tail fits with r^2 above s_div_min_r2 on residuals that were merely
    # oscillating about a flat plateau. The discriminator an oscillation
    # cannot fake is that it returns to its prior level; a genuine divergence
    # does not. s_div_level_ratio is the ratio of the tail window's median to
    # the median of the block immediately preceding it — see config.py for
    # the measured separation between real oscillations and synthetic
    # divergences. When there is no preceding baseline to compare against
    # (the record is barely longer than the tail window itself), the ratio
    # cannot be measured and defaults to 1.0, which denies the claim — that
    # is a data-starved edge case, not evidence of oscillation, but growth
    # too young to have a baseline is also too young to be told apart from
    # oscillation by this conjunct; it is left to the kappa_div rung as it
    # continues (see s_div_level_ratio's provenance comment).
    baseline_end = y.size - config.s_div_window
    baseline_start = max(0, baseline_end - config.s_div_baseline_window)
    baseline = y[baseline_start:baseline_end]
    tail_positive = tail[tail > 0]
    baseline_positive = baseline[baseline > 0]
    if tail_positive.size and baseline_positive.size:
        baseline_median = float(np.median(baseline_positive))
        tail_median = float(np.median(tail_positive))
        level_shift_ratio = (tail_median / baseline_median
                             if baseline_median > 0 else math.inf)
    else:
        level_shift_ratio = 1.0

    sustained_growth = bool(
        tail_fit and tail_fit.slope > config.s_div and tail_fit.r2 >= config.s_div_min_r2
        and level_shift_ratio >= config.s_div_level_ratio
    )

    floor = _precision_floor(precision, config)
    at_floor = (
        floor is not None and r_ref > 0 and r_terminal > 0
        and r_terminal / r_ref <= floor
    )

    if has_non_finite(window):
        state = ResidualState.DIVERGING
    elif r_ref > 0 and r_terminal > config.kappa_div * r_ref:
        state = ResidualState.DIVERGING
    elif sustained_growth:
        state = ResidualState.DIVERGING
    elif at_floor:
        state = ResidualState.MACHINE_PRECISION
    elif slope > -config.s_flat or r2 < config.s_conv_min_r2:
        # A negative slope past s_flat is not enough on its own: on white
        # noise around a flat plateau, the fitted slope is equally likely to
        # land on either side of the threshold by a hair, and its r^2 is
        # near 0 either way — the same class of check as the divergence
        # rung's s_div_min_r2, applied here so equations that are all
        # equally flat within their own noise get the same classification
        # rather than splitting on the sign of a meaningless slope.
        state = ResidualState.STALLED if decades < d_min else ResidualState.PLATEAU_LOW
    else:
        state = ResidualState.CONVERGING

    iterations_to_target: Optional[float] = None
    if (state is ResidualState.CONVERGING and slope < 0
            and r2 >= config.s_conv_min_r2 and r_ref > 0 and r_terminal > 0):
        target = r_ref * 10.0 ** (-d_min)
        if target < r_terminal:
            iterations_to_target = math.log10(target / r_terminal) / slope

    return ResidualAssessment(
        name=name,
        equation_class=eq_class,
        r_ref=r_ref,
        r_terminal=r_terminal,
        decades_dropped=decades,
        log_slope=slope,
        decay_factor=decay,
        fit_r2=r2,
        fit_sigma=sigma,
        state=state,
        iterations_to_target=iterations_to_target,
    )
