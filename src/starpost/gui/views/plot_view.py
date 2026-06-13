"""In-app monitor plot viewer (pyqtgraph). Residuals: log Y, multi-series.

Two modes:
  show_plots(plots)             — one sim's plots, each series a distinct color
  show_comparison(categories)   — each plot overlaid across sims for comparison

Beneath the plot sits one dropdown per displayed category (monitor plot),
labelled with the category's name. Each dropdown chooses which of that
category's series (monitors) are drawn — useful when a category bundles many,
or when several categories are overlaid at once.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
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

# How close (in pixels) the cursor must be to a data point for its hover
# readout to appear — keeps the tooltip from showing when nowhere near a line.
_HOVER_PX = 25.0

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


class _CategorySelector(QWidget):
    """A category name label beside a dropdown of its series (monitors).

    Each row beneath the plot is one of these; toggling any series emits
    `changed` so the view can redraw.
    """

    changed = Signal()

    def __init__(self, category: str, names: list[str], initial=None, parent=None) -> None:
        super().__init__(parent)
        self.category = category
        self._actions: dict[str, object] = {}

        self._btn = QToolButton()
        self._btn.setObjectName("monitorSelect")
        self._btn.setPopupMode(QToolButton.InstantPopup)
        self._menu = _StayOpenMenu(self._btn)
        self._btn.setMenu(self._menu)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._btn)

        self._populate(names, initial)

    def _populate(self, names: list[str], initial) -> None:
        self._menu.clear()
        self._actions = {}
        if names:
            self._menu.addAction("Select all").triggered.connect(
                lambda: self._set_all(True)
            )
            self._menu.addAction("Deselect all").triggered.connect(
                lambda: self._set_all(False)
            )
            self._menu.addSeparator()
        for n in names:
            act = self._menu.addAction(n)
            act.setCheckable(True)
            # No remembered choice (initial is None) → default to shown.
            act.setChecked(initial is None or n in initial)
            act.toggled.connect(self._on_toggled)
            self._actions[n] = act
        self._update_button()

    def _set_all(self, state: bool) -> None:
        for a in self._actions.values():
            a.blockSignals(True)
            a.setChecked(state)
            a.blockSignals(False)
        self._update_button()
        self.changed.emit()

    def _on_toggled(self, _checked: bool) -> None:
        self._update_button()
        self.changed.emit()

    def _update_button(self) -> None:
        total = len(self._actions)
        sel = len(self.selected())
        self._btn.setText(
            f"{self.category} ({sel}/{total})" if total else f"{self.category} (—)"
        )
        self._btn.setEnabled(total > 0)

    def selected(self) -> set[str]:
        return {n for n, a in self._actions.items() if a.isChecked()}


class PlotView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._legend = self._plot.addLegend()
        self._plot.showGrid(x=True, y=True, alpha=0.3)

        # Hover readout: a marker dot + a coordinate label pinned to the data
        # point nearest the cursor. Both are re-added after each clear().
        self._hover_marker = pg.ScatterPlotItem(
            size=9, pen=pg.mkPen("#222", width=1), brush=pg.mkBrush("#ffffff")
        )
        self._hover_text = pg.TextItem(anchor=(0, 1), fill=pg.mkBrush(34, 34, 34, 200))
        self._hover_marker.setZValue(100)
        self._hover_text.setZValue(101)
        # Drawn-curve data the hover search runs over: each is a dict with the
        # x/y arrays (originals, for display), display colour, and series name.
        self._curves: list[dict] = []
        self._plot.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # One category (series) selector per displayed plot, laid out in a row.
        self._ctrl = QHBoxLayout()
        self._selectors: dict[str, _CategorySelector] = {}
        # Remember each category's series selection so it survives redraws
        # (toggling another checkbox re-shows the view from scratch).
        self._selection_memory: dict[str, set[str]] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(self._plot, 1)
        layout.addLayout(self._ctrl)

        # What to re-render when the monitor selection changes.
        self._mode: str | None = None          # "single" | "comparison"
        self._current = None                    # list[MonitorPlot] | categories
        self._y_log = False                     # current Y-axis log state

        # Empty-monitor filtering (mirrors the Reports settings).
        self._hide_empty = True
        self._zero_threshold = 1e-5

        # Hover readout options.
        self._hover_show_name = True
        self._hover_x_decimals = 0
        self._hover_y_decimals = 4

        # Plot colours, kept in sync with the app's light/dark mode by
        # apply_theme. pyqtgraph isn't styled by the app's QSS, so the plot
        # background, axes and legend text are coloured here instead.
        self._fg = "#e6e6e6"
        self._bg = "#1e1e1e"
        self._title = ""
        self._y_axis_label = "Value"
        self._plot.setBackground(self._bg)

    # --- public entry points --------------------------------------------
    def apply_theme(self, mode: str) -> None:
        """Match the plot background, axes and legend text to the app's mode."""
        light = mode == "light"
        self._fg = "#1f1f1f" if light else "#e6e6e6"
        self._bg = "#ffffff" if light else "#1e1e1e"
        self._plot.setBackground(self._bg)
        for name in ("left", "bottom", "right", "top"):
            ax = self._plot.getAxis(name)
            ax.setPen(self._fg)
            ax.setTextPen(self._fg)
        self._legend.setLabelTextColor(self._fg)
        # Recolour the title and axis labels already on screen.
        self._plot.setTitle(self._title, color=self._fg)
        self._plot.setLabel("bottom", "Iteration", color=self._fg)
        self._plot.setLabel("left", self._y_axis_label, color=self._fg)
        # Rebuild the current plot so its legend entries pick up the new text
        # colour (existing legend labels aren't recoloured retroactively).
        if self._mode is not None:
            self._render()

    def set_filter(self, hide_empty: bool, zero_threshold: float) -> None:
        """Configure hiding of empty monitors (those whose values are all ~0).

        Re-shows the current plot so the change takes effect immediately.
        """
        self._hide_empty = hide_empty
        self._zero_threshold = zero_threshold
        self._reshow()

    def set_hover_options(
        self, show_name: bool, x_decimals: int = 0, y_decimals: int = 4
    ) -> None:
        """Configure the hover readout. When show_name is False the label shows
        only the coordinates, omitting the monitor's name. `x_decimals` and
        `y_decimals` set how many decimal places each coordinate is rounded to."""
        self._hover_show_name = show_name
        self._hover_x_decimals = max(0, x_decimals)
        self._hover_y_decimals = max(0, y_decimals)
        self._hide_hover()  # drop any stale label; it rebuilds on next hover

    def show_plots(self, plots: list[MonitorPlot]) -> None:
        """Draw one sim's monitor plots, overlaid; each is its own category."""
        self._mode = "single"
        self._current = plots
        self._set_categories(
            [(p.name, [s.name for s in p.series if self._visible(s)]) for p in plots]
        )
        self._render()

    def show_comparison(
        self, categories: list[tuple[str, list[tuple[str, MonitorPlot]]]]
    ) -> None:
        """categories: list of (plot_name, [(sim_name, MonitorPlot), ...]) — each
        plot overlaid across the sims that have it."""
        self._mode = "comparison"
        self._current = categories
        cat_series: list[tuple[str, list[str]]] = []
        for plot_name, pairs in categories:
            names: list[str] = []
            seen: set[str] = set()
            for _, p in pairs:
                for s in p.series:
                    if s.name not in seen and self._visible(s):
                        seen.add(s.name)
                        names.append(s.name)
            cat_series.append((plot_name, names))
        self._set_categories(cat_series)
        self._render()

    def clear(self) -> None:
        """Blank the view — e.g. when no plot is selected for display."""
        self._mode = None
        self._current = None
        self._set_categories([])
        self._plot.clear()
        self._legend.clear()
        self._title = ""
        self._plot.setTitle("", color=self._fg)
        self._curves = []
        self._hide_hover()

    # --- empty-monitor filtering ----------------------------------------
    def _visible(self, series) -> bool:
        """False for monitors filtered out by the hide-empty setting."""
        return not (self._hide_empty and _series_is_empty(series, self._zero_threshold))

    def _reshow(self) -> None:
        """Re-run the active show_* so a filter change rebuilds the menu/plot."""
        if self._mode == "single":
            self.show_plots(self._current)
        elif self._mode == "comparison":
            self.show_comparison(self._current)

    # --- category selectors ---------------------------------------------
    def _set_categories(self, cat_series: list[tuple[str, list[str]]]) -> None:
        """Rebuild the row of per-category dropdowns, preserving prior choices."""
        # Stash current choices so they carry across the teardown.
        for name, sel in self._selectors.items():
            self._selection_memory[name] = sel.selected()
        while self._ctrl.count():
            item = self._ctrl.takeAt(0)
            w = item.widget()
            if w is not None:
                # Reparent out first so the old row vanishes immediately rather
                # than lingering until the event loop processes deleteLater.
                w.setParent(None)
                w.deleteLater()
        self._selectors = {}

        for category, names in cat_series:
            remembered = self._selection_memory.get(category)
            initial = remembered & set(names) if remembered is not None else None
            sel = _CategorySelector(category, names, initial)
            sel.changed.connect(self._render)
            self._ctrl.addWidget(sel)
            self._selectors[category] = sel
        self._ctrl.addStretch(1)

    def _selected_series(self, category: str) -> set[str]:
        sel = self._selectors.get(category)
        return sel.selected() if sel is not None else set()

    # --- rendering -------------------------------------------------------
    def _reset(self, title: str, y_log: bool, y_label: str = "Value") -> None:
        self._plot.clear()
        self._legend.clear()  # avoid stale/duplicate legend entries on re-render
        self._title = title
        self._y_axis_label = y_label
        self._plot.setTitle(title, color=self._fg)
        self._plot.setLogMode(x=False, y=y_log)
        self._plot.setLabel("bottom", "Iteration", color=self._fg)
        self._plot.setLabel("left", y_label, color=self._fg)
        # clear() drops every item, including the hover overlay — re-add it
        # (hidden) and start collecting the freshly drawn curves.
        self._y_log = y_log
        self._curves = []
        self._hover_marker.setData([], [])
        self._hover_marker.hide()
        self._hover_text.hide()
        self._plot.addItem(self._hover_marker)
        self._plot.addItem(self._hover_text)

    def _render(self) -> None:
        if self._mode == "single":
            self._render_single(self._current)
        elif self._mode == "comparison":
            self._render_comparison(self._current)
        else:
            return
        # Re-fit the view to the freshly drawn data, overriding any manual
        # pan/zoom so the new selection is fully visible.
        self._plot.getViewBox().autoRange()

    def _render_single(self, plots: list[MonitorPlot]) -> None:
        drawn: list[str] = []
        specs: list[tuple] = []
        # A running colour index across every category's series keeps each
        # line's colour stable regardless of which are filtered/deselected.
        color_i = 0
        for plot in plots:
            selected = self._selected_series(plot.name)
            for s in plot.series:
                color = _COLORS[color_i % len(_COLORS)]
                color_i += 1
                if s.name not in selected or not self._visible(s):
                    continue
                drawn.append(s.name)
                specs.append((s.x, s.y, s.name, color))
        title = ", ".join(p.name for p in plots)
        self._reset(title, any(p.y_log for p in plots), _y_label_for(drawn))
        for x, y, name, color in specs:
            self._plot.plot(x, y, name=name, pen=pg.mkPen(color, width=1.5))
            self._record_curve(x, y, name, color)

    def _render_comparison(
        self, categories: list[tuple[str, list[tuple[str, MonitorPlot]]]]
    ) -> None:
        # Colour by sim, consistent across every category that has the sim.
        sim_order: list[str] = []
        for _, pairs in categories:
            for sim_name, _ in pairs:
                if sim_name not in sim_order:
                    sim_order.append(sim_name)
        sim_color = {s: _COLORS[i % len(_COLORS)] for i, s in enumerate(sim_order)}
        # Disambiguate the legend by series whenever more than one could appear.
        multi = len(categories) > 1 or any(
            len(p.series) > 1 for _, pairs in categories for _, p in pairs
        )

        drawn: list[str] = []
        specs: list[tuple] = []
        y_log = False
        for plot_name, pairs in categories:
            selected = self._selected_series(plot_name)
            for sim_name, plot in pairs:
                y_log = y_log or plot.y_log
                for s in plot.series:
                    if s.name not in selected or not self._visible(s):
                        continue
                    drawn.append(s.name)
                    label = f"{sim_name}: {s.name}" if multi else sim_name
                    specs.append((s.x, s.y, label, sim_color[sim_name]))
        title = ", ".join(name for name, _ in categories) + " (comparison)"
        self._reset(title, y_log, _y_label_for(drawn))
        for x, y, label, color in specs:
            self._plot.plot(x, y, name=label, pen=pg.mkPen(color, width=1.5))
            self._record_curve(x, y, label, color)

    # --- hover readout ---------------------------------------------------
    def _record_curve(self, x, y, name: str, color: str) -> None:
        """Stash a drawn line's data so the hover search can run over it."""
        self._curves.append(
            {
                "x": np.asarray(x, dtype=float),
                "y": np.asarray(y, dtype=float),
                "name": name,
                "color": color,
            }
        )

    def _view_y(self, y):
        """Map a data Y to the axis' view coordinate (log10 under log mode)."""
        return np.log10(y) if self._y_log else y

    def _on_mouse_moved(self, scene_pos) -> None:
        """Pin the readout to the data point nearest the cursor, in pixels."""
        vb = self._plot.getViewBox()
        if not self._curves or not self._plot.sceneBoundingRect().contains(scene_pos):
            self._hide_hover()
            return
        cursor_x = float(vb.mapSceneToView(scene_pos).x())
        sx, sy = scene_pos.x(), scene_pos.y()

        best = None  # (pixel_distance, x, y, color, name)
        for c in self._curves:
            xs, ys = c["x"], c["y"]
            if xs.size == 0:
                continue
            # The x arrays are monotonic iterations, so binary-search to the
            # nearest index and check it plus its neighbours — enough to find
            # the closest vertex without scanning the whole (possibly huge) line.
            i = int(np.searchsorted(xs, cursor_x))
            for j in (i - 1, i, i + 1):
                if j < 0 or j >= xs.size:
                    continue
                yj = ys[j]
                if self._y_log and yj <= 0:
                    continue  # not drawable on a log axis
                pt = vb.mapViewToScene(QPointF(float(xs[j]), float(self._view_y(yj))))
                d = math.hypot(pt.x() - sx, pt.y() - sy)
                if best is None or d < best[0]:
                    best = (d, float(xs[j]), float(yj), c["color"], c["name"])

        if best is None or best[0] > _HOVER_PX:
            self._hide_hover()
            return
        self._show_hover(*best[1:])

    def _show_hover(self, x: float, y: float, color: str, name: str) -> None:
        vy = float(self._view_y(y))
        self._hover_marker.setData([x], [vy], brush=pg.mkBrush(color))
        coords = f"{x:.{self._hover_x_decimals}f}, {y:.{self._hover_y_decimals}f}"
        label = f"{name}\n{coords}" if self._hover_show_name else coords
        self._hover_text.setText(label, color=color)
        self._hover_text.setPos(x, vy)
        self._hover_marker.show()
        self._hover_text.show()

    def _hide_hover(self) -> None:
        self._hover_marker.hide()
        self._hover_text.hide()
