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
class Displayer:
    """A scalar or vector displayer inside a scene (what draws a field/glyphs)."""
    name: str
    kind: str = "scalar"   # "scalar" | "vector"


@dataclass
class Scene:
    """A STAR-CCM+ scene and its selectable scalar/vector displayers."""
    name: str
    displayers: list[Displayer] = field(default_factory=list)


@dataclass
class MediaArtifact:
    """A rendered visual output (e.g. a scene still). The file lives on disk; this
    just records where it is and what produced it."""
    name: str                   # display name (the scene name, for stills)
    path: str                   # absolute path to the rendered file on disk
    source: str = ""            # the scene (or, later, screenplay) it came from
    kind: str = "still"         # "still" | "video" (video reserved for later)
    width: int = 0
    height: int = 0
    error: Optional[str] = None


@dataclass
class SimResult:
    """Everything extracted from one .sim file."""
    sim_path: str
    reports: list[Report] = field(default_factory=list)
    plots: list[MonitorPlot] = field(default_factory=list)
    # Scenes discovered in the .sim during extraction (no rendering), each with
    # its scalar/vector displayers; these populate the Scenes selection tree,
    # mirroring the monitor-plot groups.
    scenes: list[Scene] = field(default_factory=list)
    # Saved camera views discovered in the .sim (sim-global, via the view
    # manager); a scene can be rendered from any of these.
    views: list[str] = field(default_factory=list)
    # Visual outputs rendered from this .sim (scene stills, etc.). Produced by a
    # separate render pass, not the numeric extraction.
    media: list[MediaArtifact] = field(default_factory=list)
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

    def scene_names(self) -> set[str]:
        return {s.name for s in self.scenes}

    def signature(self) -> tuple[frozenset[str], frozenset[str]]:
        """Used for the homogeneity check across a batch."""
        return frozenset(self.report_names()), frozenset(self.plot_names())
