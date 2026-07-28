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
    "s_div_min_r2": "[D]",
    "s_div_level_ratio": "[D]",
    "s_div_baseline_window": "[D]",
    "s_conv_min_r2": "[D]",
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
    "mk_trend_z": "[D]",
    "mk_trend_departure_fraction": "[D]",
    "iterative_unbounded_confidence_fraction": "[D]",
    "window_relax_ci_fraction": "[D]",
}


@dataclass
class MonitorConfig:
    """Per-monitor overrides. ``reference_scale`` set means rung 1 of the
    scale ladder (user-supplied physical scale) is taken.

    ``is_primary`` is deliberately tri-state: ``True``/``False`` pin the
    choice, ``None`` means "no opinion" and leaves it to
    ``_select_auto_primary``. A plain ``bool`` cannot express that, and the
    difference is not academic — the mere existence of a MonitorConfig would
    then read as an explicit override, so editing one monitor's *tolerance*
    would silently freeze its primary state too, and the auto rule could
    never run for it again."""
    is_primary: Optional[bool] = None
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
    s_div_min_r2: float = 0.5      # the s_div_window tail fit must explain at least
                                   # this much variance before its slope is trusted
                                   # to declare divergence — an oscillating residual
                                   # makes the last-window slope pure phase, not
                                   # trend (r^2 near 0), and divergence is the
                                   # strongest claim this module makes. Same class
                                   # of check as min_fit_r2 below, applied to the
                                   # divergence rung instead of the iterative-error
                                   # one.
    s_div_level_ratio: float = 3.0
                                   # The r^2 floor alone is not enough: one
                                   # half-cycle of an oscillation is itself
                                   # well fitted by a straight line, so its
                                   # r^2 lands wherever the phase puts it,
                                   # and a real STAR-CCM+ run measured tail
                                   # fits above s_div_min_r2 on oscillating
                                   # (not diverging) residuals. An
                                   # oscillation returns to its prior level;
                                   # a divergence does not. This is the
                                   # ratio median(tail window) /
                                   # median(preceding baseline window) must
                                   # exceed before the slope+r^2 rungs above
                                   # are trusted to declare divergence.
                                   # Measured across 18 real oscillating
                                   # residual series (three production
                                   # runs, all truncation phases): worst
                                   # case 1.71. Measured on synthetic
                                   # divergences: 201 at 0.1 decades/iter,
                                   # 10.6 at 0.05 decades/iter. 3.0 sits
                                   # comfortably above the former and well
                                   # below the latter. Growth slower than
                                   # ~0.02 decades/iteration is genuinely
                                   # indistinguishable from oscillation
                                   # within one s_div_window (it has only
                                   # grown ~2x in 50 iterations) — that is
                                   # left to the kappa_div rung as the
                                   # growth continues, not chased here.
    s_div_baseline_window: int = 200
                                   # Size of the block immediately
                                   # preceding the s_div_window tail that
                                   # s_div_level_ratio is measured against.
    s_conv_min_r2: float = 0.5     # the main-window fit must explain at least
                                   # this much variance before a negative
                                   # slope is trusted to declare CONVERGING —
                                   # same class of check as s_div_min_r2 above,
                                   # applied to the opposite end of the
                                   # ladder. A real STAR-CCM+ run had four
                                   # equations behaving identically (all flat
                                   # inside their own noise, r^2 <= 0.02) with
                                   # three landing STALLED and the fourth
                                   # CONVERGING purely because its noise-driven
                                   # slope crossed s_flat by 0.000019 — an
                                   # inconsistency, and a false claim of
                                   # progress ("converging at 0.01 decades per
                                   # 100 iterations") extrapolated from a fit
                                   # explaining 1.9% of the variance. Below
                                   # this floor the fit is not trusted and the
                                   # residual falls through to the same
                                   # STALLED/PLATEAU_LOW split its flat
                                   # siblings use. Shared with
                                   # iterations_to_target's projection gate
                                   # (formerly a private module constant) so
                                   # the state and the projection cannot
                                   # disagree about whether a slope is
                                   # resolved enough to act on. 0.5 was
                                   # checked against a synthetic decay with
                                   # realistic multiplicative log-normal
                                   # noise landing mid-range (r^2 in ~0.58-0.75
                                   # for noise sigma 0.15-0.20 decades): it
                                   # still reads CONVERGING, so the floor does
                                   # not reject a genuinely decaying-but-noisy
                                   # residual, only ones with no resolvable
                                   # trend at all.
    kappa_div: float = 10.0        # residual growth vs reference => diverged
    eps_prec_double: float = 1e-13
    eps_prec_single: float = 1e-6

    # --- iterative error ------------------------------------------------
    safety_factor: float = 1.25
    min_fit_points: int = 20
    rho_stagnant: float = 0.999
    min_fit_r2: float = 0.10       # below this the change series has no
                                   # geometric structure to extrapolate
    mk_trend_z: float = 5.0        # |Mann-Kendall z| above this, on a declined
                                   # iterative fit, denies the static-monitor
                                   # escape hatch: the window still shows a
                                   # statistically resolvable monotonic trend
    mk_trend_departure_fraction: float = 0.25
                                   # the mk_trend_z denial above also requires
                                   # the record-scale departure (trailing
                                   # window mean vs. first-block mean) to be
                                   # at least this fraction of tolerance — z
                                   # alone is a pure significance test with no
                                   # effect size, and a long enough record
                                   # makes a physically irrelevant difference
                                   # significant. Chosen from a sweep at
                                   # n=3000, screening tolerance: it separates
                                   # every creeping case at rho <= 0.99999
                                   # (departure >= 0.271 x eps) from a benign
                                   # small real drift (0.218 x eps) — see
                                   # steady.py's module docstring and
                                   # c3-closure-report.md for the full sweep
                                   # and its acknowledged residual gap.
    iterative_unbounded_confidence_fraction: float = 0.10
                                   # When a primary monitor's iterative
                                   # estimator declines, confidence is capped
                                   # at Medium only if the iterative gate's
                                   # tested quantity (largest single-iteration
                                   # change, or the MK-denial's infinite
                                   # stand-in) exceeds this fraction of the
                                   # monitor's tolerance. The estimator
                                   # declines for any settled monitor with
                                   # ordinary noise — there is no geometric
                                   # structure in white noise to fit — so
                                   # capping unconditionally on decline alone
                                   # made High unreachable for essentially
                                   # every well-converged run. A monitor whose
                                   # largest per-iteration change is a tiny
                                   # fraction of tolerance is as converged as
                                   # anything can be; one still moving at an
                                   # appreciable fraction of tolerance is the
                                   # case the missing bound actually matters
                                   # for. See verdict.py's confidence_of.

    # --- QoI gates ------------------------------------------------------
    tolerance_fraction: float = TOLERANCE_PRESETS["screening"]
    window_min: int = 200          # N_W floor, iterations
    window_fraction: float = 0.2   # window is max(window_min, fraction * N)
    gamma: float = 5.0             # mean/sigma separation to use |mean| as scale
    lambda_ind: int = 20           # independent samples required in the window
    window_relax_ci_fraction: float = 0.25
                                   # A safety factor of 4 on the source theory's
                                   # own criterion (t * SEM_eff <= eps). The
                                   # factor is not decoration: at the bare
                                   # criterion (1.0) this route admits a strongly
                                   # autocorrelated record whose mean is known
                                   # only to 87% of tolerance — marginal, not
                                   # settled — while a real well-converged monitor
                                   # sits at 5-11%. 0.25 separates those by more
                                   # than 2x on each side rather than sitting
                                   # against either. An earlier 0.10 was tighter
                                   # than any evidence supported and refused a run
                                   # whose mean was known to 10.5% of tolerance.
                                   # The t-quantile self-limits too: at n_eff = 5,
                                   # t(0.975, 4) is 2.78, so a poorly sampled
                                   # window is penalised automatically.
                                   #
                                   # The n_eff >= lambda_ind requirement is a proxy
                                   # for "is the mean known to within tolerance?" —
                                   # on a very smooth, well-settled monitor,
                                   # smoothness itself is high autocorrelation, so
                                   # the proxy can be unsatisfiable even though the
                                   # quantity it stands in for passes comfortably.
                                   # The window gate also passes when: (1) the
                                   # window meets its length floor; (2) the
                                   # confidence half-width on the mean,
                                   # t(1-alpha/2, nu_eff) * std/sqrt(n_eff) with
                                   # nu_eff = max(n_eff - 1, 1), is no more than
                                   # this fraction of tolerance; and (3) the
                                   # immediately preceding equal-length block's
                                   # mean agrees with the window's mean to within
                                   # tolerance. Condition (3) is what still catches
                                   # a brief flat stretch inside a slow
                                   # oscillation: that case shows a *different*
                                   # mean in the preceding block, where a
                                   # genuinely settled monitor agrees to a small
                                   # fraction of tolerance across the two blocks.
                                   # alpha = 0.05 (the same 95% convention the
                                   # band gate's [97.5, 2.5] percentiles already
                                   # use in this module; there is no separate
                                   # named alpha constant to reuse). Measured on
                                   # a real, well-settled car-aero downforce
                                   # monitor: n_eff = 4.7 against lambda_ind = 20,
                                   # confidence half-width 0.0199 x tolerance,
                                   # preceding-block agreement 0.026 x tolerance
                                   # across 1000 iterations — comfortably inside
                                   # this floor on both counts.
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
