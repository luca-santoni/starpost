"""In-app monitor plot viewer (pyqtgraph). Residuals: log Y, multi-series.

Two modes:
  show_plot(plot)               — one sim's plot, each series a distinct color
  show_comparison(name, plots)  — same plot across sims overlaid for comparison

A "Monitors" dropdown beneath the plot lets the user choose which series
(monitors) of the current plot are drawn — useful when a plot bundles many.
"""
from __future__ import annotations

import re

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


class _StayOpenMenu(QMenu):
    """A menu that stays open when its items are clicked.

    Lets the user toggle any number of monitors in one go; the menu only
    closes on the usual dismiss gestures (click the button again, click
    outside, or press Esc).
    """

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        action = self.activeAction()
        if (
            action is not None
            and action.isEnabled()
            and self.actionGeometry(action).contains(event.position().toPoint())
        ):
            if action.isCheckable():
                action.setChecked(not action.isChecked())
            else:
                action.trigger()
            return  # swallow the release so the base class doesn't close the menu
        super().mouseReleaseEvent(event)


# A simple distinct-color cycle for series/sims.
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


def _y_label_for(names: list[str]) -> str:
    """Y-axis label from the plotted series' units: the shared unit when they
    agree, else a generic fallback (mixed units can't share one axis label)."""
    units = {u for u in (_series_unit(n) for n in names) if u}
    if len(units) == 1:
        return next(iter(units))
    return "Value"


def _series_is_empty(series, zero_threshold: float) -> bool:
    """True when every value lies within (-threshold, +threshold).

    The threshold is an absolute magnitude, so monitors that are strongly
    negative still count as non-empty.
    """
    return not series.y or max(abs(v) for v in series.y) < zero_threshold


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
        self._monitor_menu = _StayOpenMenu(self._monitor_btn)
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

        # Empty-monitor filtering (mirrors the Reports settings).
        self._hide_empty = True
        self._zero_threshold = 1e-5

    # --- public entry points --------------------------------------------
    def set_filter(self, hide_empty: bool, zero_threshold: float) -> None:
        """Configure hiding of empty monitors (those whose values are all ~0).

        Re-shows the current plot so the change takes effect immediately.
        """
        self._hide_empty = hide_empty
        self._zero_threshold = zero_threshold
        self._reshow()

    def show_plot(self, plot: MonitorPlot) -> None:
        self._mode = "single"
        self._current = plot
        self._rebuild_monitor_menu([s.name for s in plot.series if self._visible(s)])
        self._render()

    def show_comparison(self, name: str, plots: list[tuple[str, MonitorPlot]]) -> None:
        """plots: list of (sim_name, MonitorPlot) for the same plot across sims."""
        self._mode = "comparison"
        self._current = (name, plots)
        names: list[str] = []
        seen: set[str] = set()
        for _, p in plots:
            for s in p.series:
                if s.name not in seen and self._visible(s):
                    seen.add(s.name)
                    names.append(s.name)
        self._rebuild_monitor_menu(names)
        self._render()

    def clear(self) -> None:
        """Blank the view — e.g. when no plot is selected for display."""
        self._mode = None
        self._current = None
        self._rebuild_monitor_menu([])
        self._plot.clear()
        self._legend.clear()
        self._plot.setTitle("")

    # --- empty-monitor filtering ----------------------------------------
    def _visible(self, series) -> bool:
        """False for monitors filtered out by the hide-empty setting."""
        return not (self._hide_empty and _series_is_empty(series, self._zero_threshold))

    def _reshow(self) -> None:
        """Re-run the active show_* so a filter change rebuilds the menu/plot."""
        if self._mode == "single":
            self.show_plot(self._current)
        elif self._mode == "comparison":
            name, plots = self._current
            self.show_comparison(name, plots)

    # --- monitor selector ------------------------------------------------
    def _rebuild_monitor_menu(self, names: list[str]) -> None:
        self._monitor_menu.clear()
        self._series_actions = {}
        if names:
            self._monitor_menu.addAction("Select all").triggered.connect(
                lambda: self._set_all_series(True)
            )
            self._monitor_menu.addAction("Deselect all").triggered.connect(
                lambda: self._set_all_series(False)
            )
            self._monitor_menu.addSeparator()
        for n in names:
            act = self._monitor_menu.addAction(n)
            act.setCheckable(True)
            act.setChecked(True)
            act.toggled.connect(self._on_monitor_toggled)
            self._series_actions[n] = act
        self._update_monitor_button()

    def _set_all_series(self, state: bool) -> None:
        for a in self._series_actions.values():
            a.blockSignals(True)
            a.setChecked(state)
            a.blockSignals(False)
        self._update_monitor_button()
        self._render()

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
    def _reset(self, title: str, y_log: bool, y_label: str = "Value") -> None:
        self._plot.clear()
        self._legend.clear()  # avoid stale/duplicate legend entries on re-render
        self._plot.setTitle(title)
        self._plot.setLogMode(x=False, y=y_log)
        self._plot.setLabel("bottom", "Iteration")
        self._plot.setLabel("left", y_label)

    def _render(self) -> None:
        if self._mode == "single":
            self._render_single(self._current, self._selected_series())
        elif self._mode == "comparison":
            name, plots = self._current
            self._render_comparison(name, plots, self._selected_series())
        else:
            return
        # Re-fit the view to the freshly drawn data, overriding any manual
        # pan/zoom so the new selection is fully visible.
        self._plot.getViewBox().autoRange()

    def _render_single(self, plot: MonitorPlot, selected: set[str]) -> None:
        drawn = [s.name for s in plot.series if s.name in selected and self._visible(s)]
        self._reset(plot.name, plot.y_log, _y_label_for(drawn))
        # Keep each series' colour stable regardless of which are filtered out.
        for i, s in enumerate(plot.series):
            if s.name not in selected or not self._visible(s):
                continue
            self._plot.plot(
                s.x, s.y, name=s.name, pen=pg.mkPen(_COLORS[i % len(_COLORS)], width=1.5)
            )

    def _render_comparison(
        self, name: str, plots: list[tuple[str, MonitorPlot]], selected: set[str]
    ) -> None:
        y_log = any(p.y_log for _, p in plots)
        drawn = [
            s.name for _, p in plots for s in p.series
            if s.name in selected and self._visible(s)
        ]
        self._reset(f"{name} (comparison)", y_log, _y_label_for(drawn))
        for i, (sim_name, plot) in enumerate(plots):
            color = _COLORS[i % len(_COLORS)]
            for s in plot.series:
                if s.name not in selected or not self._visible(s):
                    continue
                label = f"{sim_name}: {s.name}" if len(plot.series) > 1 else sim_name
                self._plot.plot(s.x, s.y, name=label, pen=pg.mkPen(color, width=1.5))
