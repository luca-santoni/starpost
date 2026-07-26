# Convergence Tool (Phase 1: Steady Runs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Convergence tool that assesses whether a solved steady STAR-CCM+ simulation has converged, reporting a state, a confidence level, a convergence index, the binding constraint, and a list of reasons with suggested actions.

**Architecture:** A new Qt-free, STAR-CCM+-free `core/convergence/` package of small single-responsibility modules (numeric primitives → signal prep → three analysis layers → verdict roll-up), consumed by one non-modal `ConvergenceDialog`. Every module takes arrays plus a config and returns a dataclass, so the whole validation suite runs headless. Reads cached `SimResult` data only — no STAR-CCM+ re-run.

**Tech Stack:** Python 3.11, numpy, PySide6, pytest. **No new dependencies.**

## Global Constraints

- **Design spec:** `docs/superpowers/specs/2026-07-25-convergence-tool-design.md`. Section references of the form "§3.3" in that spec and in this plan refer to the *convergence theory specification* supplied by the user (not checked into the repo), not to the design doc.
- **No new dependencies.** numpy only. Do not add scipy or statsmodels.
- **Qt-free core.** Nothing under `src/starpost/core/convergence/` may import PySide6 or pyqtgraph.
- **Lazy import.** `core.convergence` must not be imported at module top level anywhere on the startup path (CLAUDE.md startup-latency convention). `main_window.py` imports it inside the menu slot.
- **Line length 100, target py311** (`ruff check .` must pass).
- **Run the full suite with `python scripts/run_tests.py`**, never a bare `python -m pytest`. Single-file `python -m pytest tests/test_x.py` is fine.
- **Headless:** prefix GUI tests with `QT_QPA_PLATFORM=offscreen`.
- **Tests isolate per-user state** with the `autouse` fixture that monkeypatches `paths.platformdirs.user_config_dir` / `user_cache_dir` to `tmp_path`. Only needed for tests touching config/cache.
- **Commit after every task.** Log user-facing changes in `CHANGELOG.md` (newest first) — that happens once, in Task 11.
- **No new keyboard shortcut**, so `src/starpost/gui/shortcuts.py` and `docs/starpost_hotkeys.txt` stay untouched.
- **Brand:** "StarPost" in prose, lowercase `starpost` only for package/path/command identifiers.

---

### Task 1: Numeric primitives (`stats.py`)

Pure numeric helpers with no domain knowledge. Everything later tasks need for regression, trend, autocorrelation and Student-$t$ work.

**Files:**
- Create: `src/starpost/core/convergence/__init__.py` (empty for now — Task 8 fills it)
- Create: `src/starpost/core/convergence/stats.py`
- Test: `tests/test_convergence_stats.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `OlsFit(slope: float, intercept: float, r2: float, sigma: float, n: int)` — frozen dataclass
  - `Decorrelation(d_n: float, tau_0: int, n: int)` with properties `n_eff -> float`, `tau0_over_n -> float`
  - `MannKendall(s: float, z: float, p: float)` — frozen dataclass
  - `ols_fit(x: np.ndarray, y: np.ndarray) -> OlsFit`
  - `theil_sen_slope(x: np.ndarray, y: np.ndarray) -> float`
  - `mann_kendall(y: np.ndarray) -> MannKendall`
  - `autocorrelation(y: np.ndarray, max_lag: int | None = None) -> np.ndarray` (index 0 is lag 0, value 1.0)
  - `decorrelation_factor(y: np.ndarray) -> Decorrelation`
  - `regularized_incomplete_beta(a: float, b: float, x: float) -> float`
  - `student_t_cdf(t: float, df: float) -> float`
  - `student_t_ppf(p: float, df: float) -> float`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_convergence_stats.py`:

```python
"""Numeric primitives behind the convergence assessment. Pure numpy/math —
no Qt, no STAR-CCM+, no per-user state, so no isolated_paths fixture needed."""
import math

import numpy as np
import pytest

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
    """The robust slope is unmoved by a single spike that drags OLS off."""
    x = np.arange(101, dtype=float)
    y = 2.0 * x
    y[50] += 5000.0
    assert theil_sen_slope(x, y) == pytest.approx(2.0, rel=1e-9)
    assert ols_fit(x, y).slope != pytest.approx(2.0, rel=1e-3)


def test_mann_kendall_detects_a_monotonic_rise():
    """A strictly increasing series gives S = n(n-1)/2 and a large positive Z."""
    y = np.arange(30, dtype=float)
    mk = mann_kendall(y)
    assert mk.s == pytest.approx(30 * 29 / 2)
    assert mk.z > 4.0
    assert mk.p < 1e-4


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_convergence_stats.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.core.convergence'`

- [ ] **Step 3: Create the package and implement `stats.py`**

Create `src/starpost/core/convergence/__init__.py` as an empty file (Task 8 gives it the public `assess` entry point).

Create `src/starpost/core/convergence/stats.py`:

```python
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
    max_points = 2000
    if n > max_points:
        idx = np.linspace(0, n - 1, max_points).astype(int)
        x, y = x[idx], y[idx]
    i, j = np.triu_indices(x.size, k=1)
    dx = x[j] - x[i]
    ok = dx != 0
    if not ok.any():
        return 0.0
    return float(np.median((y[j] - y[i])[ok] / dx[ok]))


def mann_kendall(y: np.ndarray) -> MannKendall:
    """Mann-Kendall trend test with the standard tie-corrected variance and
    continuity correction. Reported as supporting evidence only: the design
    never gates a verdict on a p-value alone."""
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 3:
        return MannKendall(s=0.0, z=0.0, p=1.0)
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convergence_stats.py -q`
Expected: PASS, 17 passed.

Note: `test_decorrelation_factor_recovers_ar1_theory` builds a 200 000-sample AR(1) series in a Python loop and takes a few seconds. That is deliberate — it is the calibration test for every `N_eff` in the tool.

- [ ] **Step 5: Lint**

Run: `ruff check src/starpost/core/convergence/ tests/test_convergence_stats.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/starpost/core/convergence/__init__.py src/starpost/core/convergence/stats.py tests/test_convergence_stats.py
git commit -m "feat: numeric primitives for convergence assessment

OLS, Theil-Sen, Mann-Kendall, autocorrelation with zero-crossing
truncated decorrelation factor, and Student-t via a local incomplete
beta. No scipy: four functions do not justify ~60 MB in the bundle.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Output schema and thresholds (`models.py`, `config.py`)

The dataclasses every later task fills in, and the threshold table as data with its evidence provenance.

**Files:**
- Create: `src/starpost/core/convergence/models.py`
- Create: `src/starpost/core/convergence/config.py`
- Test: `tests/test_convergence_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Enums `ConvergenceState`, `ResidualState`, `Confidence`, `AdvisoryFlag`, `Provenance`, `Severity`, `EquationClass`, `ScaleSource`
  - `MetadataField(value: str | None, provenance: Provenance)` with `.known -> bool`
  - `RunMetadata(solver_regime, solver_type, precision, residual_normalization: MetadataField, auto_norm_sample_count: int, cell_count: int | None, n_iterations: int | None)`
  - `ResidualAssessment(name, equation_class, r_ref, r_terminal, decades_dropped, log_slope, decay_factor, fit_r2, fit_sigma, state, iterations_to_target: float | None)`
  - `IterativeError(u_iter: float | None, epsilon_iter: float | None, safety_factor, rho, fit_sigma, fit_r2, valid: bool, reason: str)`
  - `GateResult(name: str, passed: bool, value: float, limit: float, detail: str)`
  - `MonitorAssessment(...)` — full field list in the code below
  - `Reason(severity, target, message, suggested_action, estimated_extra_iterations: int | None)`
  - `ConvergenceAssessment(...)` — full field list in the code below
  - `MonitorConfig(is_primary: bool, tolerance_fraction: float | None, reference_scale: float | None)`
  - `ConvergenceConfig(...)` with `.tolerance_for(name) -> float` and `.monitor(name) -> MonitorConfig`
  - `TOLERANCE_PRESETS: dict[str, float]`, `THRESHOLD_PROVENANCE: dict[str, str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_convergence_config.py`:

```python
"""The convergence threshold table and its evidence provenance."""
import pytest

from starpost.core.convergence.config import (
    THRESHOLD_PROVENANCE,
    TOLERANCE_PRESETS,
    ConvergenceConfig,
    MonitorConfig,
)
from starpost.core.convergence.models import Provenance, MetadataField


def test_defaults_match_the_published_threshold_table():
    """The [S]-tagged values are from the literature and must not drift: the
    ASME JFE editorial policy requires at least three decades of residual
    drop, and the iterative-error safety factor is 1.25."""
    c = ConvergenceConfig()
    assert c.d_min == 3.0
    assert c.d_min_advisory == 4.0
    assert c.d_min_turb == 2.0
    assert c.safety_factor == 1.25
    assert c.s_flat == 1e-4
    assert c.s_div == 1e-3
    assert c.s_div_window == 50
    assert c.kappa_div == 10.0
    assert c.eps_prec_double == 1e-13
    assert c.eps_prec_single == 1e-6
    assert c.window_min == 200
    assert c.window_fraction == 0.2
    assert c.gamma == 5.0
    assert c.lambda_ind == 20
    assert c.n_eff_min == 30.0
    assert c.n_eff_floor == 10.0
    assert c.tau0_over_n_warn == 0.05
    assert c.min_fit_points == 20
    assert c.rho_stagnant == 0.999


def test_tolerance_presets():
    assert TOLERANCE_PRESETS["screening"] == 1e-3
    assert TOLERANCE_PRESETS["production"] == 5e-4


def test_every_threshold_carries_its_provenance():
    """A user asking 'where does this number come from?' must get an answer,
    so every configurable field is tagged [S] (sourced) or [D] (design)."""
    c = ConvergenceConfig()
    configurable = {
        f for f in c.__dataclass_fields__ if f not in ("monitors", "tolerance_fraction")
    }
    assert configurable <= set(THRESHOLD_PROVENANCE)
    assert set(THRESHOLD_PROVENANCE.values()) <= {"[S]", "[D]"}
    assert THRESHOLD_PROVENANCE["d_min"] == "[S]"
    assert THRESHOLD_PROVENANCE["safety_factor"] == "[S]"
    assert THRESHOLD_PROVENANCE["s_flat"] == "[D]"


def test_monitor_config_defaults_to_non_primary_auto_scale():
    m = ConvergenceConfig().monitor("anything")
    assert m.is_primary is False
    assert m.tolerance_fraction is None
    assert m.reference_scale is None


def test_per_monitor_tolerance_overrides_the_global_one():
    c = ConvergenceConfig(
        tolerance_fraction=1e-3,
        monitors={"Drag": MonitorConfig(is_primary=True, tolerance_fraction=5e-4)},
    )
    assert c.tolerance_for("Drag") == 5e-4
    assert c.tolerance_for("Lift") == 1e-3


def test_metadata_field_known_only_when_a_value_was_resolved():
    assert MetadataField("steady", Provenance.DERIVED).known is True
    assert MetadataField(None, Provenance.ABSENT).known is False
    assert MetadataField("", Provenance.ABSENT).known is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_convergence_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.core.convergence.config'`

- [ ] **Step 3: Implement `models.py`**

Create `src/starpost/core/convergence/models.py`:

```python
"""Output schema for a convergence assessment.

Mirrors the theory specification's output contract. Two rules run through it:
every numeric result carries the estimator that produced it plus a validity
flag, and nothing is silently NaN.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ConvergenceState(str, Enum):
    """Terminal states, in ladder order — first match wins."""
    INTEGRITY_FAIL = "INTEGRITY_FAIL"
    DIVERGED = "DIVERGED"
    STALLED = "STALLED"
    UNSTEADY_UNSUPPORTED = "UNSTEADY_UNSUPPORTED"
    SLOW_DRIFT = "SLOW_DRIFT"
    CONVERGING = "CONVERGING"
    CONVERGED = "CONVERGED"
    CONVERGED_MACHINE = "CONVERGED_MACHINE"


class ResidualState(str, Enum):
    """Per-equation residual classification."""
    DIVERGING = "DIVERGING"
    MACHINE_PRECISION = "MACHINE_PRECISION"
    STALLED = "STALLED"
    PLATEAU_LOW = "PLATEAU_LOW"
    CONVERGING = "CONVERGING"


class Confidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class AdvisoryFlag(str, Enum):
    """Non-terminal flags. Any of these may attach to any state, including
    CONVERGED — that pairing is often the most important thing to surface."""
    TREND_ESTIMATE_UNSTABLE = "TREND_ESTIMATE_UNSTABLE"
    ASYMPTOTICALLY_STAGNANT = "ASYMPTOTICALLY_STAGNANT"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
    PRECISION_UNKNOWN = "PRECISION_UNKNOWN"
    NORMALIZATION_UNKNOWN = "NORMALIZATION_UNKNOWN"
    WINDOW_TOO_SHORT = "WINDOW_TOO_SHORT"
    RESTART_SUSPECTED = "RESTART_SUSPECTED"
    OSCILLATORY_SUSPECTED = "OSCILLATORY_SUSPECTED"


class Provenance(str, Enum):
    """Where a metadata field's value came from. The distinction matters: a
    derived value is good enough to branch on, an absent one suppresses the
    verdict that depends on it rather than being guessed."""
    EXTRACTED = "extracted"
    DERIVED = "derived"
    ABSENT = "absent"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EquationClass(str, Enum):
    """Turbulence residuals routinely stall one to two orders above the
    momentum residuals without harming the QoIs, so they are held to a lower
    threshold and can never alone force a NOT_CONVERGED."""
    PRIMARY = "primary"
    TURBULENCE = "turbulence"


class ScaleSource(str, Enum):
    """Which rung of the reference-scale ladder supplied S_j."""
    USER = "user-supplied"
    MEAN = "trailing-window mean"
    RANGE = "robust record range"


@dataclass(frozen=True)
class MetadataField:
    value: Optional[str]
    provenance: Provenance

    @property
    def known(self) -> bool:
        return bool(self.value)


@dataclass
class RunMetadata:
    solver_regime: MetadataField
    solver_type: MetadataField
    precision: MetadataField
    residual_normalization: MetadataField
    auto_norm_sample_count: int = 5
    cell_count: Optional[int] = None
    n_iterations: Optional[int] = None

    @property
    def is_unsteady(self) -> bool:
        return (self.solver_regime.value or "").endswith("unsteady")


@dataclass
class ResidualAssessment:
    name: str
    equation_class: EquationClass
    r_ref: float
    r_terminal: float
    decades_dropped: float
    log_slope: float
    decay_factor: float
    fit_r2: float
    fit_sigma: float
    state: ResidualState
    iterations_to_target: Optional[float] = None


@dataclass
class IterativeError:
    """Geometric-progression tail estimate of the remaining iterative error.

    A scalar analogue of the validated L-infinity field estimator, not the
    estimator itself — the validated form needs per-iteration field data that a
    post-processing tool reading monitor CSVs does not have."""
    u_iter: Optional[float]
    epsilon_iter: Optional[float]
    safety_factor: float
    rho: Optional[float]
    fit_sigma: float
    fit_r2: float
    valid: bool
    reason: str = ""
    summation_convention: str = "1/(1-rho), from the last performed iteration"
    inflation_form: str = "multiplicative, 10^sigma_fit"


@dataclass
class GateResult:
    """One convergence gate's outcome.

    ``margin`` is normalised so that >= 1 always means "passed", whichever
    direction the underlying comparison runs: limit/value for the gates where
    smaller is better, value/limit for the window-adequacy gate where larger
    is. That makes min(margin) over the gates exactly equivalent to "every gate
    passed", which is the property the convergence index relies on."""
    name: str
    passed: bool
    value: float     # the quantity tested, in the monitor's physical units
    limit: float     # the tolerance it was tested against, same units
    margin: float = float("inf")
    detail: str = ""


@dataclass
class MonitorAssessment:
    name: str
    is_primary: bool
    reference_scale: float
    scale_source: ScaleSource
    tolerance_fraction: float
    tolerance_abs: float
    window_start: int
    window_end: int
    n_window: int
    mean: float
    std: float
    band_full: float
    band_p95: float
    ols_slope: float
    theil_sen_slope: float
    projected_drift: float
    mann_kendall_z: float
    mann_kendall_p: float
    two_halves_delta: float
    two_halves_t: float
    d_n: float
    n_eff: float
    tau0_over_n: float
    iterative: IterativeError
    gates: list[GateResult] = field(default_factory=list)
    margin: float = 0.0
    binding_gate: str = ""

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)


@dataclass
class Reason:
    severity: Severity
    target: str
    message: str
    suggested_action: str = ""
    estimated_extra_iterations: Optional[int] = None


@dataclass
class ConvergenceAssessment:
    sim_path: str
    sim_name: str
    metadata: RunMetadata
    state: ConvergenceState
    confidence: Confidence
    confidence_rule: str
    convergence_index: Optional[float]
    binding_constraint: str
    flags: list[AdvisoryFlag] = field(default_factory=list)
    residuals: list[ResidualAssessment] = field(default_factory=list)
    monitors: list[MonitorAssessment] = field(default_factory=list)
    reasons: list[Reason] = field(default_factory=list)
    thresholds_used: dict = field(default_factory=dict)
    n_segments: int = 1
```

- [ ] **Step 4: Implement `config.py`**

Create `src/starpost/core/convergence/config.py`:

```python
"""Convergence thresholds, as data.

Every value is overridable and every value records where it came from: [S] is
traceable to a cited publication, [D] is a defensible engineering default
chosen for this tool. The assessment reports which values it used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Per-QoI tolerance as a fraction of the reference scale S_j.
TOLERANCE_PRESETS: dict[str, float] = {
    "screening": 1e-3,     # 0.1%
    "production": 5e-4,    # 0.05%
}

# [S] = sourced to the literature; [D] = this tool's design default.
THRESHOLD_PROVENANCE: dict[str, str] = {
    "d_min": "[S]",              # ASME JFE editorial policy: at least 3 decades
    "d_min_advisory": "[D]",
    "d_min_turb": "[D]",
    "s_flat": "[D]",
    "s_div": "[D]",
    "s_div_window": "[D]",
    "kappa_div": "[D]",
    "eps_prec_double": "[D]",
    "eps_prec_single": "[D]",
    "safety_factor": "[S]",      # F_s = 1.25
    "window_min": "[D]",
    "window_fraction": "[D]",
    "gamma": "[D]",
    "lambda_ind": "[D]",
    "n_eff_min": "[D]",
    "n_eff_floor": "[D]",
    "tau0_over_n_warn": "[D]",
    "min_fit_points": "[D]",
    "rho_stagnant": "[D]",
    "min_fit_r2": "[D]",
    "marginal_low": "[D]",
    "marginal_high": "[D]",
}


@dataclass
class MonitorConfig:
    """Per-monitor overrides. ``reference_scale`` set means rung 1 of the
    scale ladder (user-supplied physical scale) is taken."""
    is_primary: bool = False
    tolerance_fraction: Optional[float] = None
    reference_scale: Optional[float] = None


@dataclass
class ConvergenceConfig:
    # --- residual diagnostics -------------------------------------------
    d_min: float = 3.0             # required decades, continuity/momentum/energy
    d_min_advisory: float = 4.0    # stricter advisory target
    d_min_turb: float = 2.0        # required decades, Tke/Tdr/Sdr (warning only)
    s_flat: float = 1e-4           # |log-slope| below which residuals count as flat
    s_div: float = 1e-3            # log-slope above which divergence is declared
    s_div_window: int = 50         # iterations the divergent slope must be sustained
    kappa_div: float = 10.0        # residual growth vs reference => diverged
    eps_prec_double: float = 1e-13
    eps_prec_single: float = 1e-6

    # --- iterative error ------------------------------------------------
    safety_factor: float = 1.25
    min_fit_points: int = 20
    rho_stagnant: float = 0.999
    min_fit_r2: float = 0.10       # below this the change series has no
                                   # geometric structure to extrapolate

    # --- QoI gates ------------------------------------------------------
    tolerance_fraction: float = TOLERANCE_PRESETS["screening"]
    window_min: int = 200          # N_W floor, iterations
    window_fraction: float = 0.2   # window is max(window_min, fraction * N)
    gamma: float = 5.0             # mean/sigma separation to use |mean| as scale
    lambda_ind: int = 20           # independent samples required in the window
    n_eff_min: float = 30.0        # effective samples for a High-confidence verdict
    n_eff_floor: float = 10.0      # below this, confidence is Low
    tau0_over_n_warn: float = 0.05

    # --- confidence banding ---------------------------------------------
    marginal_low: float = 0.5      # a margin inside [low, high] counts as marginal
    marginal_high: float = 2.0

    monitors: dict[str, MonitorConfig] = field(default_factory=dict)

    def monitor(self, name: str) -> MonitorConfig:
        return self.monitors.get(name, MonitorConfig())

    def tolerance_for(self, name: str) -> float:
        """Per-monitor tolerance fraction, falling back to the global preset."""
        override = self.monitor(name).tolerance_fraction
        return self.tolerance_fraction if override is None else override

    def as_dict(self) -> dict:
        """The thresholds actually used, for the assessment record. Each entry
        is (value, provenance) so the UI can show where a number came from."""
        return {
            name: (getattr(self, name), THRESHOLD_PROVENANCE[name])
            for name in THRESHOLD_PROVENANCE
        }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convergence_config.py -q`
Expected: PASS, 6 passed.

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/starpost/core/convergence/ tests/test_convergence_config.py
git add src/starpost/core/convergence/models.py src/starpost/core/convergence/config.py tests/test_convergence_config.py
git commit -m "feat: convergence assessment output schema and threshold table

Dataclasses mirroring the theory spec's output contract, plus the
threshold defaults as data with [S]/[D] evidence provenance on every
entry so the tool can answer 'where does this number come from?'.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Run metadata with provenance (`metadata.py`)

Read what the sim actually recorded, derive what can be derived, and mark the rest absent. Never guess: a guessed precision permanently misclassifies a single-precision run as `STALLED`.

**Files:**
- Create: `src/starpost/core/convergence/metadata.py`
- Test: `tests/test_convergence_metadata.py`

**Interfaces:**
- Consumes: `models.MetadataField`, `models.Provenance`, `models.RunMetadata` (Task 2).
- Produces: `read_metadata(props: SimProperties | None) -> RunMetadata`

- [ ] **Step 1: Write the failing test**

Create `tests/test_convergence_metadata.py`:

```python
"""Resolving run metadata from cached sim properties, with provenance.

The rule under test throughout: extracted beats derived beats absent, and an
absent field is never guessed."""
from starpost.core.convergence.metadata import read_metadata
from starpost.core.convergence.models import Provenance
from starpost.data.models import PropertyGroup, SimProperties


def props(*groups: PropertyGroup) -> SimProperties:
    return SimProperties(groups=list(groups))


def test_no_properties_at_all_gives_everything_absent():
    """Imported portable CSVs carry no properties. Every field must come back
    absent rather than defaulted, so the verdict degrades honestly."""
    m = read_metadata(None)
    for f in (m.solver_regime, m.solver_type, m.precision, m.residual_normalization):
        assert f.provenance is Provenance.ABSENT
        assert f.known is False


def test_regime_and_solver_type_derived_from_the_continuum_model_list():
    """The enabled-models list already names Steady/Implicit Unsteady and
    Segregated/Coupled, so these are derivable without a macro change."""
    m = read_metadata(props(PropertyGroup(
        section="continuum", name="Physics 1",
        entries=[("models", "Steady; Gas; Segregated Flow; K-Epsilon Turbulence")],
    )))
    assert m.solver_regime.value == "steady"
    assert m.solver_regime.provenance is Provenance.DERIVED
    assert m.solver_type.value == "segregated"
    assert m.solver_type.provenance is Provenance.DERIVED
    assert m.is_unsteady is False


def test_implicit_unsteady_is_recognised_and_flagged_unsteady():
    m = read_metadata(props(PropertyGroup(
        section="continuum", name="Physics 1",
        entries=[("models", "Implicit Unsteady; Liquid; Coupled Flow")],
    )))
    assert m.solver_regime.value == "implicit_unsteady"
    assert m.solver_type.value == "coupled"
    assert m.is_unsteady is True


def test_extracted_convergence_section_beats_derivation():
    """When the macro supplied the values directly, they win and are marked
    extracted — the derived route is only a fallback."""
    m = read_metadata(props(
        PropertyGroup(section="continuum", name="Physics 1",
                      entries=[("models", "Steady; Segregated Flow")]),
        PropertyGroup(section="convergence", name="", entries=[
            ("solver_regime", "implicit_unsteady"),
            ("solver_type", "coupled"),
            ("precision", "double"),
            ("residual_normalization", "auto"),
            ("auto_norm_sample_count", "5"),
        ]),
    ))
    assert m.solver_regime.value == "implicit_unsteady"
    assert m.solver_regime.provenance is Provenance.EXTRACTED
    assert m.precision.value == "double"
    assert m.precision.provenance is Provenance.EXTRACTED
    assert m.residual_normalization.value == "auto"
    assert m.auto_norm_sample_count == 5


def test_precision_is_never_derived():
    """Nothing already in the properties CSV implies build precision, so it
    stays absent until the macro supplies it."""
    m = read_metadata(props(PropertyGroup(
        section="continuum", name="Physics 1", entries=[("models", "Steady")],
    )))
    assert m.precision.provenance is Provenance.ABSENT


def test_empty_extracted_value_counts_as_absent():
    """The macro writes an empty value for 'read succeeded, nothing to report';
    that must not masquerade as a known value."""
    m = read_metadata(props(PropertyGroup(
        section="convergence", name="", entries=[("precision", "")],
    )))
    assert m.precision.known is False
    assert m.precision.provenance is Provenance.ABSENT


def test_cell_count_and_iteration_are_read_as_integers():
    m = read_metadata(props(
        PropertyGroup(section="mesh", name="", entries=[("cell_count", "1234567")]),
        PropertyGroup(section="solution", name="", entries=[("iteration", "4200")]),
    ))
    assert m.cell_count == 1234567
    assert m.n_iterations == 4200


def test_unparseable_numbers_do_not_raise():
    m = read_metadata(props(
        PropertyGroup(section="mesh", name="", entries=[("cell_count", "")]),
        PropertyGroup(section="solution", name="", entries=[("iteration", "n/a")]),
    ))
    assert m.cell_count is None
    assert m.n_iterations is None


def test_auto_norm_sample_count_defaults_to_the_star_ccm_default():
    assert read_metadata(None).auto_norm_sample_count == 5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_convergence_metadata.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.core.convergence.metadata'`

- [ ] **Step 3: Implement `metadata.py`**

Create `src/starpost/core/convergence/metadata.py`:

```python
"""Resolve run metadata from cached sim properties.

Convergence conclusions are invalid without certain metadata, and the theory
specification is explicit that it must be captured rather than guessed. So each
field records where its value came from:

    extracted  the macro's `convergence` properties section supplied it
    derived    inferred from data already in the properties CSV
    absent     unavailable — the dependent verdict is suppressed, not guessed

The precision field is deliberately never derived. Nothing already extracted
implies the build precision, and defaulting it to double would permanently
misclassify every single-precision run as STALLED.
"""
from __future__ import annotations

from typing import Optional

from starpost.core.convergence.models import MetadataField, Provenance, RunMetadata
from starpost.data.models import SimProperties

_ABSENT = MetadataField(None, Provenance.ABSENT)

# Longest first: "implicit unsteady" must win over a bare "unsteady".
_REGIME_KEYWORDS = (
    ("harmonic balance", "harmonic_balance"),
    ("implicit unsteady", "implicit_unsteady"),
    ("explicit unsteady", "explicit_unsteady"),
    ("steady", "steady"),
)
_SOLVER_TYPE_KEYWORDS = (
    ("coupled", "coupled"),
    ("segregated", "segregated"),
)


def _extracted(props: Optional[SimProperties], key: str) -> Optional[str]:
    """Look up a key in the macro's `convergence` section. An empty value means
    'read succeeded, nothing to report' and counts as absent."""
    if props is None:
        return None
    group = props.get("convergence")
    if group is None:
        return None
    value = group.get(key)
    return value.strip() if value and value.strip() else None


def _field(props: Optional[SimProperties], key: str,
           derived: Optional[str] = None) -> MetadataField:
    value = _extracted(props, key)
    if value:
        return MetadataField(value, Provenance.EXTRACTED)
    if derived:
        return MetadataField(derived, Provenance.DERIVED)
    return _ABSENT


def _model_text(props: Optional[SimProperties]) -> str:
    """Every continuum's enabled-models list, lowercased and concatenated."""
    if props is None:
        return ""
    parts = [
        value
        for group in props.groups
        if group.section == "continuum"
        for key, value in group.entries
        if key == "models"
    ]
    return " ; ".join(parts).lower()


def _match(text: str, keywords: tuple[tuple[str, str], ...]) -> Optional[str]:
    for needle, result in keywords:
        if needle in text:
            return result
    return None


def _int(props: Optional[SimProperties], section: str, key: str) -> Optional[int]:
    if props is None:
        return None
    group = props.get(section)
    if group is None:
        return None
    raw = group.get(key)
    if not raw:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def read_metadata(props: Optional[SimProperties]) -> RunMetadata:
    """Build a RunMetadata from cached sim properties.

    Regime and solver type fall back to the continuum model list, which names
    "Steady"/"Implicit Unsteady" and "Segregated Flow"/"Coupled Flow" — reliable
    enough to branch the whole analysis on."""
    models = _model_text(props)
    sample_count = _extracted(props, "auto_norm_sample_count")
    try:
        auto_norm = int(sample_count) if sample_count else 5
    except ValueError:
        auto_norm = 5
    return RunMetadata(
        solver_regime=_field(props, "solver_regime", _match(models, _REGIME_KEYWORDS)),
        solver_type=_field(props, "solver_type", _match(models, _SOLVER_TYPE_KEYWORDS)),
        precision=_field(props, "precision"),
        residual_normalization=_field(props, "residual_normalization"),
        auto_norm_sample_count=auto_norm,
        cell_count=_int(props, "mesh", "cell_count"),
        n_iterations=_int(props, "solution", "iteration"),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convergence_metadata.py -q`
Expected: PASS, 9 passed.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/starpost/core/convergence/ tests/test_convergence_metadata.py
git add src/starpost/core/convergence/metadata.py tests/test_convergence_metadata.py
git commit -m "feat: resolve convergence run metadata with provenance

Regime and solver type derive from the continuum model list; precision
and residual normalization stay absent until the macro supplies them,
rather than being guessed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Signal preparation (`signals.py`)

Integrity checks, restart segmentation, monitor and equation classification, and trailing-window selection. Everything that has to happen before any estimator sees an array.

**Files:**
- Create: `src/starpost/core/convergence/signals.py`
- Test: `tests/test_convergence_signals.py`

**Interfaces:**
- Consumes: `models.EquationClass` (Task 2), `stats.Decorrelation` (Task 1).
- Produces:
  - `Segment(x: np.ndarray, y: np.ndarray, start: int)` — frozen dataclass
  - `integrity_error(x, y) -> str | None` — `None` means the series is usable
  - `has_non_finite(y) -> bool`
  - `split_segments(x, y) -> list[Segment]`
  - `final_segment(x, y) -> tuple[Segment, int]` — the segment plus the segment count
  - `restart_suspected(y, kappa: float) -> bool`
  - `window_bounds(n: int, config, d_n: float | None = None) -> tuple[int, int, bool]` — `(start, end, adequate)`
  - `equation_class(name: str) -> EquationClass`
  - `MonitorSignal(name: str, plot: str, x: np.ndarray, y: np.ndarray)` — frozen dataclass
  - `collect_signals(result, classification: dict) -> tuple[list[MonitorSignal], list[MonitorSignal]]` — `(residual_series, qoi_series)`

- [ ] **Step 1: Write the failing test**

Create `tests/test_convergence_signals.py`:

```python
"""Preconditioning: integrity, restart segmentation, classification, windows."""
import numpy as np
import pytest

from starpost.core.convergence.config import ConvergenceConfig
from starpost.core.convergence.models import EquationClass
from starpost.core.convergence.signals import (
    collect_signals,
    equation_class,
    final_segment,
    has_non_finite,
    integrity_error,
    restart_suspected,
    split_segments,
    window_bounds,
)
from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, SimResult

CLASSIFICATION = {
    "residual_keywords": ["residual", "residuals"],
    "force_keywords": ["force", "drag", "lift", "moment", "cd", "cl"],
}


def test_empty_and_too_short_series_are_rejected():
    assert integrity_error(np.array([]), np.array([])) is not None
    assert integrity_error(np.array([0.0]), np.array([1.0])) is not None


def test_a_clean_series_has_no_integrity_error():
    x = np.arange(10, dtype=float)
    assert integrity_error(x, x * 2) is None


def test_mismatched_lengths_are_rejected():
    assert integrity_error(np.arange(5.0), np.arange(4.0)) is not None


def test_non_finite_values_are_detected():
    assert has_non_finite(np.array([1.0, 2.0, np.nan])) is True
    assert has_non_finite(np.array([1.0, np.inf])) is True
    assert has_non_finite(np.array([1.0, 2.0])) is False


def test_a_monotonic_series_is_one_segment():
    x = np.arange(100, dtype=float)
    segments = split_segments(x, x)
    assert len(segments) == 1
    assert segments[0].start == 0


def test_a_restart_resets_the_index_and_starts_a_new_segment():
    """V10: an index reset is the reliable restart signature. Analysis runs on
    the final segment only, and no fit ever spans the boundary."""
    x = np.concatenate([np.arange(500.0), np.arange(500.0)])
    y = np.concatenate([np.full(500, 1.0), np.full(500, 2.0)])
    segments = split_segments(x, y)
    assert len(segments) == 2
    assert segments[1].start == 500
    final, count = final_segment(x, y)
    assert count == 2
    assert final.x.size == 500
    assert final.y[0] == 2.0


def test_a_duplicated_index_also_splits():
    x = np.array([0.0, 1.0, 2.0, 2.0, 3.0, 4.0])
    assert len(split_segments(x, np.arange(6.0))) == 2


def test_restart_suspected_fires_on_a_jump_with_no_index_reset():
    """A residual that leaps by more than kappa in one iteration, on a
    monotonic index, is advisory only — we never segment on it."""
    y = np.concatenate([np.full(100, 1e-6), np.full(100, 1e-3)])
    assert restart_suspected(y, kappa=10.0) is True


def test_restart_suspected_is_quiet_on_a_smooth_decay():
    y = 10.0 ** (-np.arange(200) / 50.0)
    assert restart_suspected(y, kappa=10.0) is False


def test_restart_suspected_ignores_non_positive_values():
    """QoI signals cross zero; the log-ratio test only applies to positive
    residual-like data and must not raise on the rest."""
    assert restart_suspected(np.array([1.0, 0.0, -1.0, 2.0]), kappa=10.0) is False


def test_window_is_the_larger_of_the_floor_and_the_record_fraction():
    c = ConvergenceConfig()   # window_min 200, window_fraction 0.2
    start, end, adequate = window_bounds(5000, c)
    assert end == 5000
    assert end - start == 1000          # 0.2 * 5000 beats the 200 floor
    assert adequate is True
    start, end, adequate = window_bounds(600, c)
    assert end - start == 200           # the floor wins
    assert adequate is True


def test_a_short_record_yields_an_inadequate_window():
    """Gate 5 is what stops a short flat stretch inside a long slow oscillation
    reading as convergence, so a record below the floor is flagged."""
    start, end, adequate = window_bounds(120, ConvergenceConfig())
    assert (start, end) == (0, 120)
    assert adequate is False


def test_window_requires_twenty_decorrelation_lengths():
    """N_W >= 20 * D_N, i.e. at least ~20 independent samples."""
    c = ConvergenceConfig()
    _, _, adequate = window_bounds(1000, c, d_n=5.0)     # needs 100, has 200
    assert adequate is True
    _, _, adequate = window_bounds(1000, c, d_n=40.0)    # needs 800, has 200
    assert adequate is False


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Continuity", EquationClass.PRIMARY),
        ("X-momentum", EquationClass.PRIMARY),
        ("Energy", EquationClass.PRIMARY),
        ("Tke", EquationClass.TURBULENCE),
        ("Tdr", EquationClass.TURBULENCE),
        ("Sdr", EquationClass.TURBULENCE),
        ("Turbulent Kinetic Energy", EquationClass.TURBULENCE),
        ("Specific Dissipation Rate", EquationClass.TURBULENCE),
        ("Something Unrecognised", EquationClass.PRIMARY),
    ],
)
def test_equation_class_keywords(name, expected):
    """Unrecognised equations default to primary, which is the conservative
    direction: a turbulence classification weakens the gate."""
    assert equation_class(name) is expected


def test_collect_signals_splits_residuals_from_qois():
    """Residual plots contribute one signal per series (one per equation);
    every other monitor is a QoI candidate."""
    result = SimResult(
        sim_path="/tmp/a.sim",
        plots=[
            MonitorPlot(
                name="Residuals", kind=PlotKind.RESIDUAL,
                series=[
                    PlotSeries(name="Continuity", x=[0.0, 1.0], y=[1.0, 0.1]),
                    PlotSeries(name="Tke", x=[0.0, 1.0], y=[1.0, 0.5]),
                ],
            ),
            MonitorPlot(
                name="Drag Monitor Plot", kind=PlotKind.FORCE,
                series=[PlotSeries(name="Drag", x=[0.0, 1.0], y=[2.0, 2.1])],
            ),
        ],
    )
    residuals, qois = collect_signals(result, CLASSIFICATION)
    assert [s.name for s in residuals] == ["Continuity", "Tke"]
    assert [s.name for s in qois] == ["Drag"]
    assert qois[0].plot == "Drag Monitor Plot"
    assert isinstance(qois[0].y, np.ndarray)


def test_collect_signals_reclassifies_by_keyword_when_kind_is_unset():
    """Cached results predating the classification settings carry kind=OTHER;
    fall back to the same keyword rule the parser uses."""
    result = SimResult(
        sim_path="/tmp/a.sim",
        plots=[MonitorPlot(
            name="Residuals", kind=PlotKind.OTHER,
            series=[PlotSeries(name="Continuity", x=[0.0, 1.0], y=[1.0, 0.1])],
        )],
    )
    residuals, qois = collect_signals(result, CLASSIFICATION)
    assert [s.name for s in residuals] == ["Continuity"]
    assert qois == []


def test_collect_signals_skips_empty_series():
    result = SimResult(
        sim_path="/tmp/a.sim",
        plots=[MonitorPlot(
            name="Drag Monitor Plot", kind=PlotKind.FORCE,
            series=[PlotSeries(name="Drag", x=[], y=[])],
        )],
    )
    assert collect_signals(result, CLASSIFICATION) == ([], [])


def test_single_series_residual_plot_uses_the_plot_name_when_series_is_unnamed():
    result = SimResult(
        sim_path="/tmp/a.sim",
        plots=[MonitorPlot(
            name="Continuity Residual", kind=PlotKind.RESIDUAL,
            series=[PlotSeries(name="", x=[0.0, 1.0], y=[1.0, 0.1])],
        )],
    )
    residuals, _ = collect_signals(result, CLASSIFICATION)
    assert residuals[0].name == "Continuity Residual"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_convergence_signals.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.core.convergence.signals'`

- [ ] **Step 3: Implement `signals.py`**

Create `src/starpost/core/convergence/signals.py`:

```python
"""Signal preconditioning, applied in a fixed order and recorded in the output.

1. Integrity        malformed, empty or non-finite input is caught up front.
2. Restart          split at index resets; analyse the final segment only.
3. Spike removal    off by default and not implemented — the robustified band
                    and Theil-Sen slope already resist spikes where it matters,
                    and silently smoothing hides real trouble.
4. Resampling       not needed for steady runs: the iteration index is uniform.
5. No smoothing     residual slopes are fitted by regression in log space,
                    which is already a smoother; pre-filtering biases the rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from starpost.core.convergence.models import EquationClass
from starpost.data.models import PlotKind

# Turbulence equations are held to a lower residual threshold and can never
# alone force a NOT_CONVERGED, so they must be recognised by name.
_TURBULENCE_KEYWORDS = (
    "tke", "tdr", "sdr",
    "turbulent kinetic", "dissipation", "turbulent viscosity",
    "omega", "epsilon", "nutilde", "nu tilde",
)


@dataclass(frozen=True)
class Segment:
    """A contiguous stretch of a monitor between restart boundaries."""
    x: np.ndarray
    y: np.ndarray
    start: int


@dataclass(frozen=True)
class MonitorSignal:
    """One analysable series: a residual equation or a QoI monitor."""
    name: str
    plot: str
    x: np.ndarray
    y: np.ndarray


def integrity_error(x: np.ndarray, y: np.ndarray) -> Optional[str]:
    """None when the series is usable, else a human-readable reason."""
    if x.size != y.size:
        return "index and value columns have different lengths"
    if x.size == 0:
        return "series is empty"
    if x.size < 2:
        return "series has fewer than 2 points"
    return None


def has_non_finite(y: np.ndarray) -> bool:
    """Any NaN or +/-Inf. A non-finite value is a hard divergence, not noise."""
    return not bool(np.all(np.isfinite(y)))


def split_segments(x: np.ndarray, y: np.ndarray) -> list[Segment]:
    """Split at restart boundaries.

    The sim gives us no restart indices, but a non-monotonic or duplicated
    iteration index is a reliable restart signature. A restart that continued
    the iteration count monotonically is not detectable here and is covered
    advisorily by ``restart_suspected``."""
    breaks = np.nonzero(np.diff(x) <= 0)[0] + 1
    bounds = [0, *breaks.tolist(), x.size]
    return [
        Segment(x=x[a:b], y=y[a:b], start=a)
        for a, b in zip(bounds[:-1], bounds[1:])
        if b > a
    ]


def final_segment(x: np.ndarray, y: np.ndarray) -> tuple[Segment, int]:
    """The last contiguous segment, plus how many segments there were.

    Earlier segments are retained by the caller for display but never fitted:
    a restart invalidates the auto-normalization baseline, so fitting across
    one produces a meaningless slope."""
    segments = split_segments(x, y)
    return segments[-1], len(segments)


def restart_suspected(y: np.ndarray, kappa: float) -> bool:
    """A single-iteration jump larger than ``kappa``, on a monotonic index.

    Advisory only. Restricted to strictly positive samples, since the test is a
    ratio and QoI signals legitimately cross zero."""
    if y.size < 2:
        return False
    pairs = np.column_stack([y[:-1], y[1:]])
    positive = np.all(pairs > 0, axis=1)
    if not positive.any():
        return False
    ratios = pairs[positive][:, 1] / pairs[positive][:, 0]
    return bool(np.any(ratios > kappa))


def window_bounds(n: int, config, d_n: Optional[float] = None) -> tuple[int, int, bool]:
    """Trailing window (start, end, adequate).

    The window is max(window_min, window_fraction * N). It is adequate when it
    reaches that length *and* holds at least ``lambda_ind`` independent
    samples, i.e. N_W >= lambda_ind * D_N. That second condition is what stops
    a short flat stretch inside a long slow oscillation reading as
    convergence — any rule satisfiable by a handful of accidentally-similar
    consecutive samples fires spuriously."""
    wanted = max(config.window_min, int(round(config.window_fraction * n)))
    length = min(wanted, n)
    adequate = length >= wanted
    if adequate and d_n is not None:
        adequate = length >= config.lambda_ind * d_n
    return n - length, n, adequate


def equation_class(name: str) -> EquationClass:
    """Classify a residual equation. Unrecognised names default to primary,
    the conservative direction — a turbulence classification only ever weakens
    the gate."""
    lowered = name.lower()
    for keyword in _TURBULENCE_KEYWORDS:
        if keyword in lowered:
            return EquationClass.TURBULENCE
    return EquationClass.PRIMARY


def _is_residual(plot, classification: dict) -> bool:
    """Trust the stored kind; fall back to the parser's own keyword rule for
    results cached before classification settings existed."""
    if plot.kind is PlotKind.RESIDUAL:
        return True
    lowered = plot.name.lower()
    return any(
        kw.lower() in lowered for kw in classification.get("residual_keywords", [])
    )


def collect_signals(result, classification: dict
                    ) -> tuple[list[MonitorSignal], list[MonitorSignal]]:
    """Split a SimResult's monitor plots into (residual series, QoI series).

    Each PlotSeries inside a residual plot is one equation. Reports are not
    considered: they are final scalars with no history, so the QoI layer
    necessarily runs on monitor plots."""
    residuals: list[MonitorSignal] = []
    qois: list[MonitorSignal] = []
    for plot in result.plots:
        target = residuals if _is_residual(plot, classification) else qois
        for series in plot.series:
            if not series.y or len(series.x) != len(series.y):
                continue
            target.append(MonitorSignal(
                name=series.name or plot.name,
                plot=plot.name,
                x=np.asarray(series.x, dtype=float),
                y=np.asarray(series.y, dtype=float),
            ))
    return residuals, qois
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convergence_signals.py -q`
Expected: PASS, 20 passed.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/starpost/core/convergence/ tests/test_convergence_signals.py
git add src/starpost/core/convergence/signals.py tests/test_convergence_signals.py
git commit -m "feat: convergence signal preconditioning

Integrity checks, restart segmentation on index resets (V10), advisory
detection of restart-like jumps, equation classification, and the
trailing-window rule including the 20-independent-samples gate.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Residual diagnostics (`residuals.py`)

Layer 1. Decades dropped, log-space decay rate, and the per-equation state ladder. Residuals are a health monitor and a necessary condition — never the verdict.

**Files:**
- Create: `src/starpost/core/convergence/residuals.py`
- Test: `tests/test_convergence_residuals.py`

**Interfaces:**
- Consumes: `stats.ols_fit` (Task 1); `models.ResidualAssessment`, `models.ResidualState`, `models.EquationClass` (Task 2); `signals.equation_class`, `signals.window_bounds`, `signals.has_non_finite` (Task 4).
- Produces: `assess_residual(name: str, y: np.ndarray, config, precision: str | None, auto_norm_sample_count: int = 5) -> ResidualAssessment`

Note the signature takes only `y`: the iteration index is uniform for a steady run, and the caller has already reduced the series to its final segment.

**A deliberate tightening of the published ladder.** As written, rungs 5–7 test `|s| < s_flat` and `s < -s_flat`, which leaves a residual that is *rising* but not sustained-divergent unclassified. This implementation uses `s > -s_flat` for rungs 5 and 6, making the ladder total: anything not decaying and not sustained-divergent is judged on its decades dropped, exactly as a flat residual would be. Record this in the module docstring.

- [ ] **Step 1: Write the failing test**

Create `tests/test_convergence_residuals.py`:

```python
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
    projects a positive, finite iteration count from its current rate.

    (The record length matters: over 1000 iterations at rho = 0.99 the trailing
    window's median already sits ~3.9 decades down, past the target, and the
    correct behaviour there is to decline to project.)"""
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
    """Log-space fitting must survive a zero sample without a warning storm,
    and must not let it derail the classification.

    The zero has to sit *inside* the trailing analysis window (y[800:1000] for
    a 1000-sample record) or the fit never sees it and the test is vacuous."""
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_convergence_residuals.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.core.convergence.residuals'`

- [ ] **Step 3: Implement `residuals.py`**

Create `src/starpost/core/convergence/residuals.py`:

```python
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

_MIN_R2_FOR_PROJECTION = 0.5


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
    tail = y[-config.s_div_window:]
    tail_fit = _log_fit(tail) if tail.size >= config.s_div_window else None
    sustained_growth = bool(tail_fit and tail_fit.slope > config.s_div)

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
    elif slope > -config.s_flat:
        state = ResidualState.STALLED if decades < d_min else ResidualState.PLATEAU_LOW
    else:
        state = ResidualState.CONVERGING

    iterations_to_target: Optional[float] = None
    if (state is ResidualState.CONVERGING and slope < 0
            and r2 >= _MIN_R2_FOR_PROJECTION and r_ref > 0 and r_terminal > 0):
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convergence_residuals.py -q`
Expected: PASS, 15 passed.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/starpost/core/convergence/ tests/test_convergence_residuals.py
git add src/starpost/core/convergence/residuals.py tests/test_convergence_residuals.py
git commit -m "feat: residual health diagnostics (layer 1)

Decades dropped from the auto-normalization reference, log-space decay
rate, and the ordered state ladder distinguishing STALLED from the
healthy PLATEAU_LOW. Turbulence equations get a lower threshold;
the machine-precision rung is skipped when precision is unknown.

Validation cases V7, V8 and V15 covered.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Iterative error estimation (`iterative.py`)

Layer 2. The geometric-progression tail estimate, in the QoI's own physical units.

**Files:**
- Create: `src/starpost/core/convergence/iterative.py`
- Test: `tests/test_convergence_iterative.py`

**Interfaces:**
- Consumes: `stats.ols_fit` (Task 1); `models.IterativeError` (Task 2).
- Produces: `estimate_iterative_error(y_window: np.ndarray, config) -> IterativeError`

- [ ] **Step 1: Write the failing test**

Create `tests/test_convergence_iterative.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_convergence_iterative.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.core.convergence.iterative'`

- [ ] **Step 3: Implement `iterative.py`**

Create `src/starpost/core/convergence/iterative.py`:

```python
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

    # A fit that explains none of the change series is not evidence of slow
    # contraction. For a monitor that has settled to noise the slope is an
    # artifact and rho lands near 1 by chance — measured at 17 of 30 seeds
    # before this guard — and since ASYMPTOTICALLY_STAGNANT is excluded from
    # steady.py's static-monitor escape hatch, that would refuse exactly the
    # monitors that have converged. No structure means nothing to extrapolate.
    if fit.r2 < config.min_fit_r2:
        return _no_estimate(
            f"NO_ESTIMATE: the change series shows no geometric structure "
            f"(fit r^2 = {fit.r2:.3g}, below {config.min_fit_r2}), so there is "
            "no progression to extrapolate",
            rho=rho, sigma=fit.sigma, r2=fit.r2, safety_factor=config.safety_factor,
        )

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convergence_iterative.py -q`
Expected: PASS, 9 passed.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/starpost/core/convergence/ tests/test_convergence_iterative.py
git add src/starpost/core/convergence/iterative.py tests/test_convergence_iterative.py
git commit -m "feat: geometric-progression iterative error estimate (layer 2)

Sums the geometric tail of the per-QoI change series rather than
trusting the last difference, with the 1.25 safety factor and the
fit-scatter inflation that the reference procedure found essential.
Guards for non-contracting, stagnant and data-poor fits.

Validation case V1 covered.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Steady QoI gates (`steady.py`)

Layer 3, and where the verdict actually lives. The reference-scale ladder plus the five-gate test.

**Files:**
- Create: `src/starpost/core/convergence/steady.py`
- Test: `tests/test_convergence_steady.py`

**Interfaces:**
- Consumes: `stats.ols_fit`, `stats.theil_sen_slope`, `stats.mann_kendall`, `stats.decorrelation_factor` (Task 1); `models.MonitorAssessment`, `models.GateResult`, `models.ScaleSource` (Task 2); `signals.window_bounds` (Task 4); `iterative.estimate_iterative_error` (Task 6).
- Produces:
  - `reference_scale(y_full: np.ndarray, y_window: np.ndarray, config, manual: float | None = None) -> tuple[float, ScaleSource]`
  - `assess_monitor(name: str, y: np.ndarray, config, is_primary: bool = False) -> MonitorAssessment`
  - Gate name constants: `GATE_DRIFT = "drift"`, `GATE_BAND = "band"`, `GATE_TWO_HALVES = "two-halves"`, `GATE_ITERATIVE = "iterative error"`, `GATE_WINDOW = "window adequacy"`

**Two corrections to the design document, both required for correctness — record them in the module docstring:**

1. **The margin formula.** The design says `u_j = max(U_iter, projected drift, band/2, two-halves delta)` and `m_j = ε_j / u_j`, while also asserting `m_j >= 1 ⇔ pass`. Those two statements contradict each other, because the gates are tested against *different* limits (the two-halves gate against `ε/2`, the window gate against a sample count, and in the opposite direction). Implement `m_j = min over gates of gate.margin`, with each gate normalising its own margin so `>= 1` means passed. That preserves the stated invariant exactly.

2. **A perfectly static QoI must be able to pass.** A monitor that has stopped moving produces an all-zero change series, so the geometric fit has no support and `estimate_iterative_error` returns `INSUFFICIENT_DATA`. Failing the iterative gate on that would make a fully converged monitor permanently un-passable. When the estimator declines *and* the signal's largest single-iteration change is already within tolerance, the gate passes on that evidence instead. `ASYMPTOTICALLY_STAGNANT` is excluded from this escape hatch — that flag exists precisely to mark a signal whose changes look small while its remaining error is enormous.

- [ ] **Step 1: Write the failing test**

Create `tests/test_convergence_steady.py`:

```python
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
    assert gate(a, GATE_BAND).passed is False


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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_convergence_steady.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.core.convergence.steady'`

- [ ] **Step 3: Implement `steady.py`**

Create `src/starpost/core/convergence/steady.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convergence_steady.py -q`
Expected: PASS, 20 passed.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/starpost/core/convergence/ tests/test_convergence_steady.py
git add src/starpost/core/convergence/steady.py tests/test_convergence_steady.py
git commit -m "feat: steady-state QoI convergence gates (layer 3)

Reference-scale ladder that never defaults to |mean| unconditionally,
plus the five gates: projected drift, robust band, two-halves
consistency, remaining iterative error, and window adequacy in
independent samples. Margins are normalised so min(margin) >= 1 is
exactly 'every gate passed'.

Validation cases V2, V5 and V9 covered.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Verdict roll-up and public entry point (`verdict.py`, `__init__.py`)

Combines the layers into a state, a confidence, a convergence index, a binding constraint, and the reasons list. This is the only module that sees everything.

**Files:**
- Create: `src/starpost/core/convergence/verdict.py`
- Modify: `src/starpost/core/convergence/__init__.py` (currently empty)
- Test: `tests/test_convergence_verdict.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces:
  - `verdict.roll_up(metadata, residuals, monitors, integrity_errors, restart_seen, config) -> tuple[ConvergenceState, list[AdvisoryFlag], float | None, str]`
  - `verdict.confidence_of(metadata, monitors, config) -> tuple[Confidence, str]`
  - `verdict.build_reasons(state, residuals, monitors, flags, config) -> list[Reason]`
  - `starpost.core.convergence.assess(result, config=None, classification=None) -> ConvergenceAssessment` — **the only entry point the GUI uses**

- [ ] **Step 1: Write the failing test**

Create `tests/test_convergence_verdict.py`:

```python
"""Roll-up: state, confidence, convergence index, binding constraint, reasons.
Includes validation case V10 and the end-to-end integration tests."""
import numpy as np
import pytest

from starpost.core.convergence import assess
from starpost.core.convergence.config import ConvergenceConfig, MonitorConfig
from starpost.core.convergence.models import (
    AdvisoryFlag,
    Confidence,
    ConvergenceState,
    Severity,
)
from starpost.data.models import (
    MonitorPlot,
    PlotKind,
    PlotSeries,
    PropertyGroup,
    SimProperties,
    SimResult,
)

CLASSIFICATION = {
    "residual_keywords": ["residual", "residuals"],
    "force_keywords": ["force", "drag", "lift", "moment", "cd", "cl"],
}


def converged_qoi(n: int = 3000, mean: float = 100.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return mean + rng.normal(scale=1e-5, size=n)


def healthy_residual(n: int = 3000) -> np.ndarray:
    return 10.0 ** (-np.arange(n, dtype=float) / 400.0) + 1e-12


def make_result(qoi: np.ndarray, residual: np.ndarray | None = None,
                *, models: str = "Steady; Segregated Flow",
                convergence_rows: list[tuple[str, str]] | None = None,
                qoi_name: str = "Drag") -> SimResult:
    plots = [MonitorPlot(
        name=f"{qoi_name} Monitor Plot", kind=PlotKind.FORCE,
        series=[PlotSeries(name=qoi_name, x=list(map(float, range(qoi.size))),
                           y=qoi.tolist())],
    )]
    if residual is not None:
        plots.append(MonitorPlot(
            name="Residuals", kind=PlotKind.RESIDUAL,
            series=[PlotSeries(name="Continuity",
                               x=list(map(float, range(residual.size))),
                               y=residual.tolist())],
        ))
    groups = [PropertyGroup(section="continuum", name="Physics 1",
                            entries=[("models", models)])]
    if convergence_rows:
        groups.append(PropertyGroup(section="convergence", name="",
                                    entries=convergence_rows))
    return SimResult(sim_path="/tmp/case.sim", plots=plots,
                     properties=SimProperties(groups=groups))


def primary(name: str = "Drag", **kw) -> ConvergenceConfig:
    return ConvergenceConfig(monitors={name: MonitorConfig(is_primary=True, **kw)})


# --- end-to-end states -----------------------------------------------------

def test_a_healthy_settled_run_is_converged():
    result = make_result(converged_qoi(), healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.CONVERGED
    assert a.convergence_index > 1.0
    assert a.confidence is Confidence.HIGH


def test_a_drifting_run_is_slow_drift_and_names_its_binding_constraint():
    n, window = 3000, 600
    eps = ConvergenceConfig().tolerance_fraction * 100.0
    qoi = 100.0 + (4.0 * eps / window) * np.arange(n, dtype=float)
    a = assess(make_result(qoi, healthy_residual()), primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.SLOW_DRIFT
    assert a.convergence_index < 1.0
    assert a.binding_constraint.startswith("Drag: ")
    assert any("drift" in r.message.lower() for r in a.reasons)


def test_a_stalled_residual_outranks_a_settled_qoi():
    """The dangerous case: the QoI looks perfectly converged while the solve is
    stuck. The residual state has to win."""
    stalled = np.concatenate([np.full(50, 10 ** -0.5), np.full(2950, 1e-2)])
    result = make_result(converged_qoi(), stalled,
                         convergence_rows=[("precision", "double")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.STALLED


def test_a_diverging_residual_outranks_everything():
    diverging = 10.0 ** (np.arange(3000, dtype=float) / 200.0)
    a = assess(make_result(converged_qoi(), diverging), primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.DIVERGED


def test_an_unsteady_run_is_refused_not_assessed():
    """Applying steady gates to a URANS record produces a confident wrong
    answer, which is worse than no answer."""
    result = make_result(converged_qoi(), healthy_residual(),
                         models="Implicit Unsteady; Coupled Flow")
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.UNSTEADY_UNSUPPORTED
    assert a.monitors == []
    assert any("unsteady" in r.message.lower() for r in a.reasons)


def test_an_empty_result_fails_integrity():
    a = assess(SimResult(sim_path="/tmp/empty.sim"), ConvergenceConfig(),
               CLASSIFICATION)
    assert a.state is ConvergenceState.INTEGRITY_FAIL


def test_a_healthy_but_unsettled_run_is_converging():
    n = 800
    qoi = 100.0 * (1.0 - np.exp(-np.arange(n) / 300.0))
    a = assess(make_result(qoi, healthy_residual(n)), primary(), CLASSIFICATION)
    assert a.state in (ConvergenceState.CONVERGING, ConvergenceState.SLOW_DRIFT)


def test_machine_precision_residuals_with_passing_gates_give_converged_machine():
    floored = np.concatenate([np.full(50, 1.0), np.full(2950, 1e-14)])
    result = make_result(converged_qoi(), floored,
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert a.state is ConvergenceState.CONVERGED_MACHINE


# --- V10: restarts ---------------------------------------------------------

def test_v10_only_the_final_segment_is_analysed():
    """A restart resets the auto-normalization baseline, so no fit may span the
    boundary. The first segment is drifting hard; the second is settled. The
    verdict must come from the second alone."""
    drifting = 100.0 + np.arange(3000, dtype=float) * 0.5
    settled = converged_qoi(3000)
    qoi = np.concatenate([drifting, settled])
    x = list(map(float, range(3000))) * 2       # the index resets: a restart
    result = SimResult(
        sim_path="/tmp/restart.sim",
        plots=[MonitorPlot(
            name="Drag Monitor Plot", kind=PlotKind.FORCE,
            series=[PlotSeries(name="Drag", x=x, y=qoi.tolist())],
        )],
        properties=SimProperties(groups=[PropertyGroup(
            section="continuum", name="P", entries=[("models", "Steady")])]),
    )
    a = assess(result, primary(), CLASSIFICATION)
    assert a.n_segments == 2
    assert a.monitors[0].n_window == 600        # 0.2 * 3000, not 0.2 * 6000
    assert a.monitors[0].mean == pytest.approx(100.0, rel=1e-3)


# --- confidence ------------------------------------------------------------

def test_missing_metadata_caps_confidence_at_medium_or_low():
    """Data sets extracted before the macro change carry no precision or
    normalization, and must assess at reduced confidence rather than pretending
    to know."""
    a = assess(make_result(converged_qoi(), healthy_residual()), primary(),
               CLASSIFICATION)
    assert a.confidence is Confidence.LOW           # normalization unknown
    assert AdvisoryFlag.PRECISION_UNKNOWN in a.flags
    assert AdvisoryFlag.NORMALIZATION_UNKNOWN in a.flags


def test_no_primary_qoi_gives_low_confidence():
    """A verdict from an inadequate monitor set is worse than no verdict,
    because it manufactures false confidence. The monitor here is deliberately
    not force-like, so the auto-primary rule does not rescue it."""
    result = make_result(converged_qoi(), healthy_residual(),
                         qoi_name="Outlet Pressure",
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, ConvergenceConfig(), CLASSIFICATION)
    assert a.confidence is Confidence.LOW
    assert AdvisoryFlag.INCOMPLETE_EVIDENCE in a.flags
    assert "no primary" in a.confidence_rule.lower()


def test_the_confidence_rule_is_reported():
    a = assess(make_result(converged_qoi(), healthy_residual()), primary(),
               CLASSIFICATION)
    assert a.confidence_rule


def test_incomplete_evidence_alone_does_not_cap_confidence():
    """It is raised unconditionally in phase 1 because the conservation check
    is not implemented; letting it cap confidence would make High unreachable."""
    result = make_result(converged_qoi(), healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert AdvisoryFlag.INCOMPLETE_EVIDENCE in a.flags
    assert a.confidence is Confidence.HIGH


# --- advisory flags --------------------------------------------------------

def test_oscillatory_suspected_when_the_mean_is_steady_but_the_band_is_wide():
    """The reduced limit-cycle check: no drift, wide band. Full
    CONVERGED_OSCILLATORY detection needs a periodogram and is out of scope,
    but the user must not be told this is simply 'not converged'."""
    n = 3000
    # A whole number of periods per half-window, so the two-halves gate is not
    # tripped by a partial cycle rather than by real drift. The period is kept
    # short for a second reason: OLS on a sinusoid has a commensurability
    # artifact that scales with period, and at T=20 over a 600-sample window it
    # spuriously fails the drift gate (0.126 against a 0.1 tolerance), which
    # would stop OSCILLATORY_SUSPECTED firing at all.
    qoi = 100.0 + 2.0 * np.sin(2.0 * np.pi * np.arange(n, dtype=float) / 6.0)
    result = make_result(qoi, healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert AdvisoryFlag.OSCILLATORY_SUSPECTED in a.flags
    assert any("limit cycle" in r.message.lower() for r in a.reasons)


def test_a_short_window_raises_window_too_short():
    a = assess(make_result(converged_qoi(120)), primary(), CLASSIFICATION)
    assert AdvisoryFlag.WINDOW_TOO_SHORT in a.flags


def test_a_residual_jump_without_an_index_reset_is_advisory_only():
    residual = np.concatenate([
        10.0 ** (-np.arange(1500, dtype=float) / 400.0),
        10.0 ** (-np.arange(1500, dtype=float) / 400.0) * 1e3,
    ])
    a = assess(make_result(converged_qoi(3000), residual), primary(),
               CLASSIFICATION)
    assert AdvisoryFlag.RESTART_SUSPECTED in a.flags
    assert a.n_segments == 1        # advisory: we did not segment


# --- reasons ---------------------------------------------------------------

def test_a_failing_run_explains_every_failed_gate():
    n, window = 3000, 600
    eps = ConvergenceConfig().tolerance_fraction * 100.0
    qoi = 100.0 + (4.0 * eps / window) * np.arange(n, dtype=float)
    a = assess(make_result(qoi, healthy_residual()), primary(), CLASSIFICATION)
    errors = [r for r in a.reasons if r.severity is Severity.ERROR]
    assert errors
    assert all(r.suggested_action for r in errors)
    assert any("drift" in r.message.lower() for r in errors)


def test_reasons_are_sorted_most_severe_first():
    n, window = 3000, 600
    eps = ConvergenceConfig().tolerance_fraction * 100.0
    qoi = 100.0 + (4.0 * eps / window) * np.arange(n, dtype=float)
    a = assess(make_result(qoi, healthy_residual()), primary(), CLASSIFICATION)
    order = [Severity.ERROR, Severity.WARNING, Severity.INFO]
    ranks = [order.index(r.severity) for r in a.reasons]
    assert ranks == sorted(ranks)


def test_a_stalled_residual_points_at_the_cell_field_not_more_iterations():
    """A stall is a setup problem — a handful of bad cells holding up an
    RMS-over-cells monitor — so 'run it longer' is the wrong advice."""
    stalled = np.concatenate([np.full(50, 10 ** -0.5), np.full(2950, 1e-2)])
    a = assess(make_result(converged_qoi(), stalled), primary(), CLASSIFICATION)
    action = " ".join(r.suggested_action for r in a.reasons).lower()
    assert "field function" in action
    assert "more iterations" not in action


def test_a_converging_run_estimates_the_extra_iterations_needed():
    n = 900
    qoi = 100.0 * (1.0 - np.exp(-np.arange(n) / 400.0))
    a = assess(make_result(qoi, healthy_residual(n)), primary(), CLASSIFICATION)
    assert any(r.estimated_extra_iterations for r in a.reasons)


def test_a_passing_run_still_reports_what_was_checked():
    """The user must be able to see the monitor set the verdict rests on."""
    result = make_result(converged_qoi(), healthy_residual(),
                         convergence_rows=[("precision", "double"),
                                           ("residual_normalization", "auto")])
    a = assess(result, primary(), CLASSIFICATION)
    assert any(r.severity is Severity.INFO for r in a.reasons)


def test_the_thresholds_used_are_recorded_with_their_provenance():
    a = assess(make_result(converged_qoi()), primary(), CLASSIFICATION)
    assert a.thresholds_used["d_min"] == (3.0, "[S]")


def test_the_package_is_qt_free_and_never_reruns_star_ccm():
    """Two invariants at once: STAR-CCM+ runs once per file and everything
    after is cached, and the analysis core stays importable without a GUI.
    Checked against the sources, not the import graph, because other tests in
    the same process legitimately import PySide6."""
    from pathlib import Path

    import starpost.core.convergence as pkg

    sources = sorted(Path(pkg.__file__).parent.glob("*.py"))
    assert len(sources) >= 9        # every module in the package is covered
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "PySide6" not in text, f"{path.name} imports Qt"
        assert "pyqtgraph" not in text, f"{path.name} imports pyqtgraph"
        assert "starccm_runner" not in text, f"{path.name} reaches for the runner"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_convergence_verdict.py -q`
Expected: FAIL — `ImportError: cannot import name 'assess' from 'starpost.core.convergence'`

- [ ] **Step 3: Implement `verdict.py`**

Create `src/starpost/core/convergence/verdict.py`:

```python
"""Roll-up: combine the layers into one verdict.

Three rules govern this module.

* Residuals are necessary, never sufficient. They can veto (DIVERGED, STALLED)
  but they cannot on their own certify convergence — that lives in the
  engineering quantities.
* Never emit a bare boolean. Every verdict carries its state, the active
  advisory flags, per-monitor margins, the binding constraint, the evidence
  completeness, and the estimated cost of finishing.
* Recommendations are the product. "Not converged" is a diagnosis; "continue
  ~4,100 iterations, or relax the drag tolerance to 0.2% which is already met"
  is help.
"""
from __future__ import annotations

from typing import Optional

from starpost.core.convergence.models import (
    AdvisoryFlag,
    Confidence,
    ConvergenceState,
    EquationClass,
    MonitorAssessment,
    Reason,
    ResidualState,
    RunMetadata,
    Severity,
)
from starpost.core.convergence.steady import (
    GATE_BAND,
    GATE_DRIFT,
    GATE_TWO_HALVES,
    GATE_WINDOW,
)

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def _slopes_disagree(monitor: MonitorAssessment) -> bool:
    """Parametric and robust slopes disagreeing is itself a useful signal, but
    only when the trend is large enough to matter — otherwise two estimates of
    pure noise always 'disagree'."""
    a, b = abs(monitor.ols_slope), abs(monitor.theil_sen_slope)
    largest = max(a, b)
    if largest <= 0:
        return False
    if monitor.n_window * largest <= 0.1 * monitor.tolerance_abs:
        return False
    return abs(a - b) / largest > 0.5


def _gate(monitor: MonitorAssessment, name: str):
    return next(g for g in monitor.gates if g.name == name)


def collect_flags(metadata: RunMetadata, monitors: list[MonitorAssessment],
                  restart_seen: bool, has_primary: bool) -> list[AdvisoryFlag]:
    """Advisory flags. Any of these may attach to any state, including
    CONVERGED — that pairing is often the most important thing to surface."""
    flags: list[AdvisoryFlag] = []
    if not metadata.precision.known:
        flags.append(AdvisoryFlag.PRECISION_UNKNOWN)
    if not metadata.residual_normalization.known:
        flags.append(AdvisoryFlag.NORMALIZATION_UNKNOWN)
    # Phase 1 performs no global-conservation check, so evidence is never
    # complete. Raised unconditionally, and deliberately excluded from the
    # confidence rule, which would otherwise make High unreachable.
    flags.append(AdvisoryFlag.INCOMPLETE_EVIDENCE)
    if restart_seen:
        flags.append(AdvisoryFlag.RESTART_SUSPECTED)
    for monitor in monitors:
        if not _gate(monitor, GATE_WINDOW).passed:
            flags.append(AdvisoryFlag.WINDOW_TOO_SHORT)
        if not monitor.iterative.valid and "ASYMPTOTICALLY_STAGNANT" in monitor.iterative.reason:
            flags.append(AdvisoryFlag.ASYMPTOTICALLY_STAGNANT)
        if _slopes_disagree(monitor):
            flags.append(AdvisoryFlag.TREND_ESTIMATE_UNSTABLE)
        if (_gate(monitor, GATE_DRIFT).passed
                and _gate(monitor, GATE_TWO_HALVES).passed
                and not _gate(monitor, GATE_BAND).passed):
            flags.append(AdvisoryFlag.OSCILLATORY_SUSPECTED)
    if not has_primary:
        flags.append(AdvisoryFlag.INCOMPLETE_EVIDENCE)
    # Preserve first-seen order while removing duplicates.
    return list(dict.fromkeys(flags))


def roll_up(metadata: RunMetadata, residuals, monitors: list[MonitorAssessment],
            integrity_errors: list[str], restart_seen: bool, config
            ) -> tuple[ConvergenceState, list[AdvisoryFlag], Optional[float], str]:
    """Resolve the terminal state, flags, convergence index and binding
    constraint. The state ladder is evaluated in order, first match wins, so a
    residual DIVERGED outranks a QoI CONVERGED."""
    primary_monitors = [m for m in monitors if m.is_primary]
    flags = collect_flags(metadata, monitors, restart_seen, bool(primary_monitors))

    index: Optional[float] = None
    binding = "no primary QoI declared"
    if primary_monitors:
        worst = min(primary_monitors, key=lambda m: m.margin)
        index = worst.margin
        binding = f"{worst.name}: {worst.binding_gate}"

    primary_residuals = [r for r in residuals
                         if r.equation_class is EquationClass.PRIMARY]

    if integrity_errors:
        return ConvergenceState.INTEGRITY_FAIL, flags, index, binding
    if any(r.state is ResidualState.DIVERGING for r in residuals):
        return ConvergenceState.DIVERGED, flags, index, binding
    # Turbulence residuals routinely stall one to two orders above the momentum
    # residuals without harming the QoIs, so only primary-class equations can
    # force a stall verdict.
    if any(r.state is ResidualState.STALLED for r in primary_residuals):
        return ConvergenceState.STALLED, flags, index, binding
    if not primary_monitors:
        return ConvergenceState.CONVERGING, flags, index, binding
    if any(not _gate(m, GATE_DRIFT).passed for m in primary_monitors):
        return ConvergenceState.SLOW_DRIFT, flags, index, binding
    if not all(m.passed for m in primary_monitors):
        return ConvergenceState.CONVERGING, flags, index, binding
    if primary_residuals and all(
            r.state is ResidualState.MACHINE_PRECISION for r in primary_residuals):
        return ConvergenceState.CONVERGED_MACHINE, flags, index, binding
    return ConvergenceState.CONVERGED, flags, index, binding


def confidence_of(metadata: RunMetadata, monitors: list[MonitorAssessment],
                  config) -> tuple[Confidence, str]:
    """High/Medium/Low with the rule that produced it, so the level is
    auditable rather than an opinion."""
    primary = [m for m in monitors if m.is_primary]
    low: list[str] = []
    medium: list[str] = []

    if not primary:
        low.append("no primary QoI declared")
    if not metadata.residual_normalization.known:
        low.append("residual normalization unknown")
    for field, label in (
        (metadata.solver_regime, "solver regime"),
        (metadata.precision, "solver precision"),
    ):
        if not field.known:
            medium.append(f"{label} unknown")

    for monitor in primary:
        if monitor.n_eff < config.n_eff_floor:
            low.append(f"{monitor.name}: only {monitor.n_eff:.0f} effective samples")
        elif monitor.n_eff < config.n_eff_min:
            medium.append(f"{monitor.name}: {monitor.n_eff:.0f} effective samples")
        if monitor.n_window < config.window_min:
            low.append(f"{monitor.name}: window shorter than {config.window_min}")
        if config.marginal_low <= monitor.margin <= config.marginal_high:
            medium.append(f"{monitor.name}: margin {monitor.margin:.2f} is marginal")

    if low:
        return Confidence.LOW, "Low — " + "; ".join(low)
    if medium:
        return Confidence.MEDIUM, "Medium — " + "; ".join(medium)
    return Confidence.HIGH, (
        "High — metadata complete, at least one primary QoI, "
        f"at least {config.n_eff_min:.0f} effective samples, no marginal gate"
    )


def build_reasons(state: ConvergenceState, residuals,
                  monitors: list[MonitorAssessment], flags: list[AdvisoryFlag],
                  config) -> list[Reason]:
    """One entry per failed gate, per marginal pass, and per active flag, plus
    an info line for each passing primary monitor so the user can see the
    evidence the verdict rests on."""
    reasons: list[Reason] = []

    if state is ConvergenceState.UNSTEADY_UNSUPPORTED:
        reasons.append(Reason(
            severity=Severity.ERROR, target="run",
            message=("This is an unsteady run. Its residuals are a per-time-step "
                     "sawtooth and its QoIs are a statistical record, so the "
                     "steady tests would give a confident wrong answer."),
            suggested_action=("Assess unsteady runs manually for now: check that "
                              "the inner iterations drop at least one order per "
                              "time step, and that the QoI record is long enough "
                              "for its time-average to be stationary."),
        ))
        return reasons

    for residual in residuals:
        turbulence = residual.equation_class is EquationClass.TURBULENCE
        if residual.state is ResidualState.DIVERGING:
            reasons.append(Reason(
                severity=Severity.ERROR, target=residual.name,
                message=(f"{residual.name} is diverging: the residual has grown "
                         f"to {residual.r_terminal:.3g} against a reference of "
                         f"{residual.r_ref:.3g}."),
                suggested_action=("Reduce the under-relaxation factors or the "
                                  "Courant number, check the boundary conditions, "
                                  "and inspect the mesh quality where the "
                                  "residual is largest."),
            ))
        elif residual.state is ResidualState.STALLED:
            reasons.append(Reason(
                severity=Severity.WARNING if turbulence else Severity.ERROR,
                target=residual.name,
                message=(f"{residual.name} has plateaued after only "
                         f"{residual.decades_dropped:.1f} decades, short of the "
                         f"{config.d_min:.0f} required."
                         + (" Turbulence residuals stalling above the momentum "
                            "residuals is common and does not on its own mean the "
                            "solution is wrong." if turbulence else "")),
                suggested_action=(
                    "A stall is usually a setup problem rather than a "
                    "run-it-longer problem: the monitor is an RMS over cells, so "
                    "a handful of bad cells can hold it up. Plot the per-cell "
                    "residual field function to localise them."
                ),
            ))
        elif residual.state is ResidualState.CONVERGING:
            reasons.append(Reason(
                severity=Severity.INFO, target=residual.name,
                message=(f"{residual.name} is still converging at "
                         f"{-100 * residual.log_slope:.2f} decades per 100 "
                         f"iterations ({residual.decades_dropped:.1f} decades "
                         "dropped so far)."),
                suggested_action=(
                    "Continue iterating. The projection assumes the current rate "
                    "persists." if residual.iterations_to_target else ""
                ),
                estimated_extra_iterations=(
                    int(residual.iterations_to_target)
                    if residual.iterations_to_target else None
                ),
            ))

    for monitor in monitors:
        severity = Severity.ERROR if monitor.is_primary else Severity.WARNING
        for gate in monitor.gates:
            if gate.passed:
                continue
            reasons.append(Reason(
                severity=severity, target=monitor.name,
                message=(f"{monitor.name} fails the {gate.name} gate: "
                         f"{gate.value:.4g} against a limit of {gate.limit:.4g} "
                         f"({gate.detail})."),
                suggested_action=_action_for(gate.name, monitor, config),
            ))
        marginal = [
            g for g in monitor.gates
            if g.passed and config.marginal_low <= g.margin <= config.marginal_high
        ]
        for gate in marginal:
            reasons.append(Reason(
                severity=Severity.WARNING, target=monitor.name,
                message=(f"{monitor.name} passes the {gate.name} gate only "
                         f"marginally (margin {gate.margin:.2f})."),
                suggested_action="Continue a little longer to build margin.",
            ))
        if monitor.passed and monitor.is_primary:
            reasons.append(Reason(
                severity=Severity.INFO, target=monitor.name,
                message=(f"{monitor.name} passes all five gates with margin "
                         f"{monitor.margin:.2f}. Mean {monitor.mean:.6g}, "
                         f"tolerance {monitor.tolerance_abs:.4g} "
                         f"({monitor.tolerance_fraction:.3%} of a "
                         f"{monitor.scale_source.value} scale of "
                         f"{monitor.reference_scale:.6g})."),
            ))
        if monitor.scale_source.value.startswith("robust"):
            reasons.append(Reason(
                severity=Severity.WARNING, target=monitor.name,
                message=(f"{monitor.name} has a mean too close to zero to use as "
                         "a scale, so the tolerance is set from the record range "
                         "instead."),
                suggested_action=("Supply a physical reference scale for this "
                                  "monitor (for a force, 0.5 * rho * U^2 * A) so "
                                  "the tolerance means what you intend."),
            ))

    for flag, message, action in _FLAG_TEXT:
        if flag in flags:
            reasons.append(Reason(severity=Severity.WARNING, target="run",
                                  message=message, suggested_action=action))

    reasons.sort(key=lambda r: _SEVERITY_ORDER[r.severity])
    return reasons


def _action_for(gate_name: str, monitor: MonitorAssessment, config) -> str:
    if gate_name == GATE_DRIFT:
        return ("The mean is still moving. Continue iterating, or supply a "
                "larger tolerance if this drift is acceptable for your purpose.")
    if gate_name == GATE_BAND:
        return ("The signal oscillates wider than the tolerance. If the mean is "
                "steady this is likely a limit cycle, which a steady solver "
                "models questionably — consider an unsteady run.")
    if gate_name == GATE_TWO_HALVES:
        return ("The two halves of the window disagree, which means slow drift "
                "the band alone would not catch. Continue iterating.")
    if gate_name == GATE_WINDOW:
        return (f"The record supports only {monitor.n_eff:.0f} independent "
                f"samples; at least {config.lambda_ind} are needed. Continue "
                "iterating so the statistics have something to stand on.")
    return ("The remaining iterative error exceeds the tolerance. Continue "
            "iterating; the estimate sums the geometric tail of the change "
            "series, not just the last step.")


_FLAG_TEXT: tuple[tuple[AdvisoryFlag, str, str], ...] = (
    (AdvisoryFlag.OSCILLATORY_SUSPECTED,
     "The mean is not drifting but the band is wide. That is the signature of a "
     "limit cycle, which a steady solver models questionably — it is not the "
     "same thing as a run that has failed to converge.",
     "Consider re-running unsteady. Full limit-cycle confirmation (dominant "
     "period and amplitude) is not implemented yet."),
    (AdvisoryFlag.PRECISION_UNKNOWN,
     "The solver's arithmetic precision was not captured, so the "
     "machine-precision verdict is suppressed rather than guessed. A "
     "single-precision run judged against a double-precision floor would read "
     "as permanently stalled.",
     "Re-extract this data set to capture the precision."),
    (AdvisoryFlag.NORMALIZATION_UNKNOWN,
     "The residual normalization mode was not captured, so residual statements "
     "are limited to decades dropped and no absolute residual level is applied.",
     "Re-extract this data set to capture the normalization mode."),
    (AdvisoryFlag.INCOMPLETE_EVIDENCE,
     "No global conservation check was performed: mass and energy imbalance are "
     "among the few absolute checks available and are the ones most likely to "
     "expose a wrong-but-converged-looking solution.",
     "Check the mass and energy imbalance reports manually."),
    (AdvisoryFlag.RESTART_SUSPECTED,
     "A residual jumped sharply without the iteration index resetting, which "
     "looks like a restart. No segmentation was applied.",
     "Check whether this run was restarted; if so the analysis may span a "
     "boundary it should not."),
    (AdvisoryFlag.WINDOW_TOO_SHORT,
     "The trailing window is too short to support the statistics. A short flat "
     "stretch inside a long slow oscillation reads as convergence to any rule "
     "that does not check this.",
     "Continue iterating."),
    (AdvisoryFlag.TREND_ESTIMATE_UNSTABLE,
     "The least-squares and robust trend estimates disagree substantially, so "
     "the drift figure is not dependable.",
     "Inspect the monitor history for spikes or a change in behaviour."),
    (AdvisoryFlag.ASYMPTOTICALLY_STAGNANT,
     "The change series is contracting so slowly that the extrapolated "
     "remaining error is enormous and the fit is untrustworthy.",
     "More iterations at this rate will not help. Revisit the solver settings."),
)
```

- [ ] **Step 4: Implement the public entry point**

Replace the contents of `src/starpost/core/convergence/__init__.py`:

```python
"""Convergence assessment for solved STAR-CCM+ simulations.

Phase 1 covers steady runs. It answers three of the five questions behind
"is it converged?": is the solve healthy, has the iteration stopped changing
the solution, and have the engineering quantities stopped changing. Unsteady
runs are detected and refused rather than assessed with steady tests, and the
global-conservation check is declared missing rather than skipped silently.

Reads cached SimResult data only — this never re-runs STAR-CCM+.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from starpost.core.convergence.config import ConvergenceConfig
from starpost.core.convergence.metadata import read_metadata
from starpost.core.convergence.models import (
    Confidence,
    ConvergenceAssessment,
    ConvergenceState,
    MonitorAssessment,
    ResidualAssessment,
)
from starpost.core.convergence.residuals import assess_residual
from starpost.core.convergence.signals import (
    collect_signals,
    final_segment,
    integrity_error,
    restart_suspected,
)
from starpost.core.convergence.steady import assess_monitor
from starpost.core.convergence.verdict import build_reasons, confidence_of, roll_up

__all__ = ["assess", "ConvergenceConfig"]

_DEFAULT_CLASSIFICATION = {
    "residual_keywords": ["residual", "residuals"],
    "force_keywords": ["force", "drag", "lift", "moment", "cd", "cl"],
}


def _auto_primary(name: str, plot: str, classification: dict) -> bool:
    """Force-like monitors are primary by default: they are the engineering
    deliverable in the overwhelming majority of cases, and a verdict with no
    primary QoI is not a verdict."""
    haystack = f"{name} {plot}".lower()
    return any(kw.lower() in haystack
               for kw in classification.get("force_keywords", []))


def assess(result, config: Optional[ConvergenceConfig] = None,
           classification: Optional[dict] = None) -> ConvergenceAssessment:
    """Assess one SimResult. The only public entry point of this package."""
    config = config or ConvergenceConfig()
    classification = classification or _DEFAULT_CLASSIFICATION

    metadata = read_metadata(result.properties)
    residual_signals, qoi_signals = collect_signals(result, classification)

    def finish(state, residuals, monitors, integrity_errors, restart_seen,
               segments) -> ConvergenceAssessment:
        if state is ConvergenceState.UNSTEADY_UNSUPPORTED:
            flags, index, binding = [], None, "unsteady run: not assessed"
            confidence, rule = Confidence.LOW, "Low — unsteady runs are not assessed"
        else:
            state, flags, index, binding = roll_up(
                metadata, residuals, monitors, integrity_errors, restart_seen, config
            )
            confidence, rule = confidence_of(metadata, monitors, config)
        return ConvergenceAssessment(
            sim_path=result.sim_path,
            sim_name=result.sim_name,
            metadata=metadata,
            state=state,
            confidence=confidence,
            confidence_rule=rule,
            convergence_index=index,
            binding_constraint=binding,
            flags=flags,
            residuals=residuals,
            monitors=monitors,
            reasons=build_reasons(state, residuals, monitors, flags, config),
            thresholds_used=config.as_dict(),
            n_segments=segments,
        )

    if metadata.is_unsteady:
        return finish(ConvergenceState.UNSTEADY_UNSUPPORTED, [], [], [], False, 1)

    if not residual_signals and not qoi_signals:
        return finish(ConvergenceState.INTEGRITY_FAIL, [], [],
                      ["no monitor histories were found in this data set"],
                      False, 1)

    integrity_errors: list[str] = []
    restart_seen = False
    segments = 1

    residuals: list[ResidualAssessment] = []
    for signal in residual_signals:
        error = integrity_error(signal.x, signal.y)
        if error:
            integrity_errors.append(f"{signal.name}: {error}")
            continue
        segment, count = final_segment(signal.x, signal.y)
        segments = max(segments, count)
        if count == 1 and restart_suspected(segment.y, config.kappa_div):
            restart_seen = True
        residuals.append(assess_residual(
            signal.name, segment.y, config,
            precision=metadata.precision.value,
            auto_norm_sample_count=metadata.auto_norm_sample_count,
        ))

    monitors: list[MonitorAssessment] = []
    for signal in qoi_signals:
        error = integrity_error(signal.x, signal.y)
        if error:
            integrity_errors.append(f"{signal.name}: {error}")
            continue
        if not np.all(np.isfinite(signal.y)):
            integrity_errors.append(f"{signal.name}: contains non-finite values")
            continue
        segment, count = final_segment(signal.x, signal.y)
        segments = max(segments, count)
        override = config.monitors.get(signal.name)
        is_primary = (
            override.is_primary if override is not None
            else _auto_primary(signal.name, signal.plot, classification)
        )
        monitors.append(assess_monitor(signal.name, segment.y, config,
                                       is_primary=is_primary))

    return finish(ConvergenceState.CONVERGING, residuals, monitors,
                  integrity_errors, restart_seen, segments)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convergence_verdict.py -q`
Expected: PASS, 24 passed.

- [ ] **Step 6: Run the whole convergence suite together**

Run: `python -m pytest tests/test_convergence_stats.py tests/test_convergence_config.py tests/test_convergence_metadata.py tests/test_convergence_signals.py tests/test_convergence_residuals.py tests/test_convergence_iterative.py tests/test_convergence_steady.py tests/test_convergence_verdict.py -q`
Expected: PASS, all green.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src/starpost/core/convergence/ tests/
git add src/starpost/core/convergence/verdict.py src/starpost/core/convergence/__init__.py tests/test_convergence_verdict.py
git commit -m "feat: convergence verdict roll-up and public assess() entry point

Resolves the terminal state ladder, advisory flags, convergence index,
binding constraint, auditable High/Medium/Low confidence, and the
reasons list with suggested actions. Residuals can veto but never
certify; unsteady runs are refused rather than mis-assessed.

Validation case V10 covered.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Extract convergence metadata in the macro

Add a `convergence` properties section so newly-extracted data sets carry the metadata that cannot be derived. `_parse_properties` passes unknown sections through untouched, so no parser change is needed.

**Files:**
- Modify: `src/starpost/macros/extract_all.java.j2` — the header comment (line 13), the `exportProperties` dispatch (after `propsCriteria(sim, w);`, line 293), and a new `propsConvergence` method plus helpers after `propsCriteria`
- Test: `tests/test_properties.py` (append)

**Interfaces:**
- Consumes: nothing in Python.
- Produces: a `convergence` section with `name` = `""` and these keys, in this order — `solver_regime`, `solver_type`, `precision`, `residual_normalization`, `auto_norm_sample_count`, `time_step`, `inner_iterations_per_timestep`, `courant_number`. This is exactly the contract `metadata.read_metadata` (Task 3) reads.

**Ground rules, from the file's existing conventions:**
- Everything outside `star.common` is reached **only** by reflection (`invokeQuiet`). A compile-time reference to a class a release has moved kills the whole extraction, and `test_extract_macro_no_compile_time_refs_outside_common` enforces it.
- Getters only. Nothing may compute, initialize or mutate.
- Per-section `try`/`catch`, so a failure loses this section's rows and nothing else.
- **An unresolvable value is written as an empty string, never as a guess.** `read_metadata` treats empty as absent, which is what makes the tool degrade honestly instead of misclassifying a single-precision run.

**Marked `[V]`:** the accessor names below reflect documented behaviour as generally understood, but residual bookkeeping differs between the segregated and coupled solvers and has changed between releases. Verify each against the local Simcenter STAR-CCM+ 2506 help. The reflective probes are written so that a wrong name yields an empty value rather than an exception.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_properties.py`:

```python
def test_extract_macro_exports_convergence_metadata(tmp_path):
    """The convergence assessment needs metadata it cannot derive: build
    precision, residual normalization mode, and the unsteady parameters phase 2
    will want. Anything unresolvable is written empty, never guessed."""
    text = render_macro(Path("/out"), tmp_path).read_text()
    assert "propsConvergence" in text
    assert '"convergence"' in text
    for key in ("solver_regime", "solver_type", "precision",
                "residual_normalization", "auto_norm_sample_count",
                "time_step", "inner_iterations_per_timestep", "courant_number"):
        assert f'"{key}"' in text, key
    # Reached reflectively: these accessors move between releases.
    assert '"isDoublePrecision"' in text
    assert '"getMonitorManager"' in text
    assert '"getNormalizeOption"' in text


def test_convergence_section_is_dispatched(tmp_path):
    text = render_macro(Path("/out"), tmp_path).read_text()
    assert "propsConvergence(sim, w);" in text


def test_convergence_metadata_round_trips_into_run_metadata(tmp_path):
    """The macro's CSV contract and the reader must agree. This is the seam
    where a renamed key would silently degrade every verdict to Low."""
    from starpost.core.convergence.metadata import read_metadata
    from starpost.core.convergence.models import Provenance
    from starpost.core.result_parser import _parse_properties

    csv = tmp_path / "case__properties.csv"
    csv.write_text(
        "section,name,key,value\n"
        "convergence,,solver_regime,steady\n"
        "convergence,,solver_type,segregated\n"
        "convergence,,precision,double\n"
        "convergence,,residual_normalization,auto\n"
        "convergence,,auto_norm_sample_count,5\n"
        "convergence,,time_step,\n"
        "convergence,,inner_iterations_per_timestep,\n"
        "convergence,,courant_number,\n",
        encoding="utf-8",
    )
    meta = read_metadata(_parse_properties(csv))
    assert meta.precision.value == "double"
    assert meta.precision.provenance is Provenance.EXTRACTED
    assert meta.residual_normalization.value == "auto"
    assert meta.solver_regime.value == "steady"
    assert meta.auto_norm_sample_count == 5
    assert meta.is_unsteady is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_properties.py -q -k convergence`
Expected: FAIL — `assert 'propsConvergence' in text`

- [ ] **Step 3: Update the macro header comment**

In `src/starpost/macros/extract_all.java.j2`, change the properties line of the output list (line 13-14) from:

```
//   <simname>__properties.csv       section,name,key,value (sim metadata:
//                                   solution state, mesh, regions, physics...)
```

to:

```
//   <simname>__properties.csv       section,name,key,value (sim metadata:
//                                   solution state, mesh, regions, physics,
//                                   convergence metadata...)
```

- [ ] **Step 4: Dispatch the new section**

In `exportProperties`, immediately after the `propsCriteria(sim, w);` line, add:

```java
            propsConvergence(sim, w);
```

- [ ] **Step 5: Add `propsConvergence` and its helpers**

Insert immediately after the closing brace of `propsCriteria`:

```java
    // Convergence metadata: what the convergence assessment needs and cannot
    // derive from anything else already extracted. Every accessor here is
    // reached reflectively — the names differ between the segregated and
    // coupled solvers and have changed between releases, and a compile-time
    // reference to a moved class would kill the whole extraction.
    //
    // An unresolvable value is written as an empty string. The reader treats
    // empty as "unknown" and suppresses the verdict that depends on it, which
    // is the point: a guessed precision permanently misclassifies every
    // single-precision run as stalled.
    private void propsConvergence(Simulation sim, PrintWriter w) {
        try {
            String models = allModelNames(sim).toLowerCase();
            prow(w, "convergence", "", "solver_regime", regimeOf(models));
            prow(w, "convergence", "", "solver_type", solverTypeOf(models));
            prow(w, "convergence", "", "precision", precisionOf(sim));
            prow(w, "convergence", "", "residual_normalization",
                residualNormalizationOf(sim));
            prow(w, "convergence", "", "auto_norm_sample_count",
                autoNormSampleCountOf(sim));
            prow(w, "convergence", "", "time_step", timeStepOf(sim));
            prow(w, "convergence", "", "inner_iterations_per_timestep",
                innerIterationsOf(sim));
            prow(w, "convergence", "", "courant_number", courantOf(sim));
        } catch (Exception e) {
            sim.println("starpost: properties: convergence section failed: "
                + e.getMessage());
        }
    }

    // The class simple name of an object, or "" — used to recognise solver and
    // criterion types without naming their packages at compile time.
    private String simpleName(Object o) {
        return o == null ? "" : o.getClass().getSimpleName();
    }

    // Every enabled model's presentation name and class name, concatenated.
    private String allModelNames(Simulation sim) {
        StringBuilder sb = new StringBuilder();
        try {
            for (Object o : sim.getContinuumManager().getObjects()) {
                Object models = invokeQuiet(o, "getModelManager");
                Object objects = invokeQuiet(models, "getObjects");
                if (!(objects instanceof java.util.Collection)) {
                    continue;
                }
                for (Object m : (java.util.Collection<?>) objects) {
                    String n = presentationName(m);
                    sb.append(n == null ? "" : n).append(" ");
                    sb.append(simpleName(m)).append(" ");
                }
            }
        } catch (Exception e) {
            return sb.toString();
        }
        return sb.toString();
    }

    // Longest first: "implicit unsteady" must win over a bare "unsteady".
    private String regimeOf(String models) {
        if (models.contains("harmonic balance")
            || models.contains("harmonicbalance")) {
            return "harmonic_balance";
        }
        if (models.contains("implicit unsteady")
            || models.contains("implicitunsteady")) {
            return "implicit_unsteady";
        }
        if (models.contains("explicit unsteady")
            || models.contains("explicitunsteady")) {
            return "explicit_unsteady";
        }
        if (models.contains("steady")) {
            return "steady";
        }
        return "";
    }

    private String solverTypeOf(String models) {
        if (models.contains("coupled")) {
            return "coupled";
        }
        if (models.contains("segregated")) {
            return "segregated";
        }
        return "";
    }

    // [V] Verify against the local 2506 help. If the accessor is absent this
    // returns "", and the tool reports PRECISION_UNKNOWN rather than guessing.
    private String precisionOf(Simulation sim) {
        Object dp = invokeQuiet(sim, "isDoublePrecision");
        if (dp instanceof Boolean) {
            return ((Boolean) dp).booleanValue() ? "double" : "single";
        }
        return "";
    }

    // Residual monitors carry the normalization mode. Reported sim-wide only
    // when every residual monitor agrees; a mixed set is written empty, since
    // a single mode is what the reader's contract promises.
    private String residualNormalizationOf(Simulation sim) {
        String found = null;
        try {
            Object mgr = invokeQuiet(sim, "getMonitorManager");
            Object objects = invokeQuiet(mgr, "getObjects");
            if (!(objects instanceof java.util.Collection)) {
                return "";
            }
            for (Object m : (java.util.Collection<?>) objects) {
                if (!simpleName(m).contains("Residual")) {
                    continue;
                }
                Object opt = invokeQuiet(m, "getNormalizeOption");
                if (opt == null) {
                    opt = invokeQuiet(m, "getNormalizationOption");
                }
                String v = presentationName(invokeQuiet(opt, "getSelectedElement"));
                if (v == null) {
                    Object sel = invokeQuiet(opt, "getSelected");
                    v = (sel == null) ? null : String.valueOf(sel);
                }
                if (v == null || v.length() == 0) {
                    continue;
                }
                v = v.toLowerCase();
                if (found == null) {
                    found = v;
                } else if (!found.equals(v)) {
                    return "";
                }
            }
        } catch (Exception e) {
            return "";
        }
        return found == null ? "" : found;
    }

    // [V] The auto-normalization reference window (STAR-CCM+ default 5).
    private String autoNormSampleCountOf(Simulation sim) {
        try {
            Object mgr = invokeQuiet(sim, "getMonitorManager");
            Object objects = invokeQuiet(mgr, "getObjects");
            if (!(objects instanceof java.util.Collection)) {
                return "";
            }
            for (Object m : (java.util.Collection<?>) objects) {
                if (!simpleName(m).contains("Residual")) {
                    continue;
                }
                Object n = invokeQuiet(m, "getNormalizationIterations");
                if (n == null) {
                    n = invokeQuiet(m, "getNumberOfSamples");
                }
                if (n != null) {
                    return String.valueOf(n);
                }
            }
        } catch (Exception e) {
            return "";
        }
        return "";
    }

    // [V] Phase 2 metadata: captured now so data sets extracted from here on
    // are already usable when the unsteady layer lands.
    private String timeStepOf(Simulation sim) {
        return solverScalar(sim, "Unsteady", "getTimeStep");
    }

    private String courantOf(Simulation sim) {
        return solverScalar(sim, "Coupled", "getCourantNumber");
    }

    // The value of a scalar property on the first solver whose class name
    // contains `marker`. Scalar properties wrap their number, so unwrap via
    // getRawValue/getValue where those exist.
    private String solverScalar(Simulation sim, String marker, String getter) {
        try {
            for (Object s : sim.getSolverManager().getObjects()) {
                if (!simpleName(s).contains(marker)) {
                    continue;
                }
                Object prop = invokeQuiet(s, getter);
                if (prop == null) {
                    continue;
                }
                Object raw = invokeQuiet(prop, "getRawValue");
                if (raw == null) {
                    raw = invokeQuiet(prop, "getValue");
                }
                return String.valueOf(raw == null ? prop : raw);
            }
        } catch (Exception e) {
            return "";
        }
        return "";
    }

    private String innerIterationsOf(Simulation sim) {
        try {
            for (Object c
                    : sim.getSolverStoppingCriterionManager().getObjects()) {
                if (!simpleName(c).contains("InnerIteration")) {
                    continue;
                }
                Object n = invokeQuiet(c, "getMaximumNumberInnerIterations");
                if (n == null) {
                    n = invokeQuiet(c, "getMaximumNumberSteps");
                }
                if (n != null) {
                    return String.valueOf(n);
                }
            }
        } catch (Exception e) {
            return "";
        }
        return "";
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_properties.py -q`
Expected: PASS — including the existing `test_extract_macro_braces_balance` and `test_extract_macro_no_compile_time_refs_outside_common`, which now also cover the new code.

- [ ] **Step 7: Commit**

```bash
git add src/starpost/macros/extract_all.java.j2 tests/test_properties.py
git commit -m "feat: extract convergence metadata in the extraction macro

A new convergence properties section carrying solver regime and type,
build precision, residual normalization mode and sample count, and the
unsteady parameters phase 2 will need. Every accessor is reflective and
every unresolvable value is written empty, so the assessment degrades
honestly rather than guessing a precision it cannot see.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: The Convergence window (`convergence_dialog.py`)

Non-modal three-pane window. Follows `PartSearchDialog` exactly: keep a reference on the main window, raise and refresh on re-trigger.

**Files:**
- Create: `src/starpost/gui/views/convergence_dialog.py`
- Test: `tests/test_convergence_gui.py`

**Interfaces:**
- Consumes: `starpost.core.convergence.assess`, `ConvergenceConfig`, `MonitorConfig`, `TOLERANCE_PRESETS`; `ResultStore`.
- Produces: `ConvergenceDialog(store, settings, parent=None)` with the public method `reload()` (re-snapshot the store and re-assess), matching `PartSearchDialog.reload`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_convergence_gui.py`:

```python
"""The Convergence window. Runs offscreen; touches no real config or cache."""
import numpy as np
import pytest

import starpost.utils.paths as paths
from starpost.core.settings import Settings
from starpost.data.models import (
    MonitorPlot,
    PlotKind,
    PlotSeries,
    PropertyGroup,
    SimProperties,
    SimResult,
)
from starpost.data.store import ResultStore


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        paths.platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path / "config")
    )
    monkeypatch.setattr(
        paths.platformdirs, "user_cache_dir", lambda *a, **k: str(tmp_path / "cache")
    )


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def make_result(path: str, drifting: bool = False) -> SimResult:
    n = 3000
    rng = np.random.default_rng(0)
    if drifting:
        qoi = 100.0 + 0.01 * np.arange(n, dtype=float)
    else:
        qoi = 100.0 + rng.normal(scale=1e-5, size=n)
    residual = 10.0 ** (-np.arange(n, dtype=float) / 400.0) + 1e-12
    x = list(map(float, range(n)))
    return SimResult(
        sim_path=path,
        plots=[
            MonitorPlot(name="Drag Monitor Plot", kind=PlotKind.FORCE,
                        series=[PlotSeries(name="Drag", x=x, y=qoi.tolist())]),
            MonitorPlot(name="Residuals", kind=PlotKind.RESIDUAL,
                        series=[PlotSeries(name="Continuity", x=x,
                                           y=residual.tolist())]),
        ],
        properties=SimProperties(groups=[
            PropertyGroup(section="continuum", name="P",
                          entries=[("models", "Steady; Segregated Flow")]),
            PropertyGroup(section="convergence", name="", entries=[
                ("precision", "double"), ("residual_normalization", "auto")]),
        ]),
    )


def store_with(*results) -> ResultStore:
    store = ResultStore()
    for r in results:
        store.put(r)
    return store


def open_dialog(store):
    from starpost.gui.views.convergence_dialog import ConvergenceDialog

    return ConvergenceDialog(store, Settings())


def test_the_window_assesses_every_loaded_data_set(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim"),
                                 make_result("/tmp/b.sim", drifting=True)))
    assert dlg._summary.rowCount() == 2
    dlg.close()


def test_a_settled_run_reads_as_converged(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert "CONVERGED" in dlg._verdict_state.text()
    assert "High" in dlg._verdict_confidence.text()
    dlg.close()


def test_a_drifting_run_names_its_binding_constraint(app):
    dlg = open_dialog(store_with(make_result("/tmp/b.sim", drifting=True)))
    assert "SLOW_DRIFT" in dlg._verdict_state.text()
    assert "Drag" in dlg._verdict_binding.text()
    dlg.close()


def test_the_reasons_list_is_populated_and_severity_ordered(app):
    dlg = open_dialog(store_with(make_result("/tmp/b.sim", drifting=True)))
    assert dlg._reasons.topLevelItemCount() > 0
    severities = [dlg._reasons.topLevelItem(i).text(0)
                  for i in range(dlg._reasons.topLevelItemCount())]
    order = ["error", "warning", "info"]
    assert [order.index(s) for s in severities] == sorted(
        order.index(s) for s in severities
    )
    dlg.close()


def test_the_detail_tabs_show_residuals_and_gates(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert dlg._residual_table.rowCount() == 1        # Continuity
    assert dlg._gate_table.rowCount() == 1            # Drag
    dlg.close()


def test_force_monitors_are_ticked_primary_by_default(app):
    """A verdict with no primary QoI is not a verdict, so force-like monitors
    are primary out of the box."""
    from PySide6.QtCore import Qt

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert dlg._monitor_table.item(0, 0).checkState() == Qt.CheckState.Checked
    dlg.close()


def test_unticking_the_only_primary_monitor_drops_confidence_to_low(app):
    from PySide6.QtCore import Qt

    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    dlg._monitor_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert "Low" in dlg._verdict_confidence.text()
    dlg.close()


def test_changing_the_tolerance_preset_re_runs_the_assessment(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    before = dlg._assessments["/tmp/a.sim"].monitors[0].tolerance_abs
    dlg._preset.setCurrentText("Production (0.05%)")
    after = dlg._assessments["/tmp/a.sim"].monitors[0].tolerance_abs
    assert after == pytest.approx(before / 2.0, rel=1e-6)
    dlg.close()


def test_selecting_a_summary_row_switches_the_detail_panes(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim"),
                                 make_result("/tmp/b.sim", drifting=True)))
    dlg._summary.selectRow(1)
    assert "SLOW_DRIFT" in dlg._verdict_state.text()
    dlg._summary.selectRow(0)
    assert "CONVERGED" in dlg._verdict_state.text()
    dlg.close()


def test_an_empty_store_shows_a_placeholder_and_does_not_raise(app):
    dlg = open_dialog(ResultStore())
    assert dlg._summary.rowCount() == 0
    assert "No data sets" in dlg._verdict_state.text()
    dlg.close()


def test_reload_re_snapshots_the_store(app):
    store = store_with(make_result("/tmp/a.sim"))
    dlg = open_dialog(store)
    store.put(make_result("/tmp/b.sim", drifting=True))
    dlg.reload()
    assert dlg._summary.rowCount() == 2
    dlg.close()


def test_failed_extractions_are_skipped(app):
    store = store_with(make_result("/tmp/a.sim"),
                       SimResult(sim_path="/tmp/bad.sim", error="extraction failed"))
    dlg = open_dialog(store)
    assert dlg._summary.rowCount() == 1
    dlg.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_convergence_gui.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.gui.views.convergence_dialog'`

- [ ] **Step 3: Implement `convergence_dialog.py`**

Create `src/starpost/gui/views/convergence_dialog.py`:

```python
"""'Convergence' window: does this simulation look converged, and if not, why?

Reads cached monitor histories only — it never re-runs STAR-CCM+. Every loaded
data set is assessed independently and summarised in one table; selecting a row
drives the verdict card, the reasons list, and the detail tables.

The window deliberately never shows a bare percentage. The headline is a state
plus an auditable High/Medium/Low confidence, a convergence index, and the
binding constraint — the one string that tells the engineer what to do next.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from starpost.core.convergence import assess
from starpost.core.convergence.config import (
    TOLERANCE_PRESETS,
    ConvergenceConfig,
    MonitorConfig,
)

_PRESET_LABELS = {
    "Screening (0.1%)": TOLERANCE_PRESETS["screening"],
    "Production (0.05%)": TOLERANCE_PRESETS["production"],
}

_MONITOR_COLUMNS = ("Primary", "Monitor", "Tolerance", "Reference scale")
_SUMMARY_COLUMNS = ("Data set", "State", "Confidence", "Index", "Binding constraint")
_RESIDUAL_COLUMNS = ("Equation", "Decades", "Slope", "rho", "r^2", "State",
                     "Iterations to target")
_GATE_COLUMNS = ("Monitor", "Primary", "Mean", "Band (95%)", "Drift", "U_iter",
                 "N_eff", "Margin", "Binding gate")


class ConvergenceDialog(QDialog):
    """Non-modal convergence assessment over every loaded data set."""

    def __init__(self, store, settings, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = settings
        self._assessments: dict = {}
        self._results: list = []
        # Per-sim monitor configuration, kept across re-assessments so editing
        # a tolerance does not reset the primary ticks.
        self._monitor_configs: dict[str, dict[str, MonitorConfig]] = {}
        self._updating = False

        self.setWindowTitle("Convergence")
        self.resize(1100, 700)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self.reload()

    # --- construction ---------------------------------------------------

    def _build_left(self) -> QWidget:
        self._preset = QComboBox()
        self._preset.addItems([*_PRESET_LABELS, "Custom"])
        self._preset.currentTextChanged.connect(self._on_preset_changed)

        self._custom = QDoubleSpinBox()
        self._custom.setDecimals(4)
        self._custom.setRange(0.0001, 100.0)
        self._custom.setSuffix(" %")
        self._custom.setValue(TOLERANCE_PRESETS["screening"] * 100.0)
        self._custom.setEnabled(False)
        self._custom.valueChanged.connect(lambda _v: self._reassess())

        form = QFormLayout()
        form.addRow("Tolerance", self._preset)
        form.addRow("Custom", self._custom)

        self._summary = QTableWidget(0, len(_SUMMARY_COLUMNS))
        self._summary.setHorizontalHeaderLabels(_SUMMARY_COLUMNS)
        self._summary.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._summary.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._summary.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._summary.verticalHeader().setVisible(False)
        self._summary.itemSelectionChanged.connect(self._on_selection_changed)

        self._monitor_table = QTableWidget(0, len(_MONITOR_COLUMNS))
        self._monitor_table.setHorizontalHeaderLabels(_MONITOR_COLUMNS)
        self._monitor_table.verticalHeader().setVisible(False)
        self._monitor_table.itemChanged.connect(self._on_monitor_edited)

        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addLayout(form)
        box.addWidget(QLabel("Data sets"))
        box.addWidget(self._summary)
        box.addWidget(QLabel("Monitors"))
        box.addWidget(self._monitor_table)
        return panel

    def _build_right(self) -> QWidget:
        self._verdict_state = QLabel("No data sets loaded")
        self._verdict_state.setObjectName("convergenceState")
        self._verdict_confidence = QLabel()
        self._verdict_index = QLabel()
        self._verdict_binding = QLabel()
        self._verdict_binding.setWordWrap(True)
        self._verdict_flags = QLabel()
        self._verdict_flags.setWordWrap(True)

        card = QFrame()
        card.setObjectName("convergenceVerdict")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_box = QVBoxLayout(card)
        card_box.addWidget(self._verdict_state)
        row = QHBoxLayout()
        row.addWidget(self._verdict_confidence)
        row.addWidget(self._verdict_index)
        row.addStretch(1)
        card_box.addLayout(row)
        card_box.addWidget(self._verdict_binding)
        card_box.addWidget(self._verdict_flags)

        self._reasons = QTreeWidget()
        self._reasons.setHeaderLabels(("Severity", "Target", "Reason"))
        self._reasons.setRootIsDecorated(True)

        self._residual_table = QTableWidget(0, len(_RESIDUAL_COLUMNS))
        self._residual_table.setHorizontalHeaderLabels(_RESIDUAL_COLUMNS)
        self._residual_table.verticalHeader().setVisible(False)

        self._gate_table = QTableWidget(0, len(_GATE_COLUMNS))
        self._gate_table.setHorizontalHeaderLabels(_GATE_COLUMNS)
        self._gate_table.verticalHeader().setVisible(False)

        tabs = QTabWidget()
        tabs.addTab(self._reasons, "Reasons")
        tabs.addTab(self._residual_table, "Residuals")
        tabs.addTab(self._gate_table, "QoI gates")

        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addWidget(card)
        box.addWidget(tabs)
        for table in (self._summary, self._monitor_table,
                      self._residual_table, self._gate_table):
            table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
        return panel

    # --- data -----------------------------------------------------------

    def reload(self) -> None:
        """Re-snapshot the store and re-assess. Called on reopen so a re-raised
        window reflects the current workspace."""
        self._results = [r for r in self._store.all()
                         if r.error is None and r.plots]
        self._reassess()

    def _tolerance_fraction(self) -> float:
        label = self._preset.currentText()
        if label in _PRESET_LABELS:
            return _PRESET_LABELS[label]
        return self._custom.value() / 100.0

    def _config_for(self, result) -> ConvergenceConfig:
        return ConvergenceConfig(
            tolerance_fraction=self._tolerance_fraction(),
            monitors=dict(self._monitor_configs.get(result.sim_path, {})),
        )

    def _reassess(self) -> None:
        classification = self._settings.plot_classification
        self._assessments = {
            r.sim_path: assess(r, self._config_for(r), classification)
            for r in self._results
        }
        # Seed the per-monitor configuration from the first assessment, so the
        # auto-primary choice is visible and editable rather than implicit.
        for path, assessment in self._assessments.items():
            known = self._monitor_configs.setdefault(path, {})
            for monitor in assessment.monitors:
                known.setdefault(monitor.name, MonitorConfig(
                    is_primary=monitor.is_primary,
                    tolerance_fraction=None,
                    reference_scale=None,
                ))
        self._populate_summary()

    # --- population -----------------------------------------------------

    def _populate_summary(self) -> None:
        self._updating = True
        try:
            self._summary.setRowCount(len(self._results))
            for row, result in enumerate(self._results):
                assessment = self._assessments[result.sim_path]
                index = assessment.convergence_index
                cells = (
                    result.sim_name,
                    assessment.state.value,
                    assessment.confidence.value,
                    "—" if index is None else f"{index:.2f}",
                    assessment.binding_constraint,
                )
                for column, text in enumerate(cells):
                    self._summary.setItem(row, column, QTableWidgetItem(text))
        finally:
            self._updating = False
        if self._results:
            self._summary.selectRow(0)
        else:
            self._show_placeholder()

    def _show_placeholder(self) -> None:
        self._verdict_state.setText("No data sets loaded")
        for label in (self._verdict_confidence, self._verdict_index,
                      self._verdict_binding, self._verdict_flags):
            label.setText("")
        self._reasons.clear()
        self._monitor_table.setRowCount(0)
        self._residual_table.setRowCount(0)
        self._gate_table.setRowCount(0)

    def _current(self):
        row = self._summary.currentRow()
        if row < 0 or row >= len(self._results):
            return None
        return self._assessments[self._results[row].sim_path]

    def _on_selection_changed(self) -> None:
        if self._updating:
            return
        assessment = self._current()
        if assessment is None:
            return
        self._populate_verdict(assessment)
        self._populate_reasons(assessment)
        self._populate_monitors(assessment)
        self._populate_residuals(assessment)
        self._populate_gates(assessment)

    def _populate_verdict(self, assessment) -> None:
        self._verdict_state.setText(assessment.state.value)
        self._verdict_confidence.setText(f"Confidence: {assessment.confidence.value}")
        index = assessment.convergence_index
        self._verdict_index.setText(
            "Convergence index: —" if index is None
            else f"Convergence index: {index:.2f}"
        )
        self._verdict_binding.setText(f"Binding: {assessment.binding_constraint}")
        self._verdict_flags.setText(
            "  ".join(flag.value for flag in assessment.flags)
        )

    def _populate_reasons(self, assessment) -> None:
        self._reasons.clear()
        for reason in assessment.reasons:
            item = QTreeWidgetItem(
                (reason.severity.value, reason.target, reason.message)
            )
            if reason.suggested_action:
                item.addChild(QTreeWidgetItem(("", "", reason.suggested_action)))
            if reason.estimated_extra_iterations:
                item.addChild(QTreeWidgetItem((
                    "", "",
                    f"Estimated ~{reason.estimated_extra_iterations:,} more "
                    "iterations (assumes the current rate persists)",
                )))
            self._reasons.addTopLevelItem(item)

    def _populate_monitors(self, assessment) -> None:
        self._updating = True
        try:
            self._monitor_table.setRowCount(len(assessment.monitors))
            for row, monitor in enumerate(assessment.monitors):
                # Column 0 is the checkbox alone; column 1 carries the name,
                # which _on_monitor_edited reads back to identify the row.
                primary = QTableWidgetItem("")
                primary.setFlags(primary.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                primary.setCheckState(
                    Qt.CheckState.Checked if monitor.is_primary
                    else Qt.CheckState.Unchecked
                )
                self._monitor_table.setItem(row, 0, primary)
                self._monitor_table.setItem(row, 1, self._readonly(monitor.name))
                self._monitor_table.setItem(
                    row, 2, QTableWidgetItem(f"{monitor.tolerance_fraction * 100:.4g}")
                )
                self._monitor_table.setItem(
                    row, 3,
                    QTableWidgetItem(f"{monitor.reference_scale:.6g} "
                                     f"({monitor.scale_source.value})")
                )
        finally:
            self._updating = False

    def _readonly(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _populate_residuals(self, assessment) -> None:
        self._residual_table.setRowCount(len(assessment.residuals))
        for row, residual in enumerate(assessment.residuals):
            projection = residual.iterations_to_target
            cells = (
                residual.name,
                f"{residual.decades_dropped:.2f}",
                f"{residual.log_slope:.3g}",
                f"{residual.decay_factor:.5f}",
                f"{residual.fit_r2:.3f}",
                residual.state.value,
                "—" if projection is None else f"{projection:,.0f}",
            )
            for column, text in enumerate(cells):
                self._residual_table.setItem(row, column, self._readonly(text))

    def _populate_gates(self, assessment) -> None:
        self._gate_table.setRowCount(len(assessment.monitors))
        for row, monitor in enumerate(assessment.monitors):
            u_iter = monitor.iterative.u_iter
            cells = (
                monitor.name,
                "yes" if monitor.is_primary else "no",
                f"{monitor.mean:.6g}",
                f"{monitor.band_p95:.4g}",
                f"{monitor.projected_drift:.4g}",
                "—" if u_iter is None else f"{u_iter:.4g}",
                f"{monitor.n_eff:.0f}",
                f"{monitor.margin:.2f}",
                monitor.binding_gate,
            )
            for column, text in enumerate(cells):
                self._gate_table.setItem(row, column, self._readonly(text))

    # --- editing --------------------------------------------------------

    def _on_preset_changed(self, label: str) -> None:
        self._custom.setEnabled(label == "Custom")
        self._reassess()

    def _on_monitor_edited(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        row = self._summary.currentRow()
        if row < 0 or row >= len(self._results):
            return
        path = self._results[row].sim_path
        configs = self._monitor_configs.setdefault(path, {})
        name_item = self._monitor_table.item(item.row(), 1)
        if name_item is None:
            return
        name = name_item.text()
        existing = configs.get(name, MonitorConfig())
        if item.column() == 0:
            existing.is_primary = item.checkState() == Qt.CheckState.Checked
        elif item.column() == 2:
            existing.tolerance_fraction = _parse_percent(item.text())
        elif item.column() == 3:
            existing.reference_scale = _parse_float(item.text())
        configs[name] = existing
        self._reassess()
        self._select_path(path)

    def _select_path(self, path: str) -> None:
        for row, result in enumerate(self._results):
            if result.sim_path == path:
                self._summary.selectRow(row)
                return


def _parse_percent(text: str) -> Optional[float]:
    value = _parse_float(text)
    return None if value is None else value / 100.0


def _parse_float(text: str) -> Optional[float]:
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_convergence_gui.py -q`
Expected: PASS, 12 passed.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/starpost/gui/views/convergence_dialog.py tests/test_convergence_gui.py
git add src/starpost/gui/views/convergence_dialog.py tests/test_convergence_gui.py
git commit -m "feat: Convergence window

Non-modal three-pane window: tolerance preset and per-monitor
configuration on the left, verdict card plus Reasons/Residuals/QoI-gates
tabs on the right, with a summary row per loaded data set. Shows a state,
an auditable confidence and the binding constraint rather than a bare
percentage.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Wire the menu entry and document the feature

**Files:**
- Modify: `src/starpost/gui/main_window.py:546-557` (the Tools menu block) and add the `_open_convergence` slot beside `_open_part_search` (around line 1561)
- Modify: `CHANGELOG.md`
- Test: `tests/test_main_window.py` (append)

**Interfaces:**
- Consumes: `ConvergenceDialog(store, settings, parent)` (Task 10).
- Produces: `MainWindow._open_convergence()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main_window.py`:

```python
def test_tools_menu_offers_convergence(app):
    """Convergence is wired up now, so it must be enabled and must not carry
    the '(coming soon)' placeholder suffix. Correlation still does."""
    win = mw.MainWindow(Settings())
    labels = {a.text(): a for a in win._tools_menu.actions()}
    assert "Convergence" in labels
    assert labels["Convergence"].isEnabled()
    assert "Correlation (coming soon)" in labels
    assert not labels["Correlation (coming soon)"].isEnabled()
    win.close()


def test_opening_convergence_twice_reuses_one_window(app):
    """Same lifecycle as Part Search: keep a reference so the window is not
    garbage-collected, and raise-and-refresh rather than spawning a duplicate."""
    win = mw.MainWindow(Settings())
    win._open_convergence()
    first = win._convergence_dialog
    win._open_convergence()
    assert win._convergence_dialog is first
    first.close()
    win.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -q -k convergence`
Expected: FAIL — `assert 'Convergence' in labels`

- [ ] **Step 3: Wire the menu entry**

In `src/starpost/gui/main_window.py`, replace this block:

```python
        # Not built yet: tagged "(coming soon)" and disabled, so they read as
        # grayed-out placeholders rather than entries that do nothing when
        # clicked. Drop the suffix and the setDisabled call when wiring them up.
        for name in ("Correlation", "Convergence"):
            act = tools_menu.addAction(f"{name} (coming soon)")
            act.setDisabled(True)
            act.setToolTip(f"{name} is not available yet")
        part_search_act = tools_menu.addAction("Part Search")
        part_search_act.triggered.connect(self._open_part_search)
```

with:

```python
        # Not built yet: tagged "(coming soon)" and disabled, so they read as
        # grayed-out placeholders rather than entries that do nothing when
        # clicked. Drop the suffix and the setDisabled call when wiring them up.
        for name in ("Correlation",):
            act = tools_menu.addAction(f"{name} (coming soon)")
            act.setDisabled(True)
            act.setToolTip(f"{name} is not available yet")
        convergence_act = tools_menu.addAction("Convergence")
        convergence_act.setToolTip(
            "Assess whether the loaded data sets have converged"
        )
        convergence_act.triggered.connect(self._open_convergence)
        part_search_act = tools_menu.addAction("Part Search")
        part_search_act.triggered.connect(self._open_part_search)
```

- [ ] **Step 4: Add the slot**

Insert immediately before `def _open_part_search(self) -> None:`:

```python
    def _open_convergence(self) -> None:
        """Tools → Convergence: open the non-modal window that assesses whether
        the loaded data sets have converged. Reads cached monitor histories
        only — it never re-runs STAR-CCM+.

        The import is local: the convergence package pulls in numpy-heavy
        analysis modules that have no business on the startup path."""
        from starpost.gui.views.convergence_dialog import ConvergenceDialog

        dlg = getattr(self, "_convergence_dialog", None)
        if dlg is not None:
            try:
                visible = dlg.isVisible()
            except RuntimeError:
                visible = False  # underlying C++ dialog already deleted
            if visible:
                dlg.reload()
                dlg.raise_()
                dlg.activateWindow()
                return
            dlg.deleteLater()  # drop the stale hidden instance before replacing
        self._convergence_dialog = ConvergenceDialog(self.store, self.settings, self)
        self._convergence_dialog.show()
```

`MainWindow` stores its settings as `self.settings` (assigned at `main_window.py:89`), so `ConvergenceDialog(self.store, self.settings, self)` is correct as written.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -q`
Expected: PASS.

- [ ] **Step 6: Add the changelog entry**

At the top of the unreleased section of `CHANGELOG.md`, matching the file's existing style:

```markdown
- **Convergence tool.** Tools → Convergence assesses whether each loaded data
  set has converged, for steady runs. It reports a state (converged, still
  converging, stalled, diverged, drifting), a High/Medium/Low confidence with
  the rule that produced it, a convergence index, the binding constraint, and a
  list of reasons with suggested actions and an estimate of the iterations
  remaining. Residual health, remaining iterative error and the engineering
  quantities are assessed separately and then combined. Unsteady runs are
  reported as not yet supported rather than assessed with steady tests.
  Reads cached data only — no STAR-CCM+ re-run.
- Extraction now records solver precision, residual normalization mode, and the
  unsteady solver parameters. Data sets extracted before this update are still
  assessed, at reduced confidence; re-extract for the full verdict.
```

- [ ] **Step 7: Run the whole suite**

Run: `python scripts/run_tests.py`
Expected: all files pass. This is the first full-suite run; the per-file runs above do not catch cross-file interference.

- [ ] **Step 8: Lint and commit**

```bash
ruff check .
git add src/starpost/gui/main_window.py tests/test_main_window.py CHANGELOG.md
git commit -m "feat: wire up Tools -> Convergence

Replaces the disabled '(coming soon)' placeholder with the real window,
following the Part Search lifecycle. The convergence package is imported
lazily inside the slot to keep it off the startup path.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Verify in the real application**

The assessment is numeric and fully covered by headless tests, but the monitor-configuration table involves checkbox and editable cells, which the repo's experience says QTest can misrepresent. Use the project's `verify` skill to launch StarPost on a real display, open Tools → Convergence with at least one data set loaded, and confirm by screenshot that:

1. the summary table lists the loaded data sets with a state and a confidence,
2. ticking and unticking the Primary checkbox re-runs the assessment and changes the verdict,
3. editing a tolerance cell is accepted and takes effect,
4. the Reasons tab expands to show the suggested action.

---

## Notes for the implementer

**What phase 1 deliberately does not do**, so it is not mistaken for an oversight:

- No unsteady/statistical layer: no MSER or other initial-transient detection, no autocorrelation-corrected confidence intervals on a time-average, no slow-drift guard for statistically stationary records, no periodic-content correction. Unsteady runs are refused.
- No global conservation check, so `INCOMPLETE_EVIDENCE` is always raised.
- No `NONPHYSICAL` sentinel bounds, which would need user-supplied physical limits.
- No full limit-cycle confirmation: the signature is detected and flagged, but there is no periodogram and no `CONVERGED_OSCILLATORY` state.
- No export of the assessment, and no evidence plot with the trailing window shaded.
- Restart detection is heuristic: index resets are caught reliably, a restart that continued the iteration count monotonically is not.

**The highest-value future extension**, worth recording: emitting a field-max change of the primary solution variables from the extraction macro — one scalar per iteration — would make the validated L-infinity iterative-error estimator available instead of the scalar analogue used here. It is a small addition to the existing macro-based export path and materially upgrades the rigour of the whole module.
