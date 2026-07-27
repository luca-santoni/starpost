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
    "mk_trend_z": "[D]",
    "mk_trend_departure_fraction": "[D]",
    "iterative_unbounded_confidence_fraction": "[D]",
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
