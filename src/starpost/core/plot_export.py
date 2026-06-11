"""Render monitor plots to JPG/PDF with matplotlib (used for file export).

Residual plots use a log Y axis with all series overlaid in distinct colors;
force/other plots use a linear Y axis. The in-app live view (pyqtgraph) mirrors
these choices; matplotlib is used here for publication-quality file output.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # file rendering, no display needed
import matplotlib.pyplot as plt  # noqa: E402

from starpost.data.models import MonitorPlot  # noqa: E402


def render_plot(plot: MonitorPlot, path: Path, dpi: int = 150) -> None:
    """Render a single monitor plot to `path` (.jpg/.jpeg/.pdf/.png by suffix)."""
    fig, ax = plt.subplots(figsize=(8, 5))
    for s in plot.series:
        ax.plot(s.x, s.y, label=s.name, linewidth=1.2)

    ax.set_xlabel(plot.x_label)
    ax.set_ylabel("Value")
    ax.set_title(plot.name)
    if plot.y_log:
        ax.set_yscale("log")
    if len(plot.series) > 1:
        ax.legend(loc="best", fontsize="small")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
