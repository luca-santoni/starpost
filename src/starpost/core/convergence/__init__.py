"""Convergence assessment for solved STAR-CCM+ simulations.

Phase 1 covers steady runs. It answers three of the five questions behind
"is it converged?": is the solve healthy, has the iteration stopped changing
the solution, and have the engineering quantities stopped changing. Unsteady
runs are detected and refused rather than assessed with steady tests, and the
global-conservation check is declared missing rather than skipped silently.

Reads cached SimResult data only — this never re-runs STAR-CCM+.
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np

from starpost.core.convergence.config import ConvergenceConfig
from starpost.core.convergence.metadata import read_metadata
from starpost.core.convergence.models import (
    Confidence,
    ConvergenceAssessment,
    ConvergenceState,
    EquationClass,
    MonitorAssessment,
    Reason,
    ResidualAssessment,
    Severity,
)
from starpost.core.convergence.residuals import assess_residual
from starpost.core.convergence.signals import (
    MonitorSignal,
    collect_signals,
    equation_class,
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
    # Whole-word (case-insensitive) keywords that mark a force-keyword
    # monitor as an aggregate rather than a per-element contributor — see
    # _select_auto_primary below.
    "aggregate_keywords": ["ALL", "Total", "Sum", "Overall", "Combined"],
}


def _matches_any(haystack: str, keywords: list[str]) -> bool:
    lowered = haystack.lower()
    return any(kw.lower() in lowered for kw in keywords)


def _matches_whole_word(haystack: str, keyword: str) -> bool:
    """Case-insensitive whole-word match. Unlike a bare substring test, "ALL"
    does not match "Downforce wall Monitor", and "Total" does not match
    something that merely contains "total" as part of a longer word."""
    return re.search(rf"\b{re.escape(keyword)}\b", haystack, re.IGNORECASE) is not None


def _is_force_match(name: str, plot: str, classification: dict) -> bool:
    return _matches_any(f"{name} {plot}", classification.get("force_keywords", []))


def _is_aggregate(name: str, plot: str, classification: dict) -> bool:
    haystack = f"{name} {plot}"
    keywords = classification.get(
        "aggregate_keywords", _DEFAULT_CLASSIFICATION["aggregate_keywords"]
    )
    return any(_matches_whole_word(haystack, kw) for kw in keywords)


def _select_auto_primary(
    signals: list[MonitorSignal], classification: dict
) -> tuple[set[str], bool, list[MonitorSignal]]:
    """Which force-keyword monitors are auto-marked primary, absent an
    explicit per-monitor override.

    Force-like monitors are primary by default: they are the engineering
    deliverable in the overwhelming majority of cases, and a verdict with no
    primary QoI is not a verdict. But a data set that reports both an
    aggregate ("Downforce ALL") and its per-element contributors ("Downforce
    wing front 1", "Downforce wing front 2", ...) should not let the headline
    verdict ride on whichever sub-component happens to be noisiest — so when
    at least one force-keyword monitor looks like an aggregate (matches an
    aggregate keyword as a whole word), only the aggregate(s) are auto-primary
    and the per-element monitors are demoted to non-gating (still assessed,
    still able to raise warnings). When no aggregate is detectable, every
    force-keyword match is primary, exactly as before this preference existed.

    Returns ``(primary_names, used_aggregates, matches)``: ``matches`` is
    every force-keyword monitor found (used to explain the "no aggregate
    detected" fallback), ``primary_names`` is the subset actually chosen, and
    ``used_aggregates`` says which branch fired."""
    matches = [s for s in signals if _is_force_match(s.name, s.plot, classification)]
    aggregates = [s for s in matches if _is_aggregate(s.name, s.plot, classification)]
    chosen = aggregates if aggregates else matches
    return {s.name for s in chosen}, bool(aggregates), matches


def _auto_primary_reason(
    auto_primary_names: set[str],
    used_aggregates: bool,
    force_matches: list[MonitorSignal],
    config: ConvergenceConfig,
) -> Optional[Reason]:
    """An INFO reason naming which monitors were auto-selected as primary and
    why, so the choice is visible rather than implicit — a wrong auto-choice
    would otherwise silently narrow the verdict with no trace in the Reasons
    tab. Limited to monitors the auto logic actually decided: one the user
    overrode via an explicit MonitorConfig is that monitor's choice, not the
    auto rule's, so it is excluded here."""
    if not force_matches:
        return None
    effective = sorted(
        name for name in auto_primary_names if config.monitors.get(name) is None
    )
    if not effective:
        return None
    names_text = ", ".join(effective)
    if used_aggregates:
        message = (
            f"{len(effective)} monitor(s) auto-selected as primary because "
            "their name matches an aggregate keyword (ALL/Total/Sum/Overall/"
            f"Combined) among the {len(force_matches)} force-keyword monitors "
            f"in this data set: {names_text}. The verdict rests on these; "
            "their per-element siblings are still assessed and can raise "
            "warnings, but do not gate the headline."
        )
    else:
        message = (
            "No aggregate monitor was detected among the "
            f"{len(force_matches)} force-keyword monitors in this data set, "
            f"so all of them were auto-selected as primary: {names_text}."
        )
    return Reason(severity=Severity.INFO, target="run", message=message)


def assess(result, config: Optional[ConvergenceConfig] = None,
           classification: Optional[dict] = None) -> ConvergenceAssessment:
    """Assess one SimResult. The only public entry point of this package."""
    config = config or ConvergenceConfig()
    classification = classification or _DEFAULT_CLASSIFICATION

    metadata = read_metadata(result.properties)
    residual_signals, qoi_signals = collect_signals(result, classification)

    def finish(state, residuals, monitors, integrity_errors, restart_seen,
               segments, auto_primary_reason: Optional[Reason] = None
               ) -> ConvergenceAssessment:
        if state is ConvergenceState.UNSTEADY_UNSUPPORTED:
            flags, index, unbounded_count = [], None, 0
            # Match verdict.build_reasons' human-readable label (underscores
            # replaced with spaces) rather than the raw token, so the summary
            # table and the reason text agree on how the regime is spelled.
            binding = (f"{metadata.solver_regime.value.replace('_', ' ')} run: "
                      "not assessed"
                      if metadata.solver_regime.known
                      else "solver regime unknown: not assessed")
            confidence, rule = Confidence.LOW, "Low — non-steady or unknown-regime runs are not assessed"
        else:
            # "No residuals/monitors survived" only means evidence was
            # *destroyed* when at least one such signal was collected before
            # preconditioning dropped every one of them. A data set that
            # simply never had residual (or monitor) history to begin with —
            # a monitor-only portable CSV, a deleted Residuals plot, a
            # classification override — is a different, benign situation and
            # must not read the same as one where evidence was thrown away.
            residual_evidence_destroyed = bool(residual_signals) and not residuals
            monitor_evidence_destroyed = bool(qoi_signals) and not monitors
            state, flags, index, binding, unbounded_count = roll_up(
                metadata, residuals, monitors, restart_seen, config,
                residual_evidence_destroyed,
            )
            confidence, rule = confidence_of(
                metadata, residuals, monitors, integrity_errors, config,
                residual_evidence_destroyed, monitor_evidence_destroyed,
            )
        reasons = build_reasons(state, residuals, monitors, flags, config,
                                metadata, integrity_errors)
        # INFO severity, so it belongs at the tail of build_reasons' own
        # severity-sorted output — appended rather than re-sorted in.
        if auto_primary_reason is not None:
            reasons.append(auto_primary_reason)
        return ConvergenceAssessment(
            sim_path=result.sim_path,
            sim_name=result.sim_name,
            metadata=metadata,
            state=state,
            confidence=confidence,
            confidence_rule=rule,
            convergence_index=index,
            binding_constraint=binding,
            unbounded_primary_count=unbounded_count,
            flags=flags,
            residuals=residuals,
            monitors=monitors,
            reasons=reasons,
            thresholds_used=config.as_dict(),
            n_segments=segments,
            integrity_errors=list(integrity_errors),
        )

    # INTEGRITY_FAIL outranks everything else in the state ladder (see
    # ConvergenceState's docstring), so "there is nothing here to assess" is
    # checked before "the regime is not steady" — a data set with no monitor
    # histories at all is not usefully described as "unsteady" or "regime
    # unknown", whatever its metadata says.
    if not residual_signals and not qoi_signals:
        return finish(ConvergenceState.INTEGRITY_FAIL, [], [],
                      ["no monitor histories were found in this data set"],
                      False, 1)

    if not metadata.is_steady:
        return finish(ConvergenceState.UNSTEADY_UNSUPPORTED, [], [], [], False, 1)

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
        # split_segments breaks wherever diff(x) <= 0, so a single duplicated
        # or out-of-order index near the end of an otherwise clean series
        # yields a one-point (or otherwise malformed) final segment. The
        # whole-series check above cannot catch that — re-validate the
        # segment actually being analysed.
        segment_error = integrity_error(segment.x, segment.y)
        if segment_error:
            integrity_errors.append(
                f"{signal.name}: final segment {segment_error} "
                "(a restart split may have left a malformed tail)"
            )
            continue
        # Turbulence residuals spike by nature and are held to weaker
        # standards everywhere else in this module, so only primary-class
        # equations can raise a restart suspicion (see restart_suspected's
        # own persistence check in signals.py for the other half of this fix).
        if (count == 1 and equation_class(signal.name) is EquationClass.PRIMARY
                and restart_suspected(segment.y, config.kappa_div)):
            restart_seen = True
        residuals.append(assess_residual(
            signal.name, segment.y, config,
            precision=metadata.precision.value,
            auto_norm_sample_count=metadata.auto_norm_sample_count,
        ))

    auto_primary_names, used_aggregates, force_matches = _select_auto_primary(
        qoi_signals, classification
    )

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
        segment_error = integrity_error(segment.x, segment.y)
        if segment_error:
            integrity_errors.append(
                f"{signal.name}: final segment {segment_error} "
                "(a restart split may have left a malformed tail)"
            )
            continue
        override = config.monitors.get(signal.name)
        is_primary = (
            override.is_primary if override is not None
            else signal.name in auto_primary_names
        )
        monitors.append(assess_monitor(signal.name, segment.y, config,
                                       is_primary=is_primary))

    return finish(ConvergenceState.CONVERGING, residuals, monitors,
                  integrity_errors, restart_seen, segments,
                  _auto_primary_reason(auto_primary_names, used_aggregates,
                                      force_matches, config))
