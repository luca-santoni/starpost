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
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtWidgets import (
    QGraphicsRectItem,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
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


@dataclass(frozen=True)
class RegionStat:
    """One statistic reported for a Shift+drag region selection: a display
    label and a function over the in-region values (a 1-D float array).

    Add entries to ``REGION_STATS`` to surface more statistics — the region
    overlay renders whatever the list contains.
    """

    label: str
    compute: Callable[[np.ndarray], float]


# The catalog of statistics available for a selected region, in display order.
# Which of these actually show is chosen in Settings → Plots → Statistics.
# Extend this list to offer more, e.g. RegionStat("Sum", lambda v: float(v.sum())).
REGION_STATS: list[RegionStat] = [
    RegionStat("Avg", lambda v: float(np.mean(v))),
    RegionStat("Median", lambda v: float(np.median(v))),
    RegionStat("Std Dev", lambda v: float(np.std(v))),
    RegionStat("Var", lambda v: float(np.var(v))),
    RegionStat("Min", lambda v: float(np.min(v))),
    RegionStat("Max", lambda v: float(np.max(v))),
    RegionStat("Range", lambda v: float(np.ptp(v))),
]

# The catalog's labels, in order — the choices offered by the Statistics setting.
REGION_STAT_LABELS: list[str] = [s.label for s in REGION_STATS]

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


def _save_via_pillow(image, path) -> None:
    """Save a QImage through Pillow (for formats Qt can't write, e.g. TIFF). The
    QImage is round-tripped through PNG bytes, which Qt always supports."""
    from io import BytesIO

    from PIL import Image
    from PySide6.QtCore import QBuffer, QByteArray

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    Image.open(BytesIO(bytes(data))).save(str(path))


def _image_to_pdf(image, path) -> None:
    """Write a rendered QImage into a tightly-cropped (no-margin) PDF page."""
    from PySide6.QtCore import QMarginsF, QRect, QSizeF
    from PySide6.QtGui import QPageSize, QPainter, QPdfWriter

    dpi = 300
    writer = QPdfWriter(str(path))
    writer.setResolution(dpi)
    page = QSizeF(image.width() / dpi * 25.4, image.height() / dpi * 25.4)
    writer.setPageSize(QPageSize(page, QPageSize.Unit.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    painter = QPainter(writer)
    painter.drawImage(QRect(0, 0, writer.width(), writer.height()), image)
    painter.end()


class _CategorySelector(QWidget):
    """A category name label beside a dropdown of its series (monitors).

    Each row beneath the plot is one of these; toggling any series emits
    `changed` so the view can redraw.
    """

    changed = Signal()

    def __init__(
        self, category: str, names: list[str], initial=None,
        sort_mode: str | None = "az", parent=None,
    ) -> None:
        super().__init__(parent)
        self.category = category
        self._names = list(names)        # monitors in their natural (source) order
        self.sort_mode = sort_mode       # "az" (default) | "za" | None (natural)
        self._actions: dict[str, object] = {}

        self._btn = QToolButton()
        self._btn.setObjectName("monitorSelect")
        self._btn.setPopupMode(QToolButton.InstantPopup)
        self._menu = _StayOpenMenu(self._btn)
        self._btn.setMenu(self._menu)
        # Right-clicking the button offers A–Z / Z–A sorting of its monitors.
        self._btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self._btn.customContextMenuRequested.connect(self._show_sort_menu)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._btn)

        self._populate(initial)

    def _ordered_names(self) -> list[str]:
        """The monitor names in the active sort order."""
        if self.sort_mode == "az":
            return sorted(self._names, key=str.lower)
        if self.sort_mode == "za":
            return sorted(self._names, key=str.lower, reverse=True)
        return list(self._names)

    def _populate(self, initial) -> None:
        self._menu.clear()
        self._actions = {}
        names = self._ordered_names()
        if names:
            self._menu.addAction("Select all").triggered.connect(
                lambda: self._set_all(True)
            )
            self._menu.addAction("Deselect all").triggered.connect(
                lambda: self._set_all(False)
            )
            self._menu.addSeparator()
        for n in names:
            # Show the collapsed label; keep the real name as the action's key.
            act = self._menu.addAction(_display_name(n))
            act.setCheckable(True)
            # No remembered choice (initial is None) → default to hidden, so a
            # freshly selected group plots nothing until the user picks monitors.
            act.setChecked(initial is not None and n in initial)
            act.toggled.connect(self._on_toggled)
            self._actions[n] = act
        self._update_button()

    def _show_sort_menu(self, pos) -> None:
        """Right-click menu to reorder the monitors A–Z or Z–A (check state and
        which series are plotted are unaffected — only the menu order changes)."""
        menu = QMenu(self)
        az = menu.addAction("Sort A–Z")
        za = menu.addAction("Sort Z–A")
        for act, mode in ((az, "az"), (za, "za")):
            act.setCheckable(True)
            act.setChecked(self.sort_mode == mode)
        chosen = menu.exec(self._btn.mapToGlobal(pos))
        if chosen is az:
            self._resort("az")
        elif chosen is za:
            self._resort("za")

    def _resort(self, mode: str) -> None:
        if mode == self.sort_mode:
            return
        self.sort_mode = mode
        # Rebuild the menu in the new order, keeping the current selection.
        self._populate(self.selected())

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

    def set_selected(self, names) -> None:
        """Check exactly the series in `names` (others off), without emitting."""
        for n, a in self._actions.items():
            a.blockSignals(True)
            a.setChecked(n in names)
            a.blockSignals(False)
        self._update_button()

    def select_all(self) -> None:
        self.set_selected(set(self._actions))


class _RegionSelectViewBox(pg.ViewBox):
    """A ViewBox where Shift+left-drag rubber-bands a rectangular region and
    emits its data-space bounds, rather than panning. Without Shift, the usual
    pan/zoom behaviour is untouched.
    """

    # Emitted on drag release with the selected rectangle in data (view) coords;
    # a zero-area rectangle (a plain Shift+click) signals "clear the selection".
    region_selected = Signal(object)  # QRectF

    def mouseDragEvent(self, ev, axis=None) -> None:  # noqa: N802 (Qt override)
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if shift and ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            if ev.isFinish():
                self.rbScaleBox.hide()
                rect = QRectF(ev.buttonDownPos(), ev.pos())
                rect = self.childGroup.mapRectFromParent(rect).normalized()
                self.region_selected.emit(rect)
            else:
                # Reuse the built-in rubber-band box for live feedback.
                self.updateScaleBox(ev.buttonDownPos(), ev.pos())
        else:
            super().mouseDragEvent(ev, axis)


class _DraggableLabel(QLabel):
    """A QLabel the user can drag to reposition anywhere within its parent,
    clamped so it never leaves the parent's bounds."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.OpenHandCursor)
        self._grab: QPointF | None = None  # cursor offset within the label

    def set_position(self, pos) -> None:
        """Move to ``pos`` (parent coords), clamped to stay fully on-parent."""
        parent = self.parentWidget()
        if parent is not None:
            x = min(max(0, pos.x()), max(0, parent.width() - self.width()))
            y = min(max(0, pos.y()), max(0, parent.height() - self.height()))
            pos = pos.__class__(x, y)
        self.move(pos)

    def reclamp(self) -> None:
        """Re-apply the clamp to the current position (after a resize/relayout)."""
        self.set_position(self.pos())

    def mousePressEvent(self, ev) -> None:  # noqa: N802 (Qt override)
        if ev.button() == Qt.MouseButton.LeftButton:
            self._grab = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802 (Qt override)
        if self._grab is not None:
            delta = (ev.position() - self._grab).toPoint()
            self.set_position(self.pos() + delta)
            ev.accept()
        else:
            super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802 (Qt override)
        if self._grab is not None and ev.button() == Qt.MouseButton.LeftButton:
            self._grab = None
            self.setCursor(Qt.OpenHandCursor)
            ev.accept()
        else:
            super().mouseReleaseEvent(ev)


class PlotView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        pg.setConfigOptions(antialias=True)
        self._vb = _RegionSelectViewBox()
        self._plot = pg.PlotWidget(viewBox=self._vb)
        self._vb.region_selected.connect(self._on_region_selected)
        self._legend = self._plot.addLegend()
        self._plot.showGrid(x=True, y=True, alpha=0.3)

        # Hint shown centred over the plot when nothing is drawn. Kept subtle
        # (gray) and click-through so it never gets in the way. Parented to the
        # plot widget; re-centred via an event filter on the plot's resizes.
        self._empty_label = QLabel("Select a monitor to begin", self._plot)
        self._empty_label.setStyleSheet(
            "color: gray; background: transparent; font-size: 28px;"
        )
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._empty_label.adjustSize()
        self._plot.installEventFilter(self)

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

        # Shift+drag region selection: a shaded rectangle (in data coords, so it
        # tracks pan/zoom) plus a stats overlay pinned to the plot's top-left.
        # Which statistics the table reports (labels into REGION_STATS); set from
        # Settings via set_region_stats. Defaults to the original three.
        self._region_rect: QRectF | None = None
        self._enabled_stats: list[str] = ["Avg", "Std Dev", "Range"]
        self._region_item = QGraphicsRectItem()
        self._region_item.setPen(
            pg.mkPen("#5aa9e6", width=1, style=Qt.PenStyle.DashLine)
        )
        self._region_item.setBrush(pg.mkBrush(90, 169, 230, 45))
        self._region_item.setZValue(50)
        self._region_item.hide()
        self._plot.addItem(self._region_item)
        # Draggable so it can be moved off the data; starts at the top-left.
        self._stats_label = _DraggableLabel(self._plot)
        self._stats_label.setTextFormat(Qt.RichText)
        self._stats_label.setToolTip("Drag to move")
        self._stats_label.move(58, 8)
        self._stats_label.hide()

        # One category (series) selector per displayed plot, laid out in a row.
        # The row can be hidden (e.g. the export preview drives the series
        # selection from elsewhere) while the selectors still hold the state.
        self._ctrl = QHBoxLayout()
        self._selectors: dict[str, _CategorySelector] = {}
        self._category_controls_visible = True
        # Remember each category's series selection so it survives redraws
        # (toggling another checkbox re-shows the view from scratch).
        self._selection_memory: dict[str, set[str]] = {}
        # Likewise remember each category's chosen monitor sort order.
        self._sort_memory: dict[str, str | None] = {}

        # "Clear selection" sits at the bottom-right, past the category
        # dropdowns; enabled only while a Shift+drag region is active.
        self._clear_sel_btn = QPushButton("Clear selection")
        self._clear_sel_btn.setEnabled(False)
        self._clear_sel_btn.clicked.connect(self._clear_region)

        bottom = QHBoxLayout()
        bottom.addLayout(self._ctrl, 1)
        bottom.addWidget(self._clear_sel_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._plot, 1)
        layout.addLayout(bottom)

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
        # Effective labels currently on the plot, and the auto-derived values they
        # fall back to. A non-empty override (set externally, e.g. from the export
        # menu) replaces the auto value; clearing it reverts to auto.
        self._title = ""
        self._x_axis_label = "Iteration"
        self._y_axis_label = "Value"
        self._auto_title = ""
        self._auto_x_label = "Iteration"
        self._auto_y_label = "Value"
        self._title_override = ""
        self._x_label_override = ""
        self._y_label_override = ""
        # Per-series colour overrides (raw series name -> hex), and the colours
        # actually drawn last render (raw series name -> hex) for read-back.
        self._series_colors: dict[str, str] = {}
        self._drawn_colors: dict[str, str] = {}
        self._plot.setBackground(self._bg)
        self._style_stats_label()

    # --- public entry points --------------------------------------------
    def apply_theme(self, mode: str) -> None:
        """Match the plot background, axes and legend text to the app's mode."""
        light = mode == "light"
        self._fg = "#1f1f1f" if light else "#e6e6e6"
        self._bg = "#ffffff" if light else "#1e1e1e"
        self._plot.setBackground(self._bg)
        self._style_stats_label()
        for name in ("left", "bottom", "right", "top"):
            ax = self._plot.getAxis(name)
            ax.setPen(self._fg)
            ax.setTextPen(self._fg)
        self._legend.setLabelTextColor(self._fg)
        # Recolour the title and axis labels already on screen.
        self._refresh_labels()
        # Rebuild the current plot so its legend entries pick up the new text
        # colour (existing legend labels aren't recoloured retroactively).
        if self._mode is not None:
            self._render()

    def _refresh_labels(self) -> None:
        """Push the effective title and axis labels (override if set, else the
        auto-derived value) onto the plot in the current foreground colour."""
        self._title = self._title_override or self._auto_title
        self._x_axis_label = self._x_label_override or self._auto_x_label
        self._y_axis_label = self._y_label_override or self._auto_y_label
        self._plot.setTitle(self._title, color=self._fg)
        self._plot.setLabel("bottom", self._x_axis_label, color=self._fg)
        self._plot.setLabel("left", self._y_axis_label, color=self._fg)

    def set_title_override(self, text: str) -> None:
        """Override the plot title (empty reverts to the auto title)."""
        self._title_override = text or ""
        self._refresh_labels()

    def set_x_label_override(self, text: str) -> None:
        """Override the X-axis label (empty reverts to the auto label)."""
        self._x_label_override = text or ""
        self._refresh_labels()

    def set_y_label_override(self, text: str) -> None:
        """Override the Y-axis label (empty reverts to the auto label)."""
        self._y_label_override = text or ""
        self._refresh_labels()

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

    def set_region_stats(self, labels) -> None:
        """Choose which statistics the region table shows, by label. Columns
        render in REGION_STATS catalog order regardless of the order given.
        Refreshes the table immediately if a region is currently selected."""
        self._enabled_stats = list(labels)
        if self._region_rect is not None:
            self._show_region_stats(self._region_rect)

    def region_stats(self) -> list[str]:
        """The statistics currently shown in the region table (for profiles)."""
        return list(self._enabled_stats)

    # --- per-series colours ---------------------------------------------
    def series_color(self, name: str) -> str | None:
        """The colour a monitor (raw series name) is drawn in, or its override if
        it isn't currently on screen; None if unknown."""
        return self._drawn_colors.get(name) or self._series_colors.get(name)

    def set_series_color(self, name: str, color: str) -> None:
        """Override a monitor's plot colour and redraw."""
        self._series_colors[name] = color
        if self._mode is not None:
            self._render()

    # --- export ----------------------------------------------------------
    def has_content(self) -> bool:
        """True when at least one curve is currently drawn."""
        return bool(self._curves)

    def export(self, path, fmt: str, scale: float = 3.0) -> None:
        """Render just the plot (graph, title, axes, legend — none of the
        surrounding controls) to ``path`` in ``fmt`` (png | jpg | tiff | pdf).

        The plot widget is captured at ``scale``× device-pixel-ratio rather than
        by upscaling the scene: that keeps line widths, legend and fonts in the
        same proportion as the on-screen preview (pyqtgraph's image exporter
        leaves cosmetic pens and the legend at a fixed pixel size when upscaled),
        while still producing a high-resolution image."""
        from PySide6.QtGui import QColor, QImage, QPainter  # noqa: F401
        from PySide6.QtWidgets import QWidget

        src = self._plot
        w = max(src.width(), 1)
        h = max(src.height(), 1)
        image = QImage(round(w * scale), round(h * scale), QImage.Format.Format_ARGB32)
        image.setDevicePixelRatio(scale)
        image.fill(QColor(self._bg))
        # Explicit QWidget.render (not QGraphicsView.render) — capture the widget
        # as drawn, honouring the image's device-pixel-ratio.
        QWidget.render(src, image)

        if fmt.lower() == "pdf":
            _image_to_pdf(image, path)
        elif not image.save(str(path)):
            # Qt couldn't write this format (e.g. TIFF often lacks a plugin);
            # fall back to Pillow, which infers the format from the extension.
            _save_via_pillow(image, path)

    # --- monitor selection (persisted in profiles) ----------------------
    def monitor_selection(self) -> dict[str, list[str]]:
        """The series (monitors) currently shown, keyed by monitor group name.

        Covers every group seen this session — both the live dropdowns and the
        remembered choices for groups not currently on screen.
        """
        for name, sel in self._selectors.items():
            self._selection_memory[name] = sel.selected()
        return {k: sorted(v) for k, v in self._selection_memory.items()}

    def set_monitor_selection(self, selection: dict[str, list[str]]) -> None:
        """Restore which series are shown per monitor group (profile loading).

        Groups absent from `selection` fall back to showing all their monitors.
        """
        self._selection_memory = {k: set(v) for k, v in selection.items()}
        for name, sel in self._selectors.items():
            if name in self._selection_memory:
                sel.set_selected(self._selection_memory[name])
            else:
                sel.select_all()
        if self._mode is not None:
            self._render()

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
        # No plot, so the auto title is empty; any user title override still shows.
        self._auto_title = ""
        self._refresh_labels()
        self._curves = []
        self._hide_hover()
        self._clear_region()
        self._update_empty_label()

    # --- "select a monitor" hint ----------------------------------------
    def _update_empty_label(self) -> None:
        """Show the centred hint only while nothing is plotted."""
        self._empty_label.setVisible(not self._curves)
        self._center_empty_label()

    def _center_empty_label(self) -> None:
        self._empty_label.adjustSize()
        x = (self._plot.width() - self._empty_label.width()) // 2
        y = (self._plot.height() - self._empty_label.height()) // 2
        self._empty_label.move(x, y)

    def eventFilter(self, obj, event):
        # Keep the hint centred and the stats panel on-plot as it's resized.
        if obj is self._plot and event.type() == QEvent.Type.Resize:
            self._center_empty_label()
            self._stats_label.reclamp()
        return super().eventFilter(obj, event)

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
            self._sort_memory[name] = sel.sort_mode
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
            sel = _CategorySelector(
                category, names, initial, self._sort_memory.get(category, "az")
            )
            sel.changed.connect(self._render)
            sel.setVisible(self._category_controls_visible)
            self._ctrl.addWidget(sel)
            self._selectors[category] = sel
        self._ctrl.addStretch(1)

    def set_category_controls_visible(self, visible: bool) -> None:
        """Show or hide the per-category series dropdowns. Hidden selectors still
        hold the selection (set via set_monitor_selection), so the plot can be
        driven entirely from elsewhere — e.g. the export menu's Monitors list."""
        self._category_controls_visible = visible
        for sel in self._selectors.values():
            sel.setVisible(visible)

    def _selected_series(self, category: str) -> set[str]:
        sel = self._selectors.get(category)
        return sel.selected() if sel is not None else set()

    # --- rendering -------------------------------------------------------
    def _reset(self, title: str, y_log: bool, y_label: str = "Value") -> None:
        self._plot.clear()
        self._legend.clear()  # avoid stale/duplicate legend entries on re-render
        self._auto_title = title
        self._auto_x_label = "Iteration"
        self._auto_y_label = y_label
        self._plot.setLogMode(x=False, y=y_log)
        self._refresh_labels()  # applies any overrides over the auto values
        # clear() drops every item, including the hover overlay — re-add it
        # (hidden) and start collecting the freshly drawn curves.
        self._y_log = y_log
        self._curves = []
        self._hover_marker.setData([], [])
        self._hover_marker.hide()
        self._hover_text.hide()
        self._plot.addItem(self._hover_marker)
        self._plot.addItem(self._hover_text)
        # A new render invalidates any region selection; drop it and re-attach
        # the (hidden) rectangle that _plot.clear() just removed.
        self._clear_region()
        self._plot.addItem(self._region_item)

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
        # Reveal the hint when the selection ended up drawing nothing.
        self._update_empty_label()

    def _render_single(self, plots: list[MonitorPlot]) -> None:
        drawn: list[str] = []
        specs: list[tuple] = []
        self._drawn_colors = {}
        # A running colour index across every category's series keeps each
        # line's colour stable regardless of which are filtered/deselected.
        color_i = 0
        for plot in plots:
            selected = self._selected_series(plot.name)
            for s in plot.series:
                default = _COLORS[color_i % len(_COLORS)]
                color_i += 1
                if s.name not in selected or not self._visible(s):
                    continue
                color = self._series_colors.get(s.name, default)
                self._drawn_colors[s.name] = color
                drawn.append(s.name)
                specs.append((s.x, s.y, s.name, color))
        title = ", ".join(p.name for p in plots)
        self._reset(title, any(p.y_log for p in plots), _y_label_for(drawn))
        for x, y, name, color in specs:
            label = _display_name(name)
            self._plot.plot(x, y, name=label, pen=pg.mkPen(color, width=1.5))
            self._record_curve(x, y, label, color)

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
        self._drawn_colors = {}
        y_log = False
        for plot_name, pairs in categories:
            selected = self._selected_series(plot_name)
            for sim_name, plot in pairs:
                y_log = y_log or plot.y_log
                for s in plot.series:
                    if s.name not in selected or not self._visible(s):
                        continue
                    # A per-series override forces that monitor's colour across
                    # every sim; otherwise comparison colours by sim.
                    color = self._series_colors.get(s.name, sim_color[sim_name])
                    self._drawn_colors[s.name] = color
                    drawn.append(s.name)
                    disp = _display_name(s.name)
                    label = f"{sim_name}: {disp}" if multi else sim_name
                    specs.append((s.x, s.y, label, color))
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

    # --- region statistics (Shift+drag) ---------------------------------
    def _style_stats_label(self) -> None:
        """Theme the region-stats overlay: legible text on a translucent panel."""
        panel = "rgba(255,255,255,225)" if self._bg == "#ffffff" else "rgba(30,30,30,215)"
        self._stats_label.setStyleSheet(
            f"color: {self._fg}; background: {panel};"
            " padding: 6px 8px; border-radius: 4px;"
        )

    def _clear_region(self) -> None:
        """Drop any active region selection and its stats overlay."""
        self._region_rect = None
        self._region_item.hide()
        self._stats_label.hide()
        self._clear_sel_btn.setEnabled(False)

    def _on_region_selected(self, rect: QRectF) -> None:
        """Handle a Shift+drag: a real rectangle shows stats; a zero-area drag
        (a plain Shift+click) clears the current selection."""
        if rect.width() <= 0 or rect.height() <= 0 or not self._curves:
            self._clear_region()
            return
        self._region_rect = rect
        self._region_item.setRect(rect)
        self._region_item.show()
        self._show_region_stats(rect)
        self._clear_sel_btn.setEnabled(True)

    def _region_values(self, curve: dict, rect: QRectF):
        """The curve's Y values whose points fall inside the rectangle (in view
        space for Y, matching how the rect was captured under log mode)."""
        xs, ys = curve["x"], curve["y"]
        if xs.size == 0:
            return None
        vy = self._view_y(ys)
        with np.errstate(invalid="ignore"):
            inside = (
                (xs >= rect.left()) & (xs <= rect.right())
                & (vy >= rect.top()) & (vy <= rect.bottom())
            )
        vals = ys[inside]
        return vals if vals.size else None

    def _show_region_stats(self, rect: QRectF) -> None:
        """Render the per-series statistics for the selected region as a table:
        one row per series, one column per statistic (plus the point count)."""
        xd = self._hover_x_decimals
        yd = self._hover_y_decimals
        enabled = set(self._enabled_stats)
        active = [st for st in REGION_STATS if st.label in enabled]
        rows: list[str] = []
        for c in self._curves:
            vals = self._region_values(c, rect)
            if vals is None:
                continue
            cells = "".join(
                f'<td align="right">{st.compute(vals):.{yd}f}</td>'
                for st in active
            )
            rows.append(
                "<tr>"
                f'<td><font color="{c["color"]}">{c["name"]}</font></td>'
                f"{cells}"
                f'<td align="right">{vals.size}</td>'
                "</tr>"
            )
        title = (
            f"<b>Region</b> &nbsp; x [{rect.left():.{xd}f}, {rect.right():.{xd}f}]"
        )
        if rows:
            heads = "".join(f'<th align="right">{st.label}</th>' for st in active)
            table = (
                '<table cellspacing="0" cellpadding="4">'
                f'<tr><th align="left">Series</th>{heads}<th align="right">n</th></tr>'
                f'{"".join(rows)}'
                "</table>"
            )
            body = table
        else:
            body = "No data points in region."
        self._stats_label.setText(f"{title}{body}")
        self._stats_label.adjustSize()
        # Keep the user's chosen position; just clamp it on-plot after resizing
        # to the new content.
        self._stats_label.reclamp()
        self._stats_label.show()
        self._stats_label.raise_()
