"""In-app monitor plot viewer (pyqtgraph). Residuals: log Y, multi-series.

Two modes:
  show_plot(plot)               — one sim's plot, each series a distinct color
  show_comparison(name, plots)  — same plot across sims overlaid for comparison

A "Monitors" dropdown beneath the plot lets the user choose which series
(monitors) of the current plot are drawn — useful when a plot bundles many.
"""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

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
        self._legend = self._plot.addLegend()
        self._plot.showGrid(x=True, y=True, alpha=0.3)

        # Monitor (series) selector shown beneath the plot.
        self._monitor_btn = QToolButton()
        self._monitor_btn.setObjectName("monitorSelect")
        self._monitor_btn.setText("Monitors")
        self._monitor_btn.setPopupMode(QToolButton.InstantPopup)
        self._monitor_menu = QMenu(self._monitor_btn)
        self._monitor_btn.setMenu(self._monitor_menu)
        self._series_actions: dict[str, object] = {}

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Monitors:"))
        ctrl.addWidget(self._monitor_btn)
        ctrl.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._plot, 1)
        layout.addLayout(ctrl)

        # What to re-render when the monitor selection changes.
        self._mode: str | None = None          # "single" | "comparison"
        self._current = None                    # MonitorPlot | (name, plots)

    # --- public entry points --------------------------------------------
    def show_plot(self, plot: MonitorPlot) -> None:
        self._mode = "single"
        self._current = plot
        self._rebuild_monitor_menu([s.name for s in plot.series])
        self._render()

    def show_comparison(self, name: str, plots: list[tuple[str, MonitorPlot]]) -> None:
        """plots: list of (sim_name, MonitorPlot) for the same plot across sims."""
        self._mode = "comparison"
        self._current = (name, plots)
        names: list[str] = []
        seen: set[str] = set()
        for _, p in plots:
            for s in p.series:
                if s.name not in seen:
                    seen.add(s.name)
                    names.append(s.name)
        self._rebuild_monitor_menu(names)
        self._render()

    # --- monitor selector ------------------------------------------------
    def _rebuild_monitor_menu(self, names: list[str]) -> None:
        self._monitor_menu.clear()
        self._series_actions = {}
        for n in names:
            act = self._monitor_menu.addAction(n)
            act.setCheckable(True)
            act.setChecked(True)
            act.toggled.connect(self._on_monitor_toggled)
            self._series_actions[n] = act
        self._update_monitor_button()

    def _selected_series(self) -> set[str]:
        return {n for n, a in self._series_actions.items() if a.isChecked()}

    def _on_monitor_toggled(self, _checked: bool) -> None:
        self._update_monitor_button()
        self._render()

    def _update_monitor_button(self) -> None:
        total = len(self._series_actions)
        sel = len(self._selected_series())
        self._monitor_btn.setText(f"Monitors ({sel}/{total})" if total else "Monitors")
        self._monitor_btn.setEnabled(total > 0)

    # --- rendering -------------------------------------------------------
    def _reset(self, title: str, y_log: bool) -> None:
        self._plot.clear()
        self._legend.clear()  # avoid stale/duplicate legend entries on re-render
        self._plot.setTitle(title)
        self._plot.setLogMode(x=False, y=y_log)
        self._plot.setLabel("bottom", "Iteration")
        self._plot.setLabel("left", "Value")

    def _render(self) -> None:
        if self._mode == "single":
            self._render_single(self._current, self._selected_series())
        elif self._mode == "comparison":
            name, plots = self._current
            self._render_comparison(name, plots, self._selected_series())

    def _render_single(self, plot: MonitorPlot, selected: set[str]) -> None:
        self._reset(plot.name, plot.y_log)
        # Keep each series' colour stable regardless of which are filtered out.
        for i, s in enumerate(plot.series):
            if s.name not in selected:
                continue
            self._plot.plot(
                s.x, s.y, name=s.name, pen=pg.mkPen(_COLORS[i % len(_COLORS)], width=1.5)
            )

    def _render_comparison(
        self, name: str, plots: list[tuple[str, MonitorPlot]], selected: set[str]
    ) -> None:
        y_log = any(p.y_log for _, p in plots)
        self._reset(f"{name} (comparison)", y_log)
        for i, (sim_name, plot) in enumerate(plots):
            color = _COLORS[i % len(_COLORS)]
            for s in plot.series:
                if s.name not in selected:
                    continue
                label = f"{sim_name}: {s.name}" if len(plot.series) > 1 else sim_name
                self._plot.plot(s.x, s.y, name=label, pen=pg.mkPen(color, width=1.5))
