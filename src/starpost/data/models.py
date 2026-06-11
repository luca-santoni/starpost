"""Core data model: what a single .sim's extracted post-processing looks like."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PlotKind(str, Enum):
    RESIDUAL = "residual"   # log Y by default, all series overlaid
    FORCE = "force"         # linear Y
    OTHER = "other"         # linear Y


@dataclass
class Report:
    """A single scalar report value from a .sim."""
    name: str
    value: Optional[float]      # None when extraction failed
    units: str = ""
    error: Optional[str] = None


@dataclass
class PlotSeries:
    """One line on a monitor plot: y vs. a shared x (iteration/time)."""
    name: str
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)


@dataclass
class MonitorPlot:
    """A monitor plot (value vs. iteration), possibly multi-series."""
    name: str
    series: list[PlotSeries] = field(default_factory=list)
    kind: PlotKind = PlotKind.OTHER
    x_label: str = "Iteration"
    # Resolved axis choice (auto from kind, user-overridable). True == log Y.
    y_log: bool = False
    error: Optional[str] = None


@dataclass
class SimResult:
    """Everything extracted from one .sim file."""
    sim_path: str
    reports: list[Report] = field(default_factory=list)
    plots: list[MonitorPlot] = field(default_factory=list)
    extracted_at: str = ""        # ISO timestamp
    error: Optional[str] = None   # set if the whole batch run failed

    # --- convenience -----------------------------------------------------
    @property
    def sim_name(self) -> str:
        from pathlib import Path
        return Path(self.sim_path).stem

    def report_names(self) -> set[str]:
        return {r.name for r in self.reports}

    def plot_names(self) -> set[str]:
        return {p.name for p in self.plots}

    def signature(self) -> tuple[frozenset[str], frozenset[str]]:
        """Used for the homogeneity check across a batch."""
        return frozenset(self.report_names()), frozenset(self.plot_names())
