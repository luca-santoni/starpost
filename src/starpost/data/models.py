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

    def max_abs(self) -> float:
        """The largest |y|, cached on the instance: the data is immutable once
        extracted, and this scan over every point is hit on redraws and
        selection-list rebuilds — too hot to repeat for large workspaces."""
        cached = getattr(self, "_max_abs_cache", None)
        if cached is None:
            cached = max(map(abs, self.y), default=0.0)
            self._max_abs_cache = cached
        return cached

    def is_empty(self, zero_threshold: float) -> bool:
        """True when every value lies within (-threshold, +threshold).

        The threshold is an absolute magnitude, so monitors that are strongly
        negative still count as non-empty."""
        return not self.y or self.max_abs() < zero_threshold


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
class Screenplay:
    """A STAR-CCM+ screenplay (animation): the scene it plays and that scene's
    selectable scalar/vector displayers."""
    name: str
    scene: str = ""   # the scene the screenplay animates ("" if unresolved)
    displayers: list[Displayer] = field(default_factory=list)


@dataclass
class MediaArtifact:
    """A rendered visual output (e.g. a scene still). The file lives on disk; this
    just records where it is and what produced it."""
    name: str                   # display name (the scene name, for stills)
    path: str                   # absolute path to the rendered file on disk
    source: str = ""            # the scene (or, later, screenplay) it came from
    kind: str = "still"         # "still" | "movie" (movie == recorded screenplay)
    width: int = 0
    height: int = 0
    error: Optional[str] = None
    # Provenance, for the gallery's Properties window.
    sim_path: str = ""          # the .sim this was rendered from
    displayers: str = ""        # the visible scalar/vector displayers (readable)
    view: str = ""              # the saved view applied ("" == the current view)
    poster: str = ""            # movie-kind only: absolute path to the poster PNG


@dataclass
class PropertyGroup:
    """One entity's extracted sim properties: a section ("mesh", "region", ...),
    the entity's name ("" for sim-wide sections), and its key/value entries in
    extraction order."""
    section: str
    name: str = ""
    entries: list[tuple[str, str]] = field(default_factory=list)

    def get(self, key: str) -> Optional[str]:
        for k, v in self.entries:
            if k == key:
                return v
        return None


@dataclass
class SimProperties:
    """Simulation metadata captured at extraction time (solution state, mesh
    counts, regions, physics, tags, ...). Deliberately generic strings, not
    typed fields: the key set drifts across STAR-CCM+ releases and extraction
    tiers, and the consumer is a display dialog — anything needing a number
    parses it at the point of use."""
    groups: list[PropertyGroup] = field(default_factory=list)

    def get(self, section: str, name: str = "") -> Optional[PropertyGroup]:
        for g in self.groups:
            if g.section == section and g.name == name:
                return g
        return None


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
    # Screenplays discovered in the .sim during extraction (no recording), each
    # with its scene's scalar/vector displayers; these populate the Screenplays
    # selection tree, mirroring the Scenes tree.
    screenplays: list[Screenplay] = field(default_factory=list)
    # Visual outputs rendered from this .sim (scene stills, etc.). Produced by a
    # separate render pass, not the numeric extraction.
    media: list[MediaArtifact] = field(default_factory=list)
    # Simulation metadata captured during extraction (None for results
    # extracted before this feature). Never part of signature().
    properties: Optional[SimProperties] = None
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

    def screenplay_names(self) -> set[str]:
        return {s.name for s in self.screenplays}

    def signature(self) -> tuple[frozenset[str], frozenset[str]]:
        """Used for the homogeneity check across a batch."""
        return frozenset(self.report_names()), frozenset(self.plot_names())
