"""Layer 2: iterative error from the geometric progression of solution changes.

The naive estimator "the last difference is the remaining error" fails badly,
and fails worst precisely when the convergence rate is slow — which is when you
need it. If the iteration contracts with factor rho per step, the remaining
error is the sum of the geometric tail, which exceeds the last step by 1/(1-rho)
and grows without bound as rho approaches 1. Reported last-iteration
differences can be two orders of magnitude smaller than the actual iterative
error.

So: fit log10 L = c + s*n over the trailing window, then sum the tail.

    eps_iter = 10^(c + s*n0) / (1 - 10^s)      valid only for s < 0
    U_iter   = F_s * eps_iter * 10^sigma_fit,  F_s = 1.25

Two things to keep straight about this implementation:

* Summing rho^k from k = 0 gives the 1/(1-rho) above; summing only strictly
  future changes gives rho/(1-rho), smaller by a factor rho. They differ
  negligibly as rho approaches 1, which is the regime that matters, and the
  1/(1-rho) form is the conservative one. It is used here and stated in the
  result so a hand calculation does not appear to disagree.
* Inflating by the standard deviation of the fit is not a refinement. The
  reference study's central finding is that the estimator *including* the fit
  scatter is the one that performed best; the bare extrapolation was not.

This is applied to the per-QoI change series, giving a number in that QoI's own
units. That is a legitimate scalar analogue of the validated L-infinity field
estimator, but it is *not* that estimator — the validated form needs per-
iteration field data a post-processing tool reading monitor CSVs does not have.
The distinction is recorded in the output. Residual-derived values are never
converted to physical units: a STAR-CCM+ residual is an RMS over cells, i.e.
exactly the L2-type norm the source says to avoid for this purpose.
"""
from __future__ import annotations

import numpy as np

from starpost.core.convergence.models import IterativeError
from starpost.core.convergence.stats import ols_fit


def _no_estimate(reason: str, rho=None, sigma: float = 0.0,
                 r2: float = 0.0, safety_factor: float = 1.25) -> IterativeError:
    return IterativeError(
        u_iter=None, epsilon_iter=None, safety_factor=safety_factor,
        rho=rho, fit_sigma=sigma, fit_r2=r2, valid=False, reason=reason,
    )


def estimate_iterative_error(y_window: np.ndarray, config) -> IterativeError:
    """Estimate the remaining iterative error of a QoI over its trailing window.

    ``y_window`` is the QoI's values, not its differences — the change series
    is formed here."""
    y = np.asarray(y_window, dtype=float)
    if y.size < config.min_fit_points + 1:
        return _no_estimate("INSUFFICIENT_DATA: fewer than "
                            f"{config.min_fit_points} change samples",
                            safety_factor=config.safety_factor)

    changes = np.abs(np.diff(y))
    index = np.arange(changes.size, dtype=float)
    positive = changes > 0
    if positive.sum() < config.min_fit_points:
        return _no_estimate(
            "INSUFFICIENT_DATA: too few non-zero changes to fit a progression",
            safety_factor=config.safety_factor,
        )

    fit = ols_fit(index[positive], np.log10(changes[positive]))
    rho = 10.0 ** fit.slope

    if fit.slope >= 0:
        return _no_estimate(
            "NO_ESTIMATE: the change series is not contracting (slope >= 0), so "
            "the geometric tail does not converge",
            rho=rho, sigma=fit.sigma, r2=fit.r2, safety_factor=config.safety_factor,
        )
    if rho > config.rho_stagnant:
        return _no_estimate(
            f"ASYMPTOTICALLY_STAGNANT: rho = {rho:.5f} exceeds "
            f"{config.rho_stagnant}; the extrapolated error is enormous and the "
            "fit is untrustworthy. More iterations at this rate will not help",
            rho=rho, sigma=fit.sigma, r2=fit.r2, safety_factor=config.safety_factor,
        )

    # The fitted value at the last performed iteration, not the raw one: a
    # single small final difference would otherwise understate the tail.
    n0 = float(index[-1])
    fitted_last = 10.0 ** (fit.intercept + fit.slope * n0)
    epsilon_iter = fitted_last / (1.0 - rho)
    u_iter = config.safety_factor * epsilon_iter * 10.0 ** fit.sigma

    return IterativeError(
        u_iter=u_iter,
        epsilon_iter=epsilon_iter,
        safety_factor=config.safety_factor,
        rho=rho,
        fit_sigma=fit.sigma,
        fit_r2=fit.r2,
        valid=True,
        reason="",
    )
