"""In-app monitor plot viewer (pyqtgraph). Residuals: log Y, multi-series.

Two modes:
  show_plot(plot)               — one sim's plot, each series a distinct color
  show_comparison(name, plots)  — same plot across sims overlaid for comparison
"""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from starpost.data.models import MonitorPlot

# A simple distinct-color cycle for series/sims.
_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
]


class PlotView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.addLegend()
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        layout = QVBoxLayout(self)
        layout.addWidget(self._plot)

    def _reset(self, title: str, y_log: bool) -> None:
        self._plot.clear()
        self._plot.setTitle(title)
        self._plot.setLogMode(x=False, y=y_log)
        self._plot.setLabel("bottom", "Iteration")
        self._plot.setLabel("left", "Value")

    def show_plot(self, plot: MonitorPlot) -> None:
        self._reset(plot.name, plot.y_log)
        for i, s in enumerate(plot.series):
            self._plot.plot(
                s.x, s.y, name=s.name, pen=pg.mkPen(_COLORS[i % len(_COLORS)], width=1.5)
            )

    def show_comparison(self, name: str, plots: list[tuple[str, MonitorPlot]]) -> None:
        """plots: list of (sim_name, MonitorPlot) for the same plot across sims."""
        y_log = any(p.y_log for _, p in plots)
        self._reset(f"{name} (comparison)", y_log)
        for i, (sim_name, plot) in enumerate(plots):
            color = _COLORS[i % len(_COLORS)]
            for j, s in enumerate(plot.series):
                label = f"{sim_name}: {s.name}" if len(plot.series) > 1 else sim_name
                self._plot.plot(s.x, s.y, name=label, pen=pg.mkPen(color, width=1.5))
