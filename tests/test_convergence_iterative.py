"""Layer 2: geometric-progression iterative-error estimation. Includes V1."""
import numpy as np
import pytest

from starpost.core.convergence.config import ConvergenceConfig
from starpost.core.convergence.iterative import estimate_iterative_error


def approaching(phi_inf: float, amplitude: float, rho: float, n: int) -> np.ndarray:
    """phi_n = phi_inf - A * rho^n: a fixed point approached geometrically.
    The true remaining error at sample n is exactly A * rho^n."""
    return phi_inf - amplitude * rho ** np.arange(n, dtype=float)


def test_v1_the_estimate_brackets_the_true_remaining_error():
    """V1: the whole point of the estimator. The naive 'last difference is the
    remaining error' understates it by a factor 1/(1-rho), which blows up
    exactly when convergence is slow and the estimate matters most."""
    rho, amplitude, n = 0.97, 4.0, 300
    y = approaching(10.0, amplitude, rho, n)
    true_remaining = amplitude * rho ** (n - 1)
    last_difference = abs(y[-1] - y[-2])

    e = estimate_iterative_error(y, ConvergenceConfig())

    assert e.valid is True
    assert e.rho == pytest.approx(rho, rel=0.01)
    assert e.u_iter >= true_remaining
    assert e.u_iter <= 5.0 * true_remaining
    assert last_difference < true_remaining     # the failure mode being avoided


def test_the_safety_factor_and_inflation_are_both_applied():
    """U_iter = F_s * eps_iter * 10^sigma_fit. Including the standard deviation
    of the fit is what makes the extrapolation reliable, so it is never
    optional."""
    y = approaching(10.0, 4.0, 0.97, 300)
    e = estimate_iterative_error(y, ConvergenceConfig())
    assert e.safety_factor == 1.25
    assert e.u_iter == pytest.approx(
        1.25 * e.epsilon_iter * 10.0 ** e.fit_sigma, rel=1e-9
    )


def test_the_summation_convention_is_recorded():
    """A user checking against a hand calculation must not be confused by a
    factor of rho, so the convention is stated in the result."""
    e = estimate_iterative_error(approaching(10.0, 4.0, 0.97, 300), ConvergenceConfig())
    assert "1/(1-rho)" in e.summation_convention
    assert "10^sigma" in e.inflation_form or "sigma" in e.inflation_form


def test_a_growing_change_series_yields_no_estimate():
    """Non-negative slope means the iteration is not contracting; the
    geometric tail does not converge and no number is offered."""
    y = 10.0 + 0.001 * 1.01 ** np.arange(300, dtype=float)
    e = estimate_iterative_error(y, ConvergenceConfig())
    assert e.valid is False
    assert e.u_iter is None
    assert "NO_ESTIMATE" in e.reason


def test_too_few_points_yields_insufficient_data():
    e = estimate_iterative_error(approaching(10.0, 4.0, 0.97, 8), ConvergenceConfig())
    assert e.valid is False
    assert "INSUFFICIENT_DATA" in e.reason


def test_a_stagnant_iteration_is_flagged_and_gives_no_number():
    """rho > 0.999: the extrapolated error is enormous and the fit is not
    trustworthy. More iterations at this rate will not help, and reporting a
    huge but precise-looking number would be worse than reporting none."""
    e = estimate_iterative_error(approaching(10.0, 4.0, 0.9999, 400),
                                 ConvergenceConfig())
    assert e.valid is False
    assert "ASYMPTOTICALLY_STAGNANT" in e.reason


def test_an_exactly_constant_signal_gives_no_estimate_without_raising():
    """Every successive difference is zero, so the log fit has no support."""
    e = estimate_iterative_error(np.full(300, 2.5), ConvergenceConfig())
    assert e.valid is False
    assert e.u_iter is None


def test_the_estimate_is_in_the_signal_units():
    """Scaling the QoI by 1000 scales U_iter by 1000 — it is an absolute
    quantity in the monitor's own units, directly comparable to a tolerance."""
    config = ConvergenceConfig()
    small = estimate_iterative_error(approaching(10.0, 4.0, 0.97, 300), config)
    large = estimate_iterative_error(approaching(1e4, 4e3, 0.97, 300), config)
    assert large.u_iter == pytest.approx(1000.0 * small.u_iter, rel=1e-6)


def test_noise_widens_the_estimate_through_the_fit_scatter():
    """A noisy change series has a larger sigma_fit, so the inflation makes the
    estimate more conservative rather than falsely precise."""
    config = ConvergenceConfig()
    clean = approaching(10.0, 4.0, 0.97, 300)
    rng = np.random.default_rng(3)
    noisy = clean + rng.normal(scale=1e-3, size=clean.size)
    assert (estimate_iterative_error(noisy, config).fit_sigma
            > estimate_iterative_error(clean, config).fit_sigma)


def test_settled_noise_is_not_mistaken_for_stagnation():
    """A monitor that has settled to noise has no geometric structure in its
    change series. The fitted slope is an artifact and rho lands near 1 by
    chance, which previously read as ASYMPTOTICALLY_STAGNANT on most seeds and
    made a converged monitor permanently un-passable."""
    config = ConvergenceConfig()
    for seed in range(10):
        rng = np.random.default_rng(seed)
        y = 100.0 + rng.normal(scale=1e-5, size=600)
        e = estimate_iterative_error(y, config)
        assert "ASYMPTOTICALLY_STAGNANT" not in e.reason, f"seed {seed}"
        assert e.valid is False
        assert "no geometric structure" in e.reason


def test_genuine_stagnation_is_still_flagged():
    """The contrast case: a real, clean geometric approach at rho > 0.999 has
    r^2 near 1 and must still be flagged."""
    y = 100.0 - 5.0 * 0.9999 ** np.arange(600, dtype=float)
    e = estimate_iterative_error(y, ConvergenceConfig())
    assert e.fit_r2 > 0.9
    assert "ASYMPTOTICALLY_STAGNANT" in e.reason
