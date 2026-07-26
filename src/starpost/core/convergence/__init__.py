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
