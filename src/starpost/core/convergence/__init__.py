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
    EquationClass,
    MonitorAssessment,
    ResidualAssessment,
)
from starpost.core.convergence.residuals import assess_residual
from starpost.core.convergence.signals import (
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
            reasons=build_reasons(state, residuals, monitors, flags, config,
                                  metadata, integrity_errors),
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
            else _auto_primary(signal.name, signal.plot, classification)
        )
        monitors.append(assess_monitor(signal.name, segment.y, config,
                                       is_primary=is_primary))

    return finish(ConvergenceState.CONVERGING, residuals, monitors,
                  integrity_errors, restart_seen, segments)
