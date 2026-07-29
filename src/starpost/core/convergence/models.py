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
    AUTOCORRELATION_UNRELIABLE = "AUTOCORRELATION_UNRELIABLE"
    NO_RESIDUAL_EVIDENCE = "NO_RESIDUAL_EVIDENCE"
    ITERATIVE_ERROR_UNBOUNDED = "ITERATIVE_ERROR_UNBOUNDED"


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

    @property
    def is_steady(self) -> bool:
        """Positive recognition, not a default. A regime that is absent, or
        recognised but not literally 'steady' (harmonic balance included —
        ``is_unsteady`` does not catch it, since the token does not end with
        'unsteady'), must be refused rather than silently assessed with
        steady gates."""
        return self.solver_regime.known and self.solver_regime.value == "steady"


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
    record_departure: float
    mann_kendall_z: float
    mann_kendall_p: float
    two_halves_delta: float
    two_halves_t: float
    d_n: float
    n_eff: float
    tau0_over_n: float
    iterative: IterativeError
    gates: list[GateResult] = field(default_factory=list)
    # The minimum GateResult.margin among gates whose tested *value* is
    # finite. A gate with an infinite value (currently only the iterative
    # gate, when the static-monitor escape hatch is denied — see steady.py)
    # would otherwise reduce to a margin of exactly 0.0 through _margin's
    # reciprocal and erase every other gate's genuine measurement. That gate
    # still has passed=False, so ``passed`` below is unaffected — only the
    # magnitude reported here changes. None only in the practically
    # unreachable case where every one of the monitor's gates is unbounded.
    margin: Optional[float] = None
    binding_gate: str = ""
    # Which route the window-adequacy gate took. True means the direct
    # n_eff >= lambda_ind requirement was not met but the relaxed route was:
    # the confidence half-width on the mean is well inside tolerance and the
    # preceding equal-length block agrees (see steady.py). That matters beyond
    # display, because n_eff is only ever a *proxy* for "is the mean known to
    # within tolerance", and the relaxed route measures that quantity
    # directly — so confidence_of must not turn round and cap the verdict on
    # the proxy the gate has just set aside.
    window_relaxed: bool = False

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
    # How many primary monitors have at least one gate that could not be
    # bounded at all (an infinite gate value, e.g. the iterative gate
    # whenever the static-monitor escape hatch is denied — see
    # verdict.roll_up). Such a gate no longer collapses the monitor's own
    # margin to a false 0.0 (see MonitorAssessment.margin), so this count is
    # what still lets a caller say a monitor's remaining error could not be
    # measured, even though convergence_index carries a real number.
    unbounded_primary_count: int = 0
    flags: list[AdvisoryFlag] = field(default_factory=list)
    residuals: list[ResidualAssessment] = field(default_factory=list)
    monitors: list[MonitorAssessment] = field(default_factory=list)
    reasons: list[Reason] = field(default_factory=list)
    thresholds_used: dict = field(default_factory=dict)
    n_segments: int = 1
    # Per-series messages for signals that failed an integrity check and were
    # dropped (whole series or, after C1, its final segment). Also surfaced as
    # warning Reasons; kept here too so a caller can inspect them directly
    # without re-parsing the reasons list.
    integrity_errors: list[str] = field(default_factory=list)
