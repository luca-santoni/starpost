"""Numeric primitives for the convergence assessment.

Deliberately free of domain knowledge: these take arrays and return numbers.
Implemented against numpy and the standard library only — StarPost does not
depend on scipy, and pulling it in for four functions would cost ~60 MB in the
PyInstaller bundle.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OlsFit:
    """An ordinary-least-squares fit of y against x."""
    slope: float
    intercept: float
    r2: float
    sigma: float    # standard deviation of the fit residuals
    n: int


@dataclass(frozen=True)
class Decorrelation:
    """Autocorrelation-derived sample independence of a record."""
    d_n: float      # decorrelation factor: samples between independent observations
    tau_0: int      # lag of the first zero crossing of the autocorrelation
    n: int

    @property
    def n_eff(self) -> float:
        return self.n / self.d_n

    @property
    def tau0_over_n(self) -> float:
        return self.tau_0 / self.n if self.n else 0.0


@dataclass(frozen=True)
class MannKendall:
    """Nonparametric monotonic-trend test."""
    s: float
    z: float
    p: float


# Shared cap on the O(n^2) pairwise comparison behind theil_sen_slope and
# mann_kendall. Uncapped, n=10,000 measured 1.23s and ~1.5GB peak RSS for
# mann_kendall alone, and assess_monitor calls it for every monitor of every
# data set on every checkbox toggle and tolerance edit in the Convergence
# dialog — a 50k-iteration run with a dozen monitors would freeze the GUI for
# several seconds, and 100k would OOM.
_MAX_PAIRWISE_POINTS = 2000


def ols_fit(x: np.ndarray, y: np.ndarray) -> OlsFit:
    """Least-squares straight-line fit. ``sigma`` is the residual standard
    deviation with the usual n-2 denominator; ``r2`` is defined as 0 (not NaN)
    for a constant signal so callers never have to special-case flat data."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = x.size
    if n < 2:
        raise ValueError("ols_fit needs at least 2 points")
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    dx = x - x_mean
    sxx = float(dx @ dx)
    slope = float(dx @ (y - y_mean)) / sxx if sxx > 0 else 0.0
    intercept = y_mean - slope * x_mean
    residuals = y - (intercept + slope * x)
    ss_res = float(residuals @ residuals)
    dy = y - y_mean
    ss_tot = float(dy @ dy)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    sigma = math.sqrt(ss_res / (n - 2)) if n > 2 else 0.0
    return OlsFit(slope=slope, intercept=intercept, r2=r2, sigma=sigma, n=n)


def theil_sen_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Median of all pairwise slopes: breakdown-resistant, so a spike cannot
    drag the trend estimate the way it drags OLS. O(n^2) in pairs, which is why
    long records are subsampled to a bounded number of points first."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = x.size
    if n < 2:
        return 0.0
    if n > _MAX_PAIRWISE_POINTS:
        idx = np.linspace(0, n - 1, _MAX_PAIRWISE_POINTS).astype(int)
        x, y = x[idx], y[idx]
    i, j = np.triu_indices(x.size, k=1)
    dx = x[j] - x[i]
    ok = dx != 0
    if not ok.any():
        return 0.0
    return float(np.median((y[j] - y[i])[ok] / dx[ok]))


def mann_kendall(y: np.ndarray) -> MannKendall:
    """Mann-Kendall trend test with the standard tie-corrected variance and
    continuity correction.

    Reported to the caller as supporting evidence, and also used as one of
    two conditions denying the static-monitor escape hatch in
    ``steady.assess_monitor`` (see ``ConvergenceConfig.mk_trend_z``) — but
    never alone: z is pure statistical significance, with no effect size and
    a variance formula that assumes independent samples, so on a long or
    autocorrelated record it can be large with no physically meaningful trend
    behind it. The escape-hatch denial always pairs it with an absolute
    effect-size test (``mk_trend_drift_fraction``) before acting on it; no
    verdict in this package gates on a p-value by itself.

    Computed on a bounded subsample, the same cap and technique
    ``theil_sen_slope`` already uses, since the pairwise comparison is
    O(n^2) — see ``_MAX_PAIRWISE_POINTS``. The z-statistic's magnitude
    depends on the sample count it is computed over, so a long record's z is
    the statistic for a representative ~2000-point subsample, not the full
    record; the separation between a trending and a non-trending signal is
    preserved either way."""
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 3:
        return MannKendall(s=0.0, z=0.0, p=1.0)
    if n > _MAX_PAIRWISE_POINTS:
        idx = np.linspace(0, n - 1, _MAX_PAIRWISE_POINTS).astype(int)
        y = y[idx]
        n = y.size
    i, j = np.triu_indices(n, k=1)
    s = float(np.sign(y[j] - y[i]).sum())
    _, counts = np.unique(y, return_counts=True)
    ties = float(sum(c * (c - 1) * (2 * c + 5) for c in counts if c > 1))
    var_s = (n * (n - 1) * (2 * n + 5) - ties) / 18.0
    if var_s <= 0:
        return MannKendall(s=s, z=0.0, p=1.0)
    if s > 0:
        z = (s - 1.0) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1.0) / math.sqrt(var_s)
    else:
        z = 0.0
    p = math.erfc(abs(z) / math.sqrt(2.0))   # two-sided normal tail
    return MannKendall(s=s, z=z, p=p)


def autocorrelation(y: np.ndarray, max_lag: int | None = None) -> np.ndarray:
    """Sample autocorrelation, index 0 == lag 0 == 1.0.

    Uses the 1/N-normalised (biased) autocovariance, which is positive
    semi-definite and far better behaved at large lag than the 1/(N-tau) form.
    A constant signal has no defined correlation structure and returns [1.0]."""
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 2:
        return np.array([1.0])
    dy = y - y.mean()
    var = float(dy @ dy) / n
    if var <= 0:
        return np.array([1.0])
    if max_lag is None:
        max_lag = n - 1
    max_lag = int(min(max_lag, n - 1))
    out = np.empty(max_lag + 1)
    out[0] = 1.0
    for tau in range(1, max_lag + 1):
        out[tau] = float(dy[tau:] @ dy[:-tau]) / n / var
    return out


def decorrelation_factor(y: np.ndarray) -> Decorrelation:
    """D_N = 1 + 2 * sum(rho_tau) truncated at the first zero crossing.

    The zero-crossing truncation is the classical integral-timescale
    convention: the estimated autocorrelation is noisy and oscillatory at large
    lag, so the untruncated sum does not converge usefully. D_N is clamped to
    >= 1 so N_eff can never exceed N."""
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 4:
        return Decorrelation(d_n=1.0, tau_0=0, n=max(n, 1))
    # Scanning every lag is O(n^2); the crossing is normally at small lag, so
    # grow the search window rather than computing the whole ACF up front.
    max_lag = min(n - 1, 64)
    while True:
        rho = autocorrelation(y, max_lag=max_lag)
        negative = np.nonzero(rho[1:] < 0)[0]
        if negative.size:
            tau_0 = int(negative[0]) + 1
            break
        if max_lag >= n - 1:
            tau_0 = max_lag
            break
        max_lag = min(n - 1, max_lag * 4)
    d_n = 1.0 + 2.0 * float(rho[1:tau_0].sum())
    return Decorrelation(d_n=max(d_n, 1.0), tau_0=tau_0, n=n)


def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _betacf(a: float, b: float, x: float, iterations: int = 300,
            eps: float = 1e-14) -> float:
    """Continued-fraction expansion for the incomplete beta function, by the
    modified Lentz algorithm."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, iterations + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """I_x(a, b). The continued fraction converges fast only for
    x < (a+1)/(a+b+2), so the other branch uses the symmetry
    I_x(a,b) = 1 - I_(1-x)(b,a)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(a * math.log(x) + b * math.log1p(-x) - _log_beta(a, b))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def student_t_cdf(t: float, df: float) -> float:
    """Cumulative distribution of Student's t with ``df`` degrees of freedom."""
    x = df / (df + t * t)
    tail = 0.5 * regularized_incomplete_beta(df / 2.0, 0.5, x)
    return 1.0 - tail if t > 0 else tail


def student_t_ppf(p: float, df: float) -> float:
    """Inverse CDF of Student's t, by bisection on the CDF.

    Bisection rather than an inverse-beta expansion: it is a handful of lines,
    cannot diverge, and 200 halvings of a +/-1e4 bracket resolve to ~1e-27,
    far past what any threshold here cares about."""
    if not 0.0 < p < 1.0:
        raise ValueError("student_t_ppf needs 0 < p < 1")
    if p == 0.5:
        return 0.0
    lo, hi = -1e4, 1e4
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if student_t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
