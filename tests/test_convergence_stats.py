"""Numeric primitives behind the convergence assessment. Pure numpy/math —
no Qt, no STAR-CCM+, no per-user state, so no isolated_paths fixture needed."""
import math

import numpy as np
import pytest

from starpost.core.convergence import stats
from starpost.core.convergence.stats import (
    autocorrelation,
    decorrelation_factor,
    mann_kendall,
    ols_fit,
    regularized_incomplete_beta,
    student_t_cdf,
    student_t_ppf,
    theil_sen_slope,
)


def test_ols_recovers_an_exact_line():
    """A noiseless line is recovered exactly, with r2 == 1 and zero scatter."""
    x = np.arange(100, dtype=float)
    y = 3.0 + 2.5 * x
    fit = ols_fit(x, y)
    assert fit.slope == pytest.approx(2.5, rel=1e-12)
    assert fit.intercept == pytest.approx(3.0, rel=1e-12)
    assert fit.r2 == pytest.approx(1.0, abs=1e-12)
    assert fit.sigma == pytest.approx(0.0, abs=1e-9)
    assert fit.n == 100


def test_ols_on_a_flat_signal_reports_zero_slope_and_zero_r2():
    """A constant signal has no explainable variance: r2 is defined as 0, not
    NaN, so downstream gates never have to special-case it."""
    x = np.arange(50, dtype=float)
    y = np.full(50, 7.0)
    fit = ols_fit(x, y)
    assert fit.slope == pytest.approx(0.0, abs=1e-12)
    assert fit.r2 == 0.0


def test_theil_sen_ignores_a_gross_outlier():
    """The robust slope is unmoved by a single spike that drags OLS off.

    Deviation from the task brief: the brief places the spike at index 50,
    which for x = arange(101) is exactly x.mean(). A point at the mean of x
    has zero leverage on an OLS slope by construction (its (x_i - x_bar)
    weight is 0), so *no* correct OLS implementation can satisfy the second
    assertion there — verified independently against `numpy.polyfit`, which
    also returns slope == 2.0 for that input. Moving the spike to index 30
    (off-mean) preserves the test's intent — Theil-Sen ignores it, OLS
    doesn't — without asserting something mathematically impossible.
    """
    x = np.arange(101, dtype=float)
    y = 2.0 * x
    y[30] += 5000.0
    assert theil_sen_slope(x, y) == pytest.approx(2.0, rel=1e-9)
    assert ols_fit(x, y).slope != pytest.approx(2.0, rel=1e-3)


def test_mann_kendall_detects_a_monotonic_rise():
    """A strictly increasing series gives S = n(n-1)/2 and a large positive Z."""
    y = np.arange(30, dtype=float)
    mk = mann_kendall(y)
    assert mk.s == pytest.approx(30 * 29 / 2)
    assert mk.z > 4.0
    assert mk.p < 1e-4


def test_i4_mann_kendall_is_capped_and_stays_fast_on_a_long_record():
    """Uncapped, mann_kendall's np.triu_indices(n, 1) measured 1.23s and
    ~1.5GB peak RSS at n=10,000, and assess_monitor calls it for every monitor
    of every data set on every checkbox toggle and tolerance edit in the
    Convergence dialog. It must be capped exactly the way theil_sen_slope
    already is.

    Asserting the mechanism rather than wall-clock time: a long record's
    statistic must equal the statistic computed directly on the same bounded
    subsample ``_MAX_PAIRWISE_POINTS`` takes, which is only true if the O(n^2)
    pairwise comparison actually ran on the subsample and not the full
    record. A wall-clock budget is flaky under a parallel test runner sharing
    CPU with other jobs; this is not."""
    n = 100_000
    y = np.arange(n, dtype=float) + np.sin(np.arange(n) / 7.0)
    idx = np.linspace(0, n - 1, 2000).astype(int)
    mk_full = mann_kendall(y)
    mk_subsample = mann_kendall(y[idx])
    assert mk_full.s == mk_subsample.s
    assert mk_full.z == mk_subsample.z
    assert mk_full.p == mk_subsample.p
    assert mk_full.z > 4.0
    assert mk_full.p < 1e-4


def test_mann_kendall_on_a_flat_series_is_neutral():
    """All ties give S = 0, Z = 0, p = 1 — no trend claimed."""
    mk = mann_kendall(np.full(20, 3.0))
    assert mk.s == 0.0
    assert mk.z == 0.0
    assert mk.p == pytest.approx(1.0)


def test_autocorrelation_lag_zero_is_one():
    rng = np.random.default_rng(0)
    rho = autocorrelation(rng.normal(size=500))
    assert rho[0] == pytest.approx(1.0)


def test_decorrelation_factor_recovers_ar1_theory():
    """For an AR(1) process with coefficient phi, D_N = (1+phi)/(1-phi)
    exactly. This is the calibration test for every N_eff downstream."""
    phi = 0.8
    rng = np.random.default_rng(42)
    n = 200_000
    noise = rng.normal(size=n)
    y = np.empty(n)
    y[0] = noise[0]
    for i in range(1, n):
        y[i] = phi * y[i - 1] + noise[i]
    expected = (1.0 + phi) / (1.0 - phi)   # == 9.0
    d = decorrelation_factor(y)
    assert d.d_n == pytest.approx(expected, rel=0.10)
    assert d.n_eff == pytest.approx(n / d.d_n)
    assert d.tau0_over_n < 0.05


def test_decorrelation_factor_of_white_noise_is_about_one():
    rng = np.random.default_rng(7)
    d = decorrelation_factor(rng.normal(size=50_000))
    assert d.d_n == pytest.approx(1.0, abs=0.25)


def test_decorrelation_factor_never_returns_below_one():
    """Anti-correlated data would drive the sum negative; D_N is clamped so
    N_eff can never exceed N."""
    y = np.array([1.0, -1.0] * 500)
    assert decorrelation_factor(y).d_n >= 1.0


def test_incomplete_beta_matches_known_values():
    """I_x(a,b) at the symmetric midpoint is 1/2; the endpoints are 0 and 1."""
    assert regularized_incomplete_beta(2.0, 2.0, 0.5) == pytest.approx(0.5, abs=1e-12)
    assert regularized_incomplete_beta(3.0, 5.0, 0.0) == 0.0
    assert regularized_incomplete_beta(3.0, 5.0, 1.0) == 1.0
    # I_x(1,1) == x
    assert regularized_incomplete_beta(1.0, 1.0, 0.3) == pytest.approx(0.3, abs=1e-12)


def test_student_t_cdf_is_symmetric_about_zero():
    assert student_t_cdf(0.0, 10.0) == pytest.approx(0.5, abs=1e-12)
    assert student_t_cdf(1.3, 8.0) + student_t_cdf(-1.3, 8.0) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize(
    "p, df, expected",
    [
        (0.975, 10.0, 2.228),
        (0.975, 30.0, 2.042),
        (0.975, 100.0, 1.984),
        (0.95, 1.0, 6.314),
        (0.95, 20.0, 1.725),
    ],
)
def test_student_t_ppf_matches_published_quantiles(p, df, expected):
    """Against a standard t-table. 1e-3 absolute is the table's own precision."""
    assert student_t_ppf(p, df) == pytest.approx(expected, abs=1e-3)


def test_student_t_ppf_is_antisymmetric():
    assert student_t_ppf(0.025, 12.0) == pytest.approx(-student_t_ppf(0.975, 12.0), abs=1e-9)


def test_student_t_ppf_approaches_the_normal_for_large_df():
    assert student_t_ppf(0.975, 1e6) == pytest.approx(1.959964, abs=1e-3)


def test_ols_rejects_too_few_points():
    with pytest.raises(ValueError):
        ols_fit(np.array([1.0]), np.array([2.0]))


def test_autocorrelation_of_a_constant_is_finite():
    """Zero variance must not produce NaN — it returns lag-0 only."""
    rho = autocorrelation(np.full(100, 5.0))
    assert math.isfinite(rho[0])


# --- memoisation of the expensive primitives --------------------------------

def _window(seed: int = 0, n: int = 600) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (100.0 + 2.0 * (1.0 - np.exp(-np.arange(n) / 200.0))
            + rng.normal(scale=1e-6, size=n))


def test_the_pairwise_statistics_are_memoised_on_content():
    """theil_sen_slope and mann_kendall are O(n^2) in the window and together
    are 81% of a ten-data-set assessment pass (measured). The Convergence
    window re-assesses every loaded data set on every edit, and neither
    statistic depends on the tolerance or residual-drop values being edited,
    so the repeat work is pure waste.

    Keyed on array *content*, not identity: each re-assessment rebuilds its
    arrays from the cached SimResult, so identity-keying would never hit."""
    stats.clear_caches()
    y = _window()
    x = np.arange(y.size, dtype=float)

    first_ts = stats.theil_sen_slope(x, y)
    first_mk = stats.mann_kendall(y)
    assert stats.cache_info()["misses"] == 2
    assert stats.cache_info()["hits"] == 0

    # Equal-valued but distinct array objects, as a re-assessment produces.
    assert stats.theil_sen_slope(x.copy(), y.copy()) == first_ts
    assert stats.mann_kendall(y.copy()) == first_mk
    assert stats.cache_info()["hits"] == 2
    assert stats.cache_info()["misses"] == 2


def test_the_cache_distinguishes_different_data():
    """A memo that confused two different windows would silently report one
    monitor's trend for another — the worst failure this module could have."""
    stats.clear_caches()
    y = _window()
    x = np.arange(y.size, dtype=float)
    other = y.copy()
    other[300] += 5.0        # one sample differs

    assert stats.theil_sen_slope(x, other) != stats.theil_sen_slope(x, y)
    # A decreasing window of the same length must not pick up the increasing
    # one's result: same shape and dtype, opposite trend.
    assert stats.mann_kendall(y[::-1].copy()).s == -stats.mann_kendall(y).s

    # Two windows that merely *differ* need not differ in every derived
    # statistic -- both of these are strictly monotonic, so both score the
    # maximal S -- but they must occupy separate cache entries rather than
    # one standing in for the other.
    stats.clear_caches()
    stats.mann_kendall(y)
    stats.mann_kendall(_window(seed=1))
    assert stats.cache_info()["misses"] == 2
    assert stats.cache_info()["hits"] == 0


def test_the_cache_is_bounded(monkeypatch):
    """A long session must not accumulate windows without limit. The eviction
    itself is what is under test, so the cap is lowered rather than filling
    the production-sized one."""
    monkeypatch.setattr(stats, "_CACHE_MAX_ENTRIES", 16)
    stats.clear_caches()
    for seed in range(60):
        stats.mann_kendall(_window(seed=seed, n=40))
    assert stats.cache_info()["entries"] == 16


def test_the_cache_evicts_least_recently_used_first():
    """Eviction order matters: every re-assessment walks the data sets in the
    same order, so evicting the most recent entry would guarantee a miss on
    the next pass."""
    stats.clear_caches()
    windows = [_window(seed=s, n=40) for s in range(3)]
    for w in windows:
        stats.mann_kendall(w)
    stats.mann_kendall(windows[0])          # windows[0] is now most recent
    keys = list(stats._cache)
    assert keys[-1] == ("mann_kendall", (stats._array_key(windows[0]),))
    assert keys[0] == ("mann_kendall", (stats._array_key(windows[1]),))


def test_memoised_results_match_the_uncached_computation():
    """The memo must be invisible: same numbers, cached or not."""
    y = _window(seed=3)
    x = np.arange(y.size, dtype=float)
    stats.clear_caches()
    uncached_ts, uncached_mk = stats.theil_sen_slope(x, y), stats.mann_kendall(y)
    uncached_dec = stats.decorrelation_factor(y)
    cached_ts, cached_mk = stats.theil_sen_slope(x, y), stats.mann_kendall(y)
    cached_dec = stats.decorrelation_factor(y)
    assert (cached_ts, cached_mk, cached_dec) == (uncached_ts, uncached_mk,
                                                  uncached_dec)
