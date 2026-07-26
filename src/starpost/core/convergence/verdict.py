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
                  restart_seen: bool) -> list[AdvisoryFlag]:
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
    # Preserve first-seen order while removing duplicates.
    return list(dict.fromkeys(flags))


def roll_up(metadata: RunMetadata, residuals, monitors: list[MonitorAssessment],
            integrity_errors: list[str], restart_seen: bool, config
            ) -> tuple[ConvergenceState, list[AdvisoryFlag], Optional[float], str]:
    """Resolve the terminal state, flags, convergence index and binding
    constraint. The state ladder is evaluated in order, first match wins, so a
    residual DIVERGED outranks a QoI CONVERGED."""
    primary_monitors = [m for m in monitors if m.is_primary]
    flags = collect_flags(metadata, monitors, restart_seen)

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
        elif residual.state is ResidualState.MACHINE_PRECISION:
            reasons.append(Reason(
                severity=Severity.INFO, target=residual.name,
                message=(f"{residual.name} has reached the arithmetic floor of "
                         f"the solver's precision after {residual.decades_dropped:.1f} "
                         "decades dropped, the best available terminal state."),
            ))
        elif residual.state is ResidualState.PLATEAU_LOW:
            reasons.append(Reason(
                severity=Severity.INFO, target=residual.name,
                message=(f"{residual.name} has plateaued after "
                         f"{residual.decades_dropped:.1f} decades dropped, a "
                         "sufficient drop and the normal healthy ending."),
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
