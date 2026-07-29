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

import math
from typing import Optional

from starpost.core.convergence.models import (
    AdvisoryFlag,
    Confidence,
    ConvergenceState,
    EquationClass,
    MonitorAssessment,
    Provenance,
    Reason,
    ResidualState,
    RunMetadata,
    Severity,
)
from starpost.core.convergence.steady import (
    GATE_BAND,
    GATE_DRIFT,
    GATE_ITERATIVE,
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


def _monitor_is_unbounded(monitor: MonitorAssessment) -> bool:
    """Whether any of the monitor's gates tested a non-finite quantity.

    Currently only the iterative gate can be non-finite — its value is
    ``math.inf`` whenever the static-monitor escape hatch is denied (see
    steady.py) — but this is written over every gate rather than assuming
    which one, since steady.py now excludes an infinite-valued gate from the
    monitor's own margin (see MonitorAssessment.margin) precisely so it can
    no longer be found by asking "what is monitor.binding_gate". This is the
    only remaining way roll_up can tell "this monitor has an unmeasured
    gate" apart from "this monitor measured badly"."""
    return any(not math.isfinite(g.value) for g in monitor.gates)


def _margin_sort_key(monitor: MonitorAssessment):
    """Sort key that treats a ``None`` margin (no gate on this monitor could
    be bounded at all — practically unreachable, see MonitorAssessment.margin)
    as worse than any finite margin, so ``min`` can still find the true worst
    monitor without Python raising on ``None < float``."""
    if monitor.margin is None:
        return (0, 0.0)
    return (1, monitor.margin)


def _join_names(names: list[str]) -> str:
    """"a", "a and b", "a, b and c" -- the English list a non-primary
    monitor's rolled-up failed-gate reason names its gates with."""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _series_label(msg: str) -> str:
    """The series-name prefix of an integrity message, formatted
    ``"<series>: <detail>"``. Not every integrity message has that shape —
    the run-level "no monitor histories were found in this data set" message
    has no colon at all — so this falls back to a generic label rather than
    rendering the whole sentence as a bogus series name."""
    name, sep, _ = msg.partition(": ")
    return name if sep else "run"


def collect_flags(metadata: RunMetadata, monitors: list[MonitorAssessment],
                  restart_seen: bool, config) -> list[AdvisoryFlag]:
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
        if monitor.tau0_over_n > config.tau0_over_n_warn:
            flags.append(AdvisoryFlag.AUTOCORRELATION_UNRELIABLE)
        if not monitor.iterative.valid and "ASYMPTOTICALLY_STAGNANT" in monitor.iterative.reason:
            flags.append(AdvisoryFlag.ASYMPTOTICALLY_STAGNANT)
        if monitor.is_primary and not monitor.iterative.valid:
            # Whenever the geometric fit declines — for any reason: no
            # structure, too little data, or genuine stagnation — this
            # module has no numeric bound on the monitor's remaining error.
            # The monitor may still pass (see steady.py's escape hatch), but
            # the verdict must say so rather than silently claiming more
            # certainty than the evidence supports.
            flags.append(AdvisoryFlag.ITERATIVE_ERROR_UNBOUNDED)
        if _slopes_disagree(monitor):
            flags.append(AdvisoryFlag.TREND_ESTIMATE_UNSTABLE)
        if (_gate(monitor, GATE_DRIFT).passed
                and _gate(monitor, GATE_TWO_HALVES).passed
                and not _gate(monitor, GATE_BAND).passed):
            flags.append(AdvisoryFlag.OSCILLATORY_SUSPECTED)
    # Preserve first-seen order while removing duplicates.
    return list(dict.fromkeys(flags))


def roll_up(metadata: RunMetadata, residuals, monitors: list[MonitorAssessment],
            restart_seen: bool, config, residual_evidence_destroyed: bool = False
            ) -> tuple[ConvergenceState, list[AdvisoryFlag], Optional[float], str, int]:
    """Resolve the terminal state, flags, convergence index, binding
    constraint and unbounded-primary-monitor count. The state ladder is
    evaluated in order, first match wins, so a residual DIVERGED outranks a
    QoI CONVERGED.

    The convergence index is the worst primary monitor's margin. Each
    monitor's own margin already excludes any gate whose tested value is
    infinite (see steady.py) — such a gate can no longer erase four
    otherwise-good measurements down to a false 0.0, so the index is a
    straightforward worst-of-margins again. ``unbounded_primary_count`` and
    the ITERATIVE_ERROR_UNBOUNDED flag still tell the user which monitors
    could not have their iterative error bounded (see
    ``_monitor_is_unbounded``); the binding-constraint string adds a short
    "(iterative error unbounded)" caveat when the worst monitor itself is one
    of them. The index is None only in the practically unreachable case
    where the worst monitor has no finite-valued gate at all (see
    ``MonitorAssessment.margin``).

    A series that failed an integrity check is dropped rather than poisoning
    the whole run — the caller has already excluded it from ``residuals``/
    ``monitors`` and turned it into a warning reason. INTEGRITY_FAIL is
    reserved for the case where *nothing* usable survived: no residuals and
    no monitors at all.

    Residuals are necessary, never sufficient (see the module docstring), so
    CONVERGED and CONVERGED_MACHINE both require at least one surviving
    residual *unless residual evidence never existed in the first place*.
    ``residual_evidence_destroyed`` is True only when at least one residual
    series was collected and every one of them was then dropped by an
    integrity check — the caller (``assess``) is the only place that knows
    whether ``residuals`` came out empty because a residual plot never
    existed or because every one that did exist failed preconditioning; a
    data set with no residual monitors at all (a monitor-only portable CSV, a
    deleted Residuals plot, a classification override) has had nothing
    destroyed and is a different situation. Dropping a bad series is meant to
    let the run continue on what is left, not to quietly remove the one thing
    that can veto it — if every residual failed its integrity check (the
    likely shape of the failure, since every equation in a STAR-CCM+ export
    shares one iteration column), the QoI gates alone cannot certify
    convergence and the strongest available verdict is CONVERGING."""
    primary_monitors = [m for m in monitors if m.is_primary]
    flags = collect_flags(metadata, monitors, restart_seen, config)

    index: Optional[float] = None
    binding = "no primary QoI declared"
    unbounded_count = 0
    if primary_monitors:
        unbounded_count = sum(1 for m in primary_monitors if _monitor_is_unbounded(m))
        worst = min(primary_monitors, key=_margin_sort_key)
        if worst.margin is None:
            # No gate on the worst monitor could be bounded at all — see
            # MonitorAssessment.margin, practically unreachable since
            # drift/band/two-halves/window are always finite from real data.
            index = None
            binding = f"{worst.name}: no gate could be bounded"
        else:
            index = worst.margin
            binding = f"{worst.name}: {worst.binding_gate}"
            if _monitor_is_unbounded(worst):
                binding += " (iterative error unbounded)"

    primary_residuals = [r for r in residuals
                         if r.equation_class is EquationClass.PRIMARY]

    if not residuals and not monitors:
        return ConvergenceState.INTEGRITY_FAIL, flags, index, binding, unbounded_count
    # When the verdict comes from the residual layer, the binding constraint has
    # to name the residual that caused it. Reporting the tightest QoI margin
    # there is actively misleading: on a run whose loads are settled 60x inside
    # tolerance but whose residuals stalled at 2.2 decades, it named a QoI gate
    # that had *passed* while the state said STALLED. The residual is also what
    # the user's next action follows from — a stall points at the per-cell
    # residual field function, not at the QoIs.
    diverging = [r for r in residuals if r.state is ResidualState.DIVERGING]
    if diverging:
        worst_residual = min(diverging, key=lambda r: r.decades_dropped)
        return (ConvergenceState.DIVERGED, flags, index,
                f"{worst_residual.name}: diverging", unbounded_count)
    # Turbulence residuals routinely stall one to two orders above the momentum
    # residuals without harming the QoIs, so only primary-class equations can
    # force a stall verdict.
    stalled = [r for r in primary_residuals if r.state is ResidualState.STALLED]
    if stalled:
        worst_residual = min(stalled, key=lambda r: r.decades_dropped)
        return (ConvergenceState.STALLED, flags, index,
                f"{worst_residual.name}: only {worst_residual.decades_dropped:.1f} of "
                f"{config.d_min:.0f} required decades", unbounded_count)
    if not primary_monitors:
        return ConvergenceState.CONVERGING, flags, index, binding, unbounded_count
    if any(not _gate(m, GATE_DRIFT).passed for m in primary_monitors):
        return ConvergenceState.SLOW_DRIFT, flags, index, binding, unbounded_count
    if not all(m.passed for m in primary_monitors):
        return ConvergenceState.CONVERGING, flags, index, binding, unbounded_count
    if residual_evidence_destroyed:
        flags = list(dict.fromkeys([*flags, AdvisoryFlag.NO_RESIDUAL_EVIDENCE]))
        return ConvergenceState.CONVERGING, flags, index, binding, unbounded_count
    if primary_residuals and all(
            r.state is ResidualState.MACHINE_PRECISION for r in primary_residuals):
        return ConvergenceState.CONVERGED_MACHINE, flags, index, binding, unbounded_count
    return ConvergenceState.CONVERGED, flags, index, binding, unbounded_count


def confidence_of(metadata: RunMetadata, residuals, monitors: list[MonitorAssessment],
                  integrity_errors: Optional[list[str]], config,
                  residual_evidence_destroyed: bool = False,
                  monitor_evidence_destroyed: bool = False) -> tuple[Confidence, str]:
    """High/Medium/Low with the rule that produced it, so the level is
    auditable rather than an opinion.

    Dropped series must show up here, not just in the reasons list: losing an
    entire class of evidence — every residual, or every monitor, that existed
    then failed its integrity check — caps confidence at Low, the same class
    of loss that, for residuals, also holds the state at CONVERGING (see
    ``roll_up``). ``residual_evidence_destroyed``/``monitor_evidence_destroyed``
    key on that distinction: a data set that simply never had residual (or
    monitor) history is a different, benign situation and must not read the
    same as one where evidence was thrown away. Any integrity error at all,
    even one series among many, caps confidence at Medium — evidence was
    thrown away, so the remaining record is not complete enough to call High
    regardless of how clean it looks."""
    primary = [m for m in monitors if m.is_primary]
    integrity_errors = integrity_errors or []
    low: list[str] = []
    medium: list[str] = []

    if not primary:
        low.append("no primary QoI declared")
    if residual_evidence_destroyed:
        low.append("no residual evidence survived preconditioning")
    if monitor_evidence_destroyed:
        low.append("no monitor evidence survived preconditioning")
    if not metadata.residual_normalization.known:
        low.append("residual normalization unknown")
    for field, label in (
        (metadata.solver_regime, "solver regime"),
        (metadata.precision, "solver precision"),
    ):
        if not field.known:
            medium.append(f"{label} unknown")
    if integrity_errors:
        dropped = ", ".join(_series_label(msg) for msg in integrity_errors)
        medium.append(f"series dropped during preconditioning ({dropped})")

    for monitor in primary:
        # n_eff is a *proxy* for "is the mean known to within tolerance". When
        # the window gate took its relaxed route it measured that quantity
        # directly (confidence half-width on the mean, plus agreement with the
        # preceding block) precisely because the proxy is unsatisfiable on a
        # very smooth monitor — smoothness is high autocorrelation. Re-applying
        # the proxy here contradicted the gate on the same number: the real
        # 2500Iter_Bodywork export read "CONVERGED / Low — only 5 effective
        # samples" while both its primary monitors passed that gate at margins
        # of 4.40 and 2.38. The gate remains the arbiter of window adequacy;
        # if it passed only barely, the marginal-margin check below still
        # catches it, and a monitor that never needed the relaxation keeps the
        # floor in full.
        if not monitor.window_relaxed:
            if monitor.n_eff < config.n_eff_floor:
                low.append(
                    f"{monitor.name}: only {monitor.n_eff:.0f} effective samples")
            elif monitor.n_eff < config.n_eff_min:
                medium.append(
                    f"{monitor.name}: {monitor.n_eff:.0f} effective samples")
        if monitor.n_window < config.window_min:
            low.append(f"{monitor.name}: window shorter than {config.window_min}")
        if (monitor.margin is not None
                and config.marginal_low <= monitor.margin <= config.marginal_high):
            medium.append(f"{monitor.name}: margin {monitor.margin:.2f} is marginal")
        if not monitor.iterative.valid:
            # The geometric fit declines for any settled monitor with
            # ordinary noise — there is no geometric structure in white
            # noise to fit — so capping confidence on decline alone would
            # make High unreachable for essentially every well-converged
            # run (the same trap INCOMPLETE_EVIDENCE avoids, see
            # collect_flags). Instead, scale the cap to how weak the
            # fallback evidence actually is: the iterative gate's own
            # tested quantity (the largest single-iteration change, or an
            # infinite stand-in when the static-monitor escape hatch was
            # denied) against its own limit. A small fraction means the
            # monitor is emphatically static and the unbounded tail is
            # immaterial; a meaningful fraction means it is still moving
            # at tolerance scale and the missing bound matters.
            gate = _gate(monitor, GATE_ITERATIVE)
            if gate.value > config.iterative_unbounded_confidence_fraction * gate.limit:
                medium.append(
                    f"{monitor.name}: remaining iterative error is unbounded "
                    "and the monitor is still moving at an appreciable "
                    f"fraction of tolerance ({monitor.iterative.reason})"
                )

    if low:
        return Confidence.LOW, "Low — " + "; ".join(low)
    if medium:
        return Confidence.MEDIUM, "Medium — " + "; ".join(medium)
    relaxed = [m.name for m in primary if m.window_relaxed]
    if relaxed:
        samples = ("the mean of " + ", ".join(relaxed) + " known to well "
                   "inside tolerance (window-adequacy relaxation)")
    else:
        samples = f"at least {config.n_eff_min:.0f} effective samples"
    return Confidence.HIGH, (
        "High — metadata complete, at least one primary QoI, "
        f"{samples}, no marginal gate"
    )


def build_reasons(state: ConvergenceState, residuals,
                  monitors: list[MonitorAssessment], flags: list[AdvisoryFlag],
                  config, metadata: Optional[RunMetadata] = None,
                  integrity_errors: Optional[list[str]] = None) -> list[Reason]:
    """One entry per failed gate, per marginal pass, and per active flag, plus
    an info line for each passing primary monitor so the user can see the
    evidence the verdict rests on."""
    reasons: list[Reason] = []
    integrity_errors = integrity_errors or []

    if state is ConvergenceState.UNSTEADY_UNSUPPORTED:
        regime = metadata.solver_regime if metadata is not None else None
        if regime is not None and regime.known:
            label = regime.value.replace("_", " ")
            article = "an" if label[:1].lower() in "aeiou" else "a"
            message = (f"This is {article} {label} run, not steady. Its residuals "
                      "and QoIs do not behave like a steady run's — a per-time-step "
                      "sawtooth and a statistical record rather than a fixed "
                      "point — so the steady tests would give a confident wrong "
                      "answer.")
        else:
            message = ("The solver regime could not be determined, so steady "
                      "tests were not applied. That is a different situation "
                      "from a run positively identified as not steady: "
                      "assessing an unknown regime as steady anyway would risk "
                      "a confident wrong answer on a case that may actually be "
                      "transient.")
        reasons.append(Reason(
            severity=Severity.ERROR, target="run",
            message=message,
            suggested_action=("Assess this run manually for now: check that the "
                              "inner iterations (or harmonics) drop at least one "
                              "order per outer step, and that the QoI record is "
                              "long enough for its time-average to be stationary. "
                              "If the regime is unknown, re-extract this data set "
                              "so it is captured, or confirm manually whether the "
                              "run is steady."),
        ))
        return reasons

    for msg in integrity_errors:
        name, sep, detail = msg.partition(": ")
        target = name if sep else "run"
        severity = (Severity.ERROR if state is ConvergenceState.INTEGRITY_FAIL
                   else Severity.WARNING)
        reasons.append(Reason(
            severity=severity, target=target,
            message=(f"{msg}, so this series was dropped from the assessment."
                     if severity is Severity.WARNING else f"{msg}."),
            suggested_action=("Check why this monitor history is malformed "
                              "(a duplicated or non-monotonic iteration index "
                              "after the last restart split, an empty series, or "
                              "too few points); re-extract if needed."),
        ))

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

    if metadata is not None and metadata.precision.known and \
            metadata.precision.provenance is Provenance.DERIVED:
        # The precision that sets the machine-precision floor is read from the
        # server running the extraction, because nothing in STAR-CCM+ records
        # the arithmetic of the run that actually produced the residuals. The
        # two agree wherever one build is installed, which is the normal case
        # — but MACHINE_PRECISION is the strongest terminal state this module
        # awards, so the evidence it rests on is stated rather than implied.
        reasons.append(Reason(
            severity=Severity.INFO, target="run",
            message=(f"Solver precision was taken as {metadata.precision.value} "
                     "from the server that extracted this data set, which "
                     "STAR-CCM+ does not record per simulation. That sets the "
                     "arithmetic floor the residuals are judged against."),
            suggested_action=("If this case was solved at a different "
                              "precision from the one StarPost extracts with, "
                              "treat any machine-precision verdict as "
                              "unconfirmed."),
        ))

    if (monitors and not residuals
            and AdvisoryFlag.NO_RESIDUAL_EVIDENCE not in flags):
        # Distinct from NO_RESIDUAL_EVIDENCE: that flag means residual
        # evidence existed and was destroyed by an integrity failure, which
        # holds the state at CONVERGING. Here there simply never were any
        # residual monitors to begin with — this data set may still reach
        # CONVERGED, but it did so on QoI evidence alone, with no residual
        # health check at all, and the user should see that plainly rather
        # than infer it from an empty residuals table.
        reasons.append(Reason(
            severity=Severity.INFO, target="run",
            message=("This data set has no residual monitors at all, so the "
                     "verdict rests on QoI evidence alone with no residual "
                     "health check."),
            suggested_action=("If residual histories should be present, "
                              "check the classification settings or "
                              "re-extract this data set."),
        ))

    for monitor in monitors:
        if monitor.is_primary:
            # Primary monitors gate the verdict, so they keep their full
            # per-gate detail exactly as before: one Reason per failed gate,
            # and one per gate passing only marginally.
            for gate in monitor.gates:
                if gate.passed:
                    continue
                reasons.append(Reason(
                    severity=Severity.ERROR, target=monitor.name,
                    message=(f"{monitor.name} fails the {gate.name} gate: "
                             f"{gate.value:.4g} against a limit of "
                             f"{gate.limit:.4g} ({gate.detail})."),
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
        else:
            # Non-primary monitors do not gate the verdict, and a real
            # car-aero export can carry dozens of them (per-element siblings
            # of an auto-primary aggregate) -- one Reason per failed gate per
            # monitor buried the handful of reasons that actually matter
            # under a hundred-plus warnings. Rolled up to at most one Reason
            # per monitor, naming which gates failed; a marginal *pass* is
            # dropped entirely, since marginality on a monitor that does not
            # gate anything is noise, not a warning. The per-gate numbers
            # are still reachable in the QoI gates tab.
            failed_names = [g.name for g in monitor.gates if not g.passed]
            if failed_names:
                plural = "s" if len(failed_names) > 1 else ""
                reasons.append(Reason(
                    severity=Severity.WARNING, target=monitor.name,
                    message=(f"{monitor.name} fails the "
                             f"{_join_names(failed_names)} gate{plural}. It "
                             "is not a primary monitor, so this does not "
                             "gate the verdict; see the QoI gates tab for "
                             "per-gate values."),
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
        if monitor.is_primary and not monitor.iterative.valid:
            reasons.append(Reason(
                severity=Severity.WARNING, target=monitor.name,
                message=(f"{monitor.name}'s remaining iterative error could not "
                         "be bounded: its change series carried no geometric "
                         f"structure ({monitor.iterative.reason}), so the "
                         "verdict rests on the other four gates and on this "
                         "monitor having stopped moving at the tolerance scale."),
                suggested_action=("Continue iterating so the change series "
                                  "develops a clear geometric trend, or treat "
                                  "this verdict's confidence as capped rather "
                                  "than definitive."),
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
    (AdvisoryFlag.AUTOCORRELATION_UNRELIABLE,
     "At least one monitor's decorrelation estimate does not meet its own "
     "validity assumption — the truncation lag (tau_0) is not small relative to "
     "the record length. The effective-sample count derived from it, and "
     "therefore the window-adequacy gate, should be treated as approximate "
     "rather than exact.",
     "Continue iterating so the record is long relative to the correlation "
     "length, and treat a marginal window-adequacy pass with extra caution."),
    (AdvisoryFlag.NO_RESIDUAL_EVIDENCE,
     "No residual history survived preconditioning, so this run could not be "
     "certified as converged: residuals are necessary evidence and here there "
     "is none to check. The verdict is held at CONVERGING even though every "
     "QoI gate passed, because the engineering quantities alone are not "
     "sufficient — that is what a residual veto would normally be for.",
     "Check why every residual series failed its integrity check (see the "
     "per-series warnings above) and re-extract this data set if the "
     "residual monitors should be present."),
    (AdvisoryFlag.ITERATIVE_ERROR_UNBOUNDED,
     "At least one primary monitor's remaining iterative error could not be "
     "bounded: its change series carried no geometric structure to "
     "extrapolate, so there is no numeric bound on how far it may still be "
     "from its converged value. The verdict rests on the other four gates "
     "and on the monitor having stopped moving at the tolerance scale, not "
     "on a quantified remaining error. When that monitor is still moving at "
     "an appreciable fraction of tolerance, confidence is capped at Medium; "
     "when it is emphatically static, the missing bound is immaterial and "
     "confidence is unaffected (see the confidence rule for which applies "
     "here).",
     "Continue iterating in the hope the change series develops a clear "
     "geometric trend, or treat this verdict's confidence as capped rather "
     "than definitive when the confidence rule says so."),
)
