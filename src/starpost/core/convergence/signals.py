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
