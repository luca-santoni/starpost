"""Plot line colours and monitor display names.

Split out of plot_view so widgets that only need these (the selection panel's
colour swatches and monitor labels) don't drag in pyqtgraph + numpy — a ~0.3 s
import chain that must stay off the startup path. plot_view re-exports them,
so its importers are unaffected.
"""
from __future__ import annotations

import re

# Default line colours, cycled across series in drawing order.
_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
]

# Series names from STAR-CCM+ exports carry their unit as a trailing
# parenthetical, e.g. "Mass Flow (kg/s)". Pull it out so the Y axis can label it.
_UNIT_RE = re.compile(r"\(([^()]*)\)\s*$")


def _series_unit(name: str) -> str:
    m = _UNIT_RE.search(name.strip())
    return m.group(1).strip() if m else ""


def _display_name(name: str) -> str:
    """Collapse STAR-CCM+'s doubled monitor labels for display only.

    A single-monitor series is exported as "<Plot>: <Plot> (unit)"; show just
    "<Plot> (unit)" when the prefix merely repeats the rest of the label. Other
    "A: B" names (genuinely different parts) are left untouched. The stored
    series name is never changed — it stays the lookup key everywhere."""
    prefix, sep, rest = name.partition(": ")
    if sep and prefix.strip() and prefix.strip() == _UNIT_RE.sub("", rest).strip():
        return rest.strip()
    return name
