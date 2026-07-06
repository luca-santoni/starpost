"""Run-batch dialog: a sequential, tabbed wizard for configuring a batch run.

Five tabs (Source → Reports → Plots → Scenes → Summary), styled like the Export
dialog's tabs. The user advances with the bottom-right **Continue** button, which
becomes **Batch run** on the final Summary tab. The tab contents and the actual
run wiring are filled in later — this is the navigation scaffold only.
"""
from __future__ import annotations

import math
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEventLoop,
    QObject,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionViewItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from starpost.core.settings import BatchProfile, list_batch_profiles
from starpost.core.starccm_runner import StarRunner
from starpost.data.models import PlotKind, SimResult
from starpost.gui.theme import _DARK, _LIGHT, normalize_accent
from starpost.gui.views.export_dialog import (
    _AXIS_LABEL_PT_DEFAULT,
    _AXIS_LABEL_PT_MAX,
    _AXIS_LABEL_PT_MIN,
    _LINE_WIDTH_DEFAULT,
    _LINE_WIDTH_MAX,
    _LINE_WIDTH_MIN,
    _PreviewWindow,
    _SWATCH_GAP,
    _SWATCH_ROLE,
    _SWATCH_SIZE,
    _TITLE_PT_DEFAULT,
    _TITLE_PT_MAX,
    _TITLE_PT_MIN,
)
from starpost.gui.views.plot_view import (
    _COLORS,
    PlotView,
    _display_name,
    _series_is_empty,
)
from starpost.gui.views.selection_panel import _SceneTree
from starpost.gui.widgets import (
    UniformTabBar,
    enable_check_range,
    enable_range_selection,
)

_TAB_NAMES = ["Source", "Reports", "Plots", "Scenes", "Summary"]


class _LockedTabBar(UniformTabBar):
    """A tab bar the user cannot drive: mouse and keyboard tab changes are
    swallowed, so the active tab moves only programmatically (the Continue
    button). The tabs still render normally."""

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.ignore()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.ignore()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.ignore()


class _CheckableList(QListWidget):
    """A checkable list where clicking anywhere on a row toggles its checkbox
    (not just the small indicator), and clicking empty space clears the
    selection — matching the app's other checklists."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        enable_check_range(self)  # Shift+click ticks a range

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        pos = event.position().toPoint()
        item = self.itemAt(pos)
        if item is None:
            # Empty space: drop the selection so no row keeps the accent fill.
            self.clearSelection()
            self.setCurrentItem(None)
        elif (
            event.button() == Qt.MouseButton.LeftButton
            and bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
            and not self._on_check_indicator(item, pos)
        ):
            item.setCheckState(
                Qt.CheckState.Unchecked
                if item.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
        super().mousePressEvent(event)

    def _on_check_indicator(self, item, pos) -> bool:
        """Whether ``pos`` falls on the row's checkbox indicator (the native
        handler already toggles that, so we must not toggle again there)."""
        opt = QStyleOptionViewItem()
        opt.initFrom(self)
        opt.rect = self.visualItemRect(item)
        opt.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        rect = self.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, self
        )
        return rect.contains(pos)


class _MonitorTree(QTreeWidget):
    """A tree of monitor groups (checkable) whose monitors are checkable children.
    Checking a group reveals its monitors unchecked so the user picks them
    deliberately — except auto-select groups (residuals), whose monitors are all
    checked at once. The checked monitors per group drive what is plotted."""

    changed = Signal()
    swatch_clicked = Signal(object, int)  # the monitor item, and which swatch

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setItemsExpandable(False)
        self.setExpandsOnDoubleClick(False)
        self.setSelectionMode(self.SelectionMode.NoSelection)
        enable_check_range(self)  # Shift+click ticks a range (per tree level)
        # Groups whose monitors are all checked when the group is ticked
        # (residual plots), so the whole set plots together.
        self._auto_select_groups: set[str] = set()
        self.itemChanged.connect(self._on_item_changed)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # A click on a monitor's colour swatch opens its colour menu instead of
        # toggling the checkbox; everything else falls through to the default.
        pos = event.position().toPoint()
        item = self.itemAt(pos)
        if item is not None and item.parent() is not None:
            for i, rect in enumerate(self._swatch_rects(item)):
                if rect.contains(pos):
                    self.swatch_clicked.emit(item, i)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def _swatch_rects(self, item) -> list[QRect]:
        """The clickable band of each colour swatch, just right of the checkbox.
        Empty when the monitor has no swatch (unchecked / not drawn)."""
        colors = item.data(0, _SWATCH_ROLE)
        if not colors:
            return []
        item_rect = self.visualRect(self.indexFromItem(item, 0))
        opt = QStyleOptionViewItem()
        opt.initFrom(self)
        opt.rect = item_rect
        opt.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        opt.checkState = item.checkState(0)
        check = self.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, self
        )
        start = check.right() + 2  # where the swatch icon begins
        return [
            QRect(
                start + i * (_SWATCH_SIZE + _SWATCH_GAP),
                item_rect.top(), _SWATCH_SIZE, item_rect.height(),
            )
            for i in range(len(colors))
        ]

    def set_auto_select_groups(self, names) -> None:
        self._auto_select_groups = set(names)

    def set_groups(self, groups: dict[str, list[str]]) -> None:
        self.blockSignals(True)
        self.clear()
        for group in sorted(groups, key=str.lower):
            gi = QTreeWidgetItem([group])
            gi.setFlags((gi.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        & ~Qt.ItemFlag.ItemIsSelectable)
            gi.setCheckState(0, Qt.CheckState.Unchecked)
            for monitor in sorted(groups[group], key=str.lower):
                # Show the collapsed label (STAR-CCM+ doubles single-monitor
                # series names), but keep the raw series name as the lookup key.
                mi = QTreeWidgetItem([_display_name(monitor)])
                mi.setData(0, Qt.ItemDataRole.UserRole, monitor)
                mi.setFlags((mi.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                            & ~Qt.ItemFlag.ItemIsSelectable)
                mi.setCheckState(0, Qt.CheckState.Unchecked)
                gi.addChild(mi)
            self.addTopLevelItem(gi)
            gi.setExpanded(False)
        self.blockSignals(False)

    def _on_item_changed(self, item, _column) -> None:
        if item.parent() is None:  # a group
            checked = item.checkState(0) == Qt.CheckState.Checked
            item.setExpanded(checked)
            # Residual (auto-select) groups check all their monitors when ticked;
            # other groups reveal them unchecked. Unticking a group clears them.
            auto = checked and item.text(0) in self._auto_select_groups
            state = Qt.CheckState.Checked if auto else Qt.CheckState.Unchecked
            self.blockSignals(True)
            for j in range(item.childCount()):
                item.child(j).setCheckState(0, state)
            self.blockSignals(False)
        self.changed.emit()

    def checked_monitors(self) -> dict[str, list[str]]:
        """The checked monitors per checked group (unchecked groups omitted)."""
        out: dict[str, list[str]] = {}
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            g = root.child(i)
            if g.checkState(0) != Qt.CheckState.Checked:
                continue
            out[g.text(0)] = [
                g.child(j).data(0, Qt.ItemDataRole.UserRole)
                for j in range(g.childCount())
                if g.child(j).checkState(0) == Qt.CheckState.Checked
            ]
        return out

    def set_selection(self, selection: dict[str, list[str]]) -> None:
        """Check exactly the groups/monitors named in ``selection`` (raw monitor
        names, as returned by :meth:`checked_monitors`), clearing everything
        else, and emit ``changed`` once. Inverse of :meth:`checked_monitors`."""
        self.blockSignals(True)
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            g = root.child(i)
            wanted = selection.get(g.text(0))
            g.setCheckState(
                0, Qt.CheckState.Checked if wanted is not None
                else Qt.CheckState.Unchecked
            )
            g.setExpanded(wanted is not None)
            want = set(wanted or [])
            for j in range(g.childCount()):
                mi = g.child(j)
                on = mi.data(0, Qt.ItemDataRole.UserRole) in want
                mi.setCheckState(
                    0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
                )
        self.blockSignals(False)
        self.changed.emit()


class _BusyBar(QProgressBar):
    """An indeterminate progress bar that animates a sliding accent segment at
    ~60 fps, painted ourselves so the motion isn't capped at the Qt style's busy
    frame rate. Track and segment colours follow the app theme and accent."""

    _SEGMENT_FRAC = 0.30   # segment width as a fraction of the track width
    _STEP = 0.014          # phase advanced per frame (~1.2 s per sweep)

    def __init__(self, accent: str, mode: str, parent=None) -> None:
        super().__init__(parent)
        self.setRange(0, 0)  # busy/indeterminate
        self.setTextVisible(False)
        self.setMinimumHeight(18)
        palette = _LIGHT if mode == "light" else _DARK
        self._track = QColor(palette["input_bg"])
        self._border = QColor(palette["border"])
        self._accent = QColor(normalize_accent(accent))
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 fps
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self) -> None:
        self._phase = (self._phase + self._STEP) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 4.0
        track = QPainterPath()
        track.addRoundedRect(rect, radius, radius)
        p.fillPath(track, self._track)
        # Sliding accent segment, clipped to the rounded track so its corners
        # stay inside as it slides on and off each edge.
        p.setClipPath(track)
        seg_w = max(24.0, rect.width() * self._SEGMENT_FRAC)
        x = rect.left() - seg_w + self._phase * (rect.width() + seg_w)
        seg = QPainterPath()
        seg.addRoundedRect(
            QRectF(x, rect.top() + 1.0, seg_w, rect.height() - 2.0), radius, radius
        )
        p.fillPath(seg, self._accent)
        p.setClipping(False)
        p.setPen(QPen(self._border, 1.0))
        p.drawPath(track)
        p.end()


class _SavedPlotPropertiesDialog(QDialog):
    """Read-only properties for a saved plot: its title, axis labels, theme and
    file format, plus the monitors it draws shown with their colours."""

    def __init__(self, name: str, data: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Properties — {name}")

        def _or_dash(text: str) -> str:
            return text if text else "—"

        def _pt(v) -> str:
            return f"{v} pt" if v is not None else "—"

        def _scale(v) -> str:
            return f"{round(v, 2):g}×" if v is not None else "—"

        def _px(v) -> str:
            return f"{v:g} px" if v is not None else "—"

        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.addRow("Plot title:", QLabel(_or_dash(data.get("title", ""))))
        form.addRow("Title size:", QLabel(_pt(data.get("title_size"))))
        form.addRow("X axis label:", QLabel(_or_dash(data.get("x_label", ""))))
        form.addRow("Y axis label:", QLabel(_or_dash(data.get("y_label", ""))))
        form.addRow("Axis label size:", QLabel(_pt(data.get("axis_label_size"))))
        form.addRow("Aspect ratio:", QLabel(_or_dash(data.get("aspect", ""))))
        form.addRow("Theme:", QLabel((data.get("theme") or "").capitalize() or "—"))
        form.addRow("Legend scale:", QLabel(_scale(data.get("legend_scale"))))
        form.addRow("Line thickness:", QLabel(_px(data.get("line_width"))))
        form.addRow("File format:", QLabel(_or_dash(data.get("format", ""))))

        layout = QVBoxLayout(self)
        layout.addLayout(form)

        monitors_label = QLabel("Monitors")
        monitors_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(monitors_label)

        monitors = data.get("monitors") or {}
        colors = data.get("monitor_colors") or {}
        series = [s for group in monitors.values() for s in group]
        if series:
            for s in series:
                layout.addLayout(self._monitor_row(s, colors.get(s)))
        else:
            layout.addWidget(QLabel("—"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "Close this window"
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _monitor_row(series: str, color: str | None) -> QHBoxLayout:
        """A monitor's colour swatch and (collapsed) label, with the hex value."""
        row = QHBoxLayout()
        swatch = QLabel()
        swatch.setFixedSize(14, 14)
        fill = f"background: {color}; " if color else ""
        swatch.setStyleSheet(
            f"{fill}border: 1px solid rgba(127, 127, 127, 0.5); border-radius: 3px;"
        )
        row.addWidget(swatch)
        label = _display_name(series)
        row.addWidget(QLabel(f"{label}  ({color})" if color else label))
        row.addStretch(1)
        return row


class _SavedScenePropertiesDialog(QDialog):
    """Read-only properties for a saved scene: its image resolution and format,
    the saved camera views it renders, and the scenes it captures shown with
    their checked displayers."""

    def __init__(self, name: str, data: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Properties — {name}")

        def _or_dash(text: str) -> str:
            return text if text else "—"

        def _wrap(text: str) -> QLabel:
            """A value label that wraps long text onto further lines instead of
            stretching the window wide."""
            label = QLabel(text)
            label.setWordWrap(True)
            label.setMaximumWidth(420)
            return label

        # A single form so every label column aligns (image options, saved views
        # and the per-scene rows all share one label width).
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.addRow(
            "Image resolution:", QLabel(_or_dash(data.get("resolution", "")))
        )
        form.addRow(
            "Image format:",
            QLabel((data.get("format") or "").upper() or "—"),
        )
        views = data.get("views") or []
        form.addRow("Saved views:", _wrap(", ".join(views) if views else "—"))

        displayers = data.get("displayers") or {}
        if displayers:
            for scene, shown in displayers.items():
                form.addRow("Scene:", _wrap(scene))
                if shown:
                    for d in shown:
                        form.addRow("Vector/Scalar name:", _wrap(d))
                else:
                    form.addRow("Vector/Scalar name:", _wrap("(all displayers)"))
        else:
            form.addRow(QLabel("—"))

        layout = QVBoxLayout(self)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "Close this window"
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class _ExtractWorker(QObject):
    """Runs a single .sim extraction off the GUI thread so the setup progress
    dialog keeps painting (and its bar animating) while STAR-CCM+ works."""

    done = Signal()  # extraction finished; the result is on ``self.result``

    def __init__(self, runner: StarRunner, sim: Path, out_dir: Path) -> None:
        super().__init__()
        self._runner = runner
        self._sim = sim
        self._out_dir = out_dir
        self.result: SimResult | None = None

    def run(self) -> None:
        try:
            self.result = self._runner.extract(self._sim, self._out_dir)
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            self.result = SimResult(sim_path=str(self._sim), error=str(e))
        self.done.emit()


class _BatchRunWorker(QObject):
    """Runs the whole batch off the GUI thread so the event loop stays alive (the
    progress dialog paints/animates, the file dialog tears down). The subprocess
    steps (extraction, scene rendering) and file I/O run here; each saved plot,
    which needs a Qt widget, is rendered back on the GUI thread via
    ``render_request`` while this thread waits."""

    progress = Signal(float, str)                    # (fraction 0..1, message)
    render_request = Signal(object, object, object)  # (result, plot_data, path)
    done = Signal()                                  # result on .result / .error

    def __init__(self, config, settings, runner, dest: Path) -> None:
        super().__init__()
        self._config = config
        self._settings = settings
        self._runner = runner
        self._dest = dest
        self.result: Path | None = None
        self.error: str | None = None
        # Hand-off for a single GUI-thread plot render at a time.
        self._render_done = threading.Event()
        self._render_result = False

    def run(self) -> None:
        from starpost.batch.run import build_batch_archive

        try:
            self.result = build_batch_archive(
                self._config, self._settings, self._runner, self._dest,
                progress=self.progress.emit,
                plot_renderer=self._render_plot,
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            self.error = str(exc)
        self.done.emit()

    def _render_plot(self, result, plot_data, path) -> bool:
        """On the worker thread: ask the GUI thread to render, then block until it
        signals completion via :meth:`finish_render`."""
        self._render_done.clear()
        self.render_request.emit(result, plot_data, path)
        self._render_done.wait()
        return self._render_result

    def finish_render(self, rendered: bool) -> None:
        """Called on the GUI thread once a plot has been rendered; wakes run()."""
        self._render_result = rendered
        self._render_done.set()


class _BatchProgressReceiver(QObject):
    """Hosts the progress/render slots on a QObject constructed on the GUI
    thread (and never moved), so Qt's auto connection type resolves
    ``worker.progress``/``worker.render_request`` to queued connections —
    connecting to a context-less plain function instead would make Qt pick a
    direct connection, running the slot on the worker thread. That matters
    for the render slot: ``render_saved_plot`` builds a ``PlotView`` (a Qt
    widget), which must be constructed on the GUI thread."""

    def __init__(
        self, busy: QProgressDialog, settings, worker: "_BatchRunWorker"
    ) -> None:
        super().__init__()
        self._busy = busy
        self._settings = settings
        self._worker = worker

    def on_progress(self, fraction: float, message: str) -> None:
        self._busy.setValue(round(fraction * 100))
        self._busy.setLabelText(message)

    def on_render(self, result, plot_data, path) -> None:
        from starpost.batch.run import render_saved_plot

        rendered = False
        try:
            rendered = render_saved_plot(result, plot_data, self._settings, path)
        finally:
            self._worker.finish_render(rendered)


def execute_batch(parent, config, settings, runner, dest) -> str | None:
    """Run ``config`` behind a modal progress dialog on a worker thread, rendering
    saved plots back on the GUI thread (Qt widgets can't be built off it). Returns
    the worker's error string, or None on success. Blocks (a local event loop)
    while the modal progress dialog stays painted."""
    busy = QProgressDialog("Preparing…", "", 0, 100, parent)
    busy.setWindowTitle("Run batch")
    busy.setCancelButton(None)
    busy.setWindowModality(Qt.WindowModality.WindowModal)
    busy.setMinimumDuration(0)
    busy.setAutoClose(False)
    busy.setAutoReset(False)
    busy.setValue(0)

    thread = QThread(parent)
    worker = _BatchRunWorker(config, settings, runner, dest)
    worker.moveToThread(thread)

    # Constructed here (GUI thread) and never moved, so its bound-method slots
    # connect queued and run back on the GUI thread — see the class docstring.
    receiver = _BatchProgressReceiver(busy, settings, worker)
    worker.progress.connect(receiver.on_progress)     # queued → GUI
    worker.render_request.connect(receiver.on_render) # queued → GUI
    loop = QEventLoop()
    worker.done.connect(loop.quit)                   # queued → GUI
    thread.started.connect(worker.run)
    thread.start()
    busy.show()
    loop.exec()
    thread.quit()
    thread.wait()
    busy.close()
    return worker.error


class SourcePanel(QWidget):
    """Source tab content: the source-mode dropdown, load buttons, a checkable
    source list, select/clear, and source-resolution helpers. Standalone so it
    can be embedded by both the full Run-batch dialog and (later) the Express
    batch dialog."""

    def __init__(
        self, parent=None, *, data_sets=None, results=None, show_similar_format=True,
    ) -> None:
        super().__init__(parent)
        self._data_sets = list(data_sets or [])  # data-set names shown in "data" mode
        self._sim_files: list[Path] = []          # .sim files added via Load File
        self._results = list(results or [])       # SimResults, for source resolution
        self._show_similar_format = show_similar_format

        self._source_input = QComboBox()
        self._source_input.addItem(".sim files", "sim")
        self._source_input.addItem("Loaded data sets", "data")
        self._source_input.currentIndexChanged.connect(self._refresh_source_window)
        # When checked, the batch is set up from a single representative .sim file
        # (reports/monitors/scenes/views come from it, since the rest share its
        # format). Only meaningful for .sim sources, so it's disabled in data mode.
        self._has_similar_format = QCheckBox("Has similar format")
        self._has_similar_format.setToolTip(
            "Set the batch up from the first .sim file; the other files share its "
            "reports, monitors, scenes and saved views."
        )

        options = QVBoxLayout()
        options.addWidget(self._header("Options"))
        options.addWidget(QLabel("Source input"))
        options.addWidget(self._source_input)
        if show_similar_format:
            options.addWidget(self._has_similar_format)
        else:
            # Still exists (callers may still reference it), just never shown.
            self._has_similar_format.setVisible(False)
        options.addStretch(1)

        self._source_window = _CheckableList()

        # Load File / Load Data Set are mutually exclusive (one per source mode);
        # Select All / Clear act on the window's checkboxes.
        self._load_file_btn = QPushButton("Load Files")
        self._load_file_btn.setToolTip("Add .sim files to the source list")
        self._load_file_btn.clicked.connect(self._load_files)
        self._load_dataset_btn = QPushButton("Load Data Set")
        self._load_dataset_btn.setToolTip("Add StarPost data CSVs to the source list")
        self._load_dataset_btn.clicked.connect(self._load_data_sets)
        select_all = QPushButton("Select All")
        select_all.clicked.connect(lambda: self._set_all_source(True))
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self._set_all_source(False))

        buttons = QHBoxLayout()
        buttons.addWidget(self._load_file_btn)
        buttons.addWidget(self._load_dataset_btn)
        buttons.addStretch(1)
        buttons.addWidget(select_all)
        buttons.addWidget(clear)

        right = QVBoxLayout()
        right.addWidget(self._header("Sources"))
        right.addWidget(self._source_window)
        right.addLayout(buttons)

        row = QHBoxLayout(self)
        row.addLayout(options, 1)
        row.addLayout(right, 2)

        self._refresh_source_window()

    @staticmethod
    def _header(text: str) -> QLabel:
        """A bold section header label."""
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold;")
        return label

    def current_mode(self) -> str:
        """The selected source mode: ``"sim"`` or ``"data"``."""
        return self._source_input.currentData()

    def _refresh_source_window(self) -> None:
        """Rebuild the right-hand window for the selected source — the loaded .sim
        files in '.sim files' mode, the data sets in 'Loaded data sets' mode —
        preserving each entry's check state, and show the matching Load button."""
        mode = self._source_input.currentData()
        self._load_file_btn.setVisible(mode == "sim")
        self._load_dataset_btn.setVisible(mode == "data")
        # "Has similar format" only applies to .sim sources; gray it out otherwise.
        self._has_similar_format.setEnabled(mode == "sim")

        prev = {
            self._source_window.item(i).text(): self._source_window.item(i).checkState()
            for i in range(self._source_window.count())
        }
        self._source_window.clear()
        names = (
            [p.name for p in self._sim_files] if mode == "sim" else list(self._data_sets)
        )
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(prev.get(name, Qt.CheckState.Checked))
            self._source_window.addItem(item)

    def _set_all_source(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._source_window.count()):
            self._source_window.item(i).setCheckState(state)

    def has_checked(self) -> bool:
        """Whether at least one source entry is checked in the current window."""
        return any(
            self._source_window.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self._source_window.count())
        )

    def checked_sim_files(self) -> list[Path]:
        """The loaded .sim files whose source-window rows are checked, in order."""
        checked = {
            self._source_window.item(i).text()
            for i in range(self._source_window.count())
            if self._source_window.item(i).checkState() == Qt.CheckState.Checked
        }
        return [p for p in self._sim_files if p.name in checked]

    def _load_files(self) -> None:
        """Load File: add .sim files to the source list (visible in '.sim files')."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load .sim files", "", "STAR-CCM+ sim (*.sim)"
        )
        existing = {str(p) for p in self._sim_files}
        for p in paths:
            if p not in existing:
                self._sim_files.append(Path(p))
                existing.add(p)
        self._refresh_source_window()

    def _load_data_sets(self) -> None:
        """Load Data Set: add StarPost data CSVs to the source list (visible in
        'Loaded data sets')."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load StarPost data CSVs", "", "CSV file (*.csv)"
        )
        for p in paths:
            name = Path(p).stem
            if name not in self._data_sets:
                self._data_sets.append(name)
        self._refresh_source_window()

    def sources(self) -> list:
        """The checked sources resolved for the run: loaded data sets carry their
        already-extracted result; .sim files are extracted during the run. A data
        set's .sim path (when it exists) lets its scenes render."""
        from starpost.batch.run import BatchSource

        if self._source_input.currentData() == "sim":
            return [BatchSource(name=p.stem, sim_file=p)
                    for p in self.checked_sim_files()]
        by_name = {r.sim_name: r for r in self._results}
        sources = []
        for i in range(self._source_window.count()):
            item = self._source_window.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            result = by_name.get(item.text())
            if result is None:
                continue
            sim_path = Path(result.sim_path) if result.sim_path else None
            sim_file = (
                sim_path
                if sim_path and sim_path.suffix == ".sim" and sim_path.exists()
                else None
            )
            sources.append(BatchSource(name=item.text(), result=result,
                                       sim_file=sim_file))
        return sources


class BatchRunDialog(QDialog):
    def __init__(
        self, parent=None, *, data_sets=None, report_names=None,
        monitor_groups=None, residual_groups=None, results=None, settings=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run batch")
        self.resize(820, 460)  # room for the Plots tab's three columns
        self._data_sets = list(data_sets or [])  # data-set names shown in "data" mode
        self._report_names = list(report_names or [])  # all reports across the sims
        self._monitor_groups = dict(monitor_groups or {})  # group -> [monitor names]
        self._residual_groups = set(residual_groups or [])  # auto-select groups
        self._results = list(results or [])       # SimResults, for the plot preview
        self._settings = settings
        # Scenes tab data, derived from the loaded results (union across sims).
        self._scene_groups = self._scene_groups_union(self._results)
        self._saved_views = sorted({v for r in self._results for v in r.views})
        # The .sim already extracted to set up the tabs (via "Has similar format"),
        # so re-pressing Continue doesn't re-check out a license for the same file.
        self._setup_sim_extracted: Path | None = None

        self._tabs = QTabWidget()
        bar = _LockedTabBar()
        bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # no keyboard focus either
        self._tabs.setTabBar(bar)
        self._source_panel = SourcePanel(
            data_sets=self._data_sets, results=self._results,
            show_similar_format=True,
        )
        self._tabs.addTab(self._source_panel, "Source")
        self._tabs.addTab(self._build_reports_tab(), "Reports")
        self._plots_tab = self._build_plots_tab()
        self._tabs.addTab(self._plots_tab, "Plots")
        self._scenes_tab = self._build_scenes_tab()
        self._tabs.addTab(self._scenes_tab, "Scenes")
        self._summary_tab = self._build_summary_tab()
        self._tabs.addTab(self._summary_tab, "Summary")
        # Keep the button label in step with the active tab, however it changed.
        self._tabs.currentChanged.connect(self._sync_button)
        # Open the plot preview window beside the dialog while the Plots tab shows.
        self._tabs.currentChanged.connect(self._update_preview)
        # Refresh the Summary lists from the other tabs whenever it's brought up.
        self._tabs.currentChanged.connect(self._refresh_summary)
        self.finished.connect(lambda _r: self._preview_window.close())

        # Bottom-left Back button (disabled on the first tab) and bottom-right
        # Continue button (becomes "Batch run" on the last tab).
        self._back = QPushButton("Back")
        self._back.clicked.connect(self._retreat)
        # "Add Plot" saves the current plot setup; only shown on the Plots tab.
        self._add_plot = QPushButton("Add Plot")
        self._add_plot.setVisible(False)
        self._add_plot.clicked.connect(self._on_add_plot)
        # "Save Scene" saves the current scene setup; only shown on the Scenes tab.
        self._save_scene = QPushButton("Save Scene")
        self._save_scene.setVisible(False)
        self._save_scene.clicked.connect(self._on_save_scene)
        self._next = QPushButton()
        self._next.clicked.connect(self._advance)
        row = QHBoxLayout()
        row.addWidget(self._back)
        row.addStretch(1)
        row.addWidget(self._add_plot)
        row.addWidget(self._save_scene)
        row.addWidget(self._next)

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_profile_bar())
        layout.addWidget(self._tabs)
        layout.addLayout(row)

        self._sync_button()

    # --- batch profiles (separate from the report/plot profiles) ----------
    def _build_profile_bar(self) -> QHBoxLayout:
        """A right-aligned 'Batch profile' selector at the top of the dialog,
        using its own separate set of profiles."""
        self._profile_box = QComboBox()
        self._refresh_profiles()
        load = QPushButton("Load")
        load.setToolTip("Load the selected batch profile")
        load.clicked.connect(self._load_profile)
        save = QPushButton("Save as…")
        save.setToolTip("Save the current batch setup as a new batch profile")
        save.clicked.connect(self._save_profile)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(QLabel("Batch profile"))
        row.addWidget(self._profile_box)
        row.addWidget(load)
        row.addWidget(save)
        return row

    def _refresh_profiles(self) -> None:
        current = self._profile_box.currentText()
        self._profile_box.clear()
        self._profile_box.addItems(list_batch_profiles())
        if current:
            self._profile_box.setCurrentText(current)

    def _load_profile(self) -> None:
        name = self._profile_box.currentText()
        if not name:
            return
        self._apply_profile(BatchProfile.load(name))

    def _save_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save batch profile", "Batch profile name:"
        )
        name = name.strip() if ok else ""
        if not name:
            return
        if name in list_batch_profiles() and QMessageBox.question(
            self, "Save batch profile",
            f"A batch profile named “{name}” already exists. Overwrite it?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._build_profile(name).save()
        self._refresh_profiles()
        self._profile_box.setCurrentText(name)

    def _build_profile(self, name: str) -> BatchProfile:
        """Capture the current batch setup — the ticked reports and the saved
        plots/scenes (name + characteristics) — into a profile."""
        return BatchProfile(
            name=name,
            selected_reports=[
                self._reports_window.item(i).text()
                for i in range(self._reports_window.count())
                if self._reports_window.item(i).checkState() == Qt.CheckState.Checked
            ],
            saved_plots=self._saved_entries(self._saved_plots),
            saved_scenes=self._saved_entries(self._saved_scenes),
            report_format=self._report_format.currentText(),
            include_units=self._report_include_units.isChecked(),
            combined_report=self._report_combined.isChecked(),
        )

    @staticmethod
    def _saved_entries(list_widget) -> list[dict]:
        """``[{"name": str, "data": dict}, ...]`` for a Saved Plots/Scenes list."""
        return [
            {
                "name": list_widget.item(i).text(),
                "data": list_widget.item(i).data(Qt.ItemDataRole.UserRole) or {},
            }
            for i in range(list_widget.count())
        ]

    def _apply_profile(self, profile: BatchProfile) -> None:
        """Apply a loaded profile: tick its reports (within those available) and
        replace the saved plots/scenes with the profile's."""
        selected = set(profile.selected_reports)
        for i in range(self._reports_window.count()):
            item = self._reports_window.item(i)
            item.setCheckState(
                Qt.CheckState.Checked if item.text() in selected
                else Qt.CheckState.Unchecked
            )
        self._restore_saved(self._saved_plots, profile.saved_plots)
        self._restore_saved(self._saved_scenes, profile.saved_scenes)
        idx = self._report_format.findText(profile.report_format)
        if idx >= 0:
            self._report_format.setCurrentIndex(idx)
        self._report_include_units.setChecked(profile.include_units)
        self._report_combined.setChecked(profile.combined_report)

    @staticmethod
    def _restore_saved(list_widget, entries) -> None:
        """Replace a Saved Plots/Scenes list with the profile's entries."""
        list_widget.clear()
        for entry in entries:
            item = QListWidgetItem(entry.get("name", ""))
            item.setData(Qt.ItemDataRole.UserRole, entry.get("data", {}))
            list_widget.addItem(item)

    @staticmethod
    def _header(text: str) -> QLabel:
        """A bold section header label."""
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold;")
        return label

    def _extract_setup_sim(self) -> bool:
        """Extract the first selected .sim and repopulate the Reports/Plots/Scenes
        tabs from it — the "Has similar format" setup step. Returns True to
        advance, False to stay on Source.

        The extraction runs on a worker thread while a modal progress dialog
        shows an animated (accent-coloured) bar, so the wizard is blocked but the
        dialog stays painted. Skips re-extraction when the first selected file is
        the one already extracted, so Back/Continue doesn't burn a license."""
        sims = self._source_panel.checked_sim_files()
        if not sims:
            return True  # nothing loaded to set up from; let the user continue
        sim = sims[0]
        if sim == self._setup_sim_extracted:
            return True  # already set up from this file
        if self._settings is None or not self._settings.starccm_path:
            QMessageBox.warning(
                self, "Run batch",
                "Set the STAR-CCM+ executable path in Settings first.",
            )
            return False

        result = self._run_extraction(sim)
        if result.error is not None:
            QMessageBox.warning(
                self, "Run batch",
                f"Couldn’t extract “{sim.name}”:\n{result.error}",
            )
            return False
        self._apply_setup_result(result)
        self._setup_sim_extracted = sim
        return True

    def _run_extraction(self, sim: Path) -> SimResult:
        """Extract ``sim`` on a worker thread, pumping the GUI event loop so the
        progress dialog animates, and return its parsed result."""
        busy = self._make_busy_dialog(sim.name)
        # Hold the result and keep the temp output dir alive until extraction and
        # parsing finish (the parser reads the CSVs the macro writes there).
        with tempfile.TemporaryDirectory(prefix="starpost_setup_") as out:
            thread = QThread(self)
            worker = _ExtractWorker(StarRunner(self._settings), sim, Path(out))
            worker.moveToThread(thread)
            loop = QEventLoop()
            # loop.quit lives on the GUI thread, so this cross-thread signal is a
            # queued connection and quit() runs back on the GUI thread.
            worker.done.connect(loop.quit)
            thread.started.connect(worker.run)
            thread.start()
            busy.show()
            loop.exec()  # waits for worker.done while the GUI keeps repainting
            thread.quit()
            thread.wait()
            result = worker.result
            worker.deleteLater()
            busy.close()
        return result

    def _make_busy_dialog(self, sim_name: str) -> QProgressDialog:
        """A modal, cancel-less progress dialog with a smooth (~60 fps) sliding
        accent bar that follows the user's theme and accent colour."""
        dlg = QProgressDialog(
            f"Extracting “{sim_name}” to set up the batch…", "", 0, 0, self
        )
        dlg.setWindowTitle("Run batch")
        dlg.setCancelButton(None)  # no cancel: one STAR-CCM+ run, runs to the end
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        accent, mode = "#ffc829", "dark"
        if self._settings is not None:
            accent = self._settings.appearance.accent
            mode = self._settings.appearance.mode
        dlg.setBar(_BusyBar(accent, mode, dlg))
        return dlg

    def _apply_setup_result(self, result) -> None:
        """Repopulate the Reports and Plots tabs (and the preview's source result)
        from a freshly extracted representative .sim."""
        self._results = [result]

        # Reports tab: rebuild the checklist (all reports checked by default).
        self._report_names = sorted(result.report_names())
        self._reports_window.clear()
        for name in self._report_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._reports_window.addItem(item)

        # Plots tab: rebuild the monitor tree from this sim's plots.
        self._monitor_groups = self._monitor_groups_union([result])
        self._residual_groups = self._residual_group_names([result])
        self._monitor_tree.set_auto_select_groups(self._residual_groups)
        self._monitor_tree.set_groups(self._monitor_groups)

        # Scenes tab: rebuild the scene tree and saved-views list from this sim.
        self._scene_groups = self._scene_groups_union([result])
        self._saved_views = sorted(result.views)
        self._scene_tree.set_items(self._scene_groups)
        self._set_views_items(self._saved_views)

    def _monitor_groups_union(self, results) -> dict[str, list[str]]:
        """``{plot group: [monitor series, ...]}`` across ``results``, dropping
        empty monitors when "Hide empty monitors" is on — mirrors the main
        window's helper so the tree matches the rest of the app."""
        hide = self._settings.hide_empty_monitors if self._settings else True
        threshold = (
            self._settings.monitor_zero_threshold if self._settings else 1e-5
        )
        groups: dict[str, list[str]] = {}
        for r in results:
            for p in r.plots:
                names = groups.setdefault(p.name, [])
                for s in p.series:
                    if hide and _series_is_empty(s, threshold):
                        continue
                    if s.name not in names:
                        names.append(s.name)
        return groups

    @staticmethod
    def _residual_group_names(results) -> set[str]:
        """Plot groups classified as residuals (plotted all-at-once when ticked)."""
        return {
            p.name for r in results for p in r.plots if p.kind == PlotKind.RESIDUAL
        }

    # --- Reports tab ------------------------------------------------------
    def _build_reports_tab(self) -> QWidget:
        """Options on the left (file format, Include units, Combined report); a
        window on the right listing every report across the sims (checkable, all
        checked by default)."""
        tab = QWidget()

        self._reports_window = _CheckableList()
        for name in self._report_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)  # all reports checked by default
            self._reports_window.addItem(item)

        self._report_format = QComboBox()
        self._report_format.addItems(["CSV", "TSV", "XLSX", "ODS"])
        self._report_include_units = QCheckBox("Include units")
        self._report_include_units.setChecked(True)
        # No "Separate files" option here (unlike the Export dialog): the batch
        # archive already keeps each data set's report in its own folder.
        self._report_combined = QCheckBox("Combined report")
        self._report_combined.setToolTip(
            "Also write one report combining every data set (one column per sim) "
            "at the archive root, alongside the per-data-set report files"
        )
        self._report_combined.setChecked(True)  # on by default

        options = QVBoxLayout()
        options.addWidget(self._header("Options"))
        options.addWidget(QLabel("File format"))
        options.addWidget(self._report_format)
        options.addWidget(self._report_include_units)
        options.addWidget(self._report_combined)
        options.addStretch(1)

        # Select All / Clear for the reports window, right-aligned beneath it.
        select_all = QPushButton("Select All")
        select_all.clicked.connect(lambda: self._set_all_reports(True))
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self._set_all_reports(False))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(select_all)
        buttons.addWidget(clear)

        right = QVBoxLayout()
        right.addWidget(self._header("Reports"))
        right.addWidget(self._reports_window)
        right.addLayout(buttons)

        row = QHBoxLayout(tab)
        row.addLayout(options, 1)
        row.addLayout(right, 2)
        return tab

    def _set_all_reports(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._reports_window.count()):
            self._reports_window.item(i).setCheckState(state)

    # --- Scenes tab -------------------------------------------------------
    def _build_scenes_tab(self) -> QWidget:
        """Four columns: render options (left, narrow); a tree of scenes (checking
        one reveals its scalar/vector displayers as checkable children, mirroring
        the app's Scenes view); a checklist of the sim's saved camera views; and
        the Saved Scenes the user has captured with "Save Scene" on the right."""
        tab = QWidget()

        # Options: the scene-render image options, seeded from settings.
        self._scene_resolution = QComboBox()
        self._scene_resolution.addItem("1080p", "1080p")
        self._scene_resolution.addItem("2160p", "2160p")
        self._scene_format = QComboBox()
        self._scene_format.addItem("JPG", "jpg")
        self._scene_format.addItem("PNG", "png")
        if self._settings is not None:
            ri = self._scene_resolution.findData(self._settings.media.image_resolution)
            if ri >= 0:
                self._scene_resolution.setCurrentIndex(ri)
            fi = self._scene_format.findData(self._settings.media.image_format)
            if fi >= 0:
                self._scene_format.setCurrentIndex(fi)

        options = QVBoxLayout()
        options.addWidget(self._header("Options"))
        options.addWidget(QLabel("Image resolution"))
        options.addWidget(self._scene_resolution)
        options.addWidget(QLabel("Image format"))
        options.addWidget(self._scene_format)
        options.addStretch(1)

        # Saved Scenes: scene setups captured with "Save Scene" (each item holds
        # its scene characteristics in its data). Right-click a scene for
        # Properties / Delete.
        self._saved_scenes = QListWidget()
        enable_range_selection(self._saved_scenes)
        self._saved_scenes.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._saved_scenes.customContextMenuRequested.connect(
            self._on_saved_scene_menu
        )
        saved = QVBoxLayout()
        saved.addWidget(self._header("Saved Scenes"))
        saved.addWidget(self._saved_scenes)

        # Scenes: a tree of scenes whose displayers appear (checkable) when the
        # scene is checked.
        self._scene_tree = _SceneTree()
        self._scene_tree.set_items(self._scene_groups)
        scenes = QVBoxLayout()
        scenes.addWidget(self._header("Scenes"))
        scenes.addWidget(self._scene_tree)

        # Saved views: a checklist of the sim's saved camera views (opt-in).
        self._views_window = _CheckableList()
        self._set_views_items(self._saved_views)
        views = QVBoxLayout()
        views.addWidget(self._header("Saved Views"))
        views.addWidget(self._views_window)

        # Options stays narrow (1); Saved Scenes sits at the far right, after
        # Saved Views.
        row = QHBoxLayout(tab)
        row.addLayout(options, 1)
        row.addLayout(scenes, 2)
        row.addLayout(views, 1)
        row.addLayout(saved, 1)
        return tab

    @staticmethod
    def _scene_groups_union(results) -> dict[str, list[str]]:
        """``{scene: [displayer, ...]}`` union across ``results`` — mirrors the
        main window's scene-choice builder."""
        groups: dict[str, list[str]] = {}
        for r in results:
            for sc in r.scenes:
                names = groups.setdefault(sc.name, [])
                for d in sc.displayers:
                    if d.name not in names:
                        names.append(d.name)
        return groups

    def _set_views_items(self, views) -> None:
        """Fill the Saved Views checklist (rendering from a view is opt-in, so
        each starts unchecked)."""
        self._views_window.clear()
        for name in views:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._views_window.addItem(item)

    # --- Summary tab ------------------------------------------------------
    def _build_summary_tab(self) -> QWidget:
        """Four columns reviewing what the batch will produce: export options
        (left), then read-only lists of the selected reports, the saved plots and
        the saved scenes. The lists are filled from the other tabs each time the
        Summary tab is shown (see _refresh_summary)."""
        tab = QWidget()

        # Export options: the archive format for the produced output, and
        # whether each data set's portable CSV goes into its folder too.
        self._export_format = QComboBox()
        self._export_format.addItem("ZIP", "zip")
        self._export_format.addItem("7Z", "7z")
        self._include_dataset_csv = QCheckBox("Include dataset .csv")
        self._include_dataset_csv.setToolTip(
            "Also write each data set's portable StarPost CSV (the same file as "
            "the Data tab's Export Data button) into its folder in the archive"
        )
        options = QVBoxLayout()
        options.addWidget(self._header("Export options"))
        options.addWidget(QLabel("Archive format"))
        options.addWidget(self._export_format)
        options.addWidget(self._include_dataset_csv)
        options.addStretch(1)

        self._summary_reports = QListWidget()
        enable_range_selection(self._summary_reports)
        reports = QVBoxLayout()
        reports.addWidget(self._header("Reports"))
        reports.addWidget(self._summary_reports)

        # Plots / Scenes mirror the saved lists on the other tabs, and carry the
        # same right-click menu (Properties / Delete). Deleting here removes the
        # entry from its source list too.
        self._summary_plots = QListWidget()
        enable_range_selection(self._summary_plots)
        self._summary_plots.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._summary_plots.customContextMenuRequested.connect(
            self._on_summary_plot_menu
        )
        plots = QVBoxLayout()
        plots.addWidget(self._header("Plots"))
        plots.addWidget(self._summary_plots)

        self._summary_scenes = QListWidget()
        enable_range_selection(self._summary_scenes)
        self._summary_scenes.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._summary_scenes.customContextMenuRequested.connect(
            self._on_summary_scene_menu
        )
        scenes = QVBoxLayout()
        scenes.addWidget(self._header("Scenes"))
        scenes.addWidget(self._summary_scenes)

        row = QHBoxLayout(tab)
        row.addLayout(options, 1)
        row.addLayout(reports, 1)
        row.addLayout(plots, 1)
        row.addLayout(scenes, 1)
        return tab

    def _refresh_summary(self, *_args) -> None:
        """Repopulate the Summary lists from the other tabs: the currently checked
        reports, the saved plots and the saved scenes. A no-op unless the Summary
        tab is in front."""
        if self._tabs.currentWidget() is not self._summary_tab:
            return
        self._summary_reports.clear()
        self._summary_reports.addItems([
            self._reports_window.item(i).text()
            for i in range(self._reports_window.count())
            if self._reports_window.item(i).checkState() == Qt.CheckState.Checked
        ])
        # Mirror the saved plots/scenes with their captured data, so the Summary
        # tab's Properties menu can render them and rows map 1:1 to their source.
        self._mirror_saved(self._saved_plots, self._summary_plots)
        self._mirror_saved(self._saved_scenes, self._summary_scenes)

    @staticmethod
    def _mirror_saved(src: QListWidget, dst: QListWidget) -> None:
        """Copy ``src``'s items (text + captured data) into ``dst``, in order."""
        dst.clear()
        for i in range(src.count()):
            s = src.item(i)
            item = QListWidgetItem(s.text())
            item.setData(
                Qt.ItemDataRole.UserRole, s.data(Qt.ItemDataRole.UserRole)
            )
            dst.addItem(item)

    # --- Plots tab --------------------------------------------------------
    def _build_plots_tab(self) -> QWidget:
        """Options on the left; a monitor tree on the right. A separate plot
        preview window (built here) opens beside the dialog while this tab shows
        (see _update_preview), mirroring the Export dialog's plot preview."""
        tab = QWidget()

        self._monitor_tree = _MonitorTree()
        self._monitor_tree.set_auto_select_groups(self._residual_groups)
        self._monitor_tree.set_groups(self._monitor_groups)
        self._monitor_tree.changed.connect(self._render_preview)
        # Clicking a checked monitor's colour swatch recolours its line.
        self._monitor_tree.swatch_clicked.connect(self._pick_monitor_color)

        options = self._build_plot_options()

        monitors = QVBoxLayout()
        monitors.addWidget(self._header("Monitors"))
        monitors.addWidget(self._monitor_tree)

        # Saved Plots: plots the user has captured with "Add Plot" (each item
        # holds its plot characteristics in its data). Right-click a plot for
        # Properties / Delete.
        self._saved_plots = QListWidget()
        enable_range_selection(self._saved_plots)
        self._saved_plots.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._saved_plots.customContextMenuRequested.connect(
            self._on_saved_plot_menu
        )
        saved = QVBoxLayout()
        saved.addWidget(self._header("Saved Plots"))
        saved.addWidget(self._saved_plots)

        # Widths (stretch): wider Options, Monitors unchanged, Saved Plots halved.
        row = QHBoxLayout(tab)
        row.addLayout(options, 2)
        row.addLayout(monitors, 2)
        row.addLayout(saved, 1)

        # The preview lives in its own top-level window, parented to the dialog so
        # it's owned/closed with it but stays beside (not over) the dialog.
        self._preview = PlotView()
        self._configure_preview()
        self._preview_window = _PreviewWindow(self)
        self._preview_window.setWindowTitle("Plot preview")
        self._preview_window.resize(720, 480)
        pv = QVBoxLayout(self._preview_window)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(self._preview)
        return tab

    def _build_plot_options(self) -> QVBoxLayout:
        """Plot options matching the Export dialog's, live-applied to the preview:
        aspect ratio, title (+size), axis labels (+size), theme, legend scale,
        line thickness, grid, image format. Each slider's value is set before its
        signal is connected so configuring it doesn't fire into the preview (which
        isn't built yet)."""
        # Aspect ratio of the preview window ("Custom" == free resize).
        self._plot_aspect = QComboBox()
        self._plot_aspect.addItems(["1:1", "3:2", "4:3", "16:9", "Custom"])
        self._plot_aspect.setCurrentText("Custom")
        self._plot_aspect.setToolTip("Lock the plot's width-to-height ratio")
        self._plot_aspect.currentTextChanged.connect(self._on_aspect_changed)

        self._plot_title = QLineEdit()
        self._plot_title.textChanged.connect(self._preview_set_title)

        # Title size: a slider setting the plot title's font size (points).
        self._title_size = QSlider(Qt.Orientation.Horizontal)
        self._title_size.setRange(0, 100)
        self._title_size.setValue(
            self._text_size_slider(_TITLE_PT_DEFAULT, _TITLE_PT_MIN, _TITLE_PT_MAX)
        )
        self._title_size.setToolTip("Font size of the plot title")
        self._title_size.valueChanged.connect(self._preview_set_title_size)

        self._plot_xlabel = QLineEdit()
        self._plot_xlabel.textChanged.connect(self._preview_set_xlabel)
        self._plot_ylabel = QLineEdit()
        self._plot_ylabel.textChanged.connect(self._preview_set_ylabel)

        # Axis label size: one slider for both axis labels, so X and Y match.
        self._axis_label_size = QSlider(Qt.Orientation.Horizontal)
        self._axis_label_size.setRange(0, 100)
        self._axis_label_size.setValue(
            self._text_size_slider(
                _AXIS_LABEL_PT_DEFAULT, _AXIS_LABEL_PT_MIN, _AXIS_LABEL_PT_MAX
            )
        )
        self._axis_label_size.setToolTip(
            "Font size of both axis labels (X and Y change together)"
        )
        self._axis_label_size.valueChanged.connect(self._preview_set_axis_label_size)

        self._plot_theme = QComboBox()
        self._plot_theme.addItem("Light", "light")
        self._plot_theme.addItem("Dark", "dark")
        self._plot_theme.currentIndexChanged.connect(self._preview_set_theme)

        # Legend size: midpoint is the natural size (1.0×), scaling down (left) or
        # up (right) symmetrically — same mapping as the Export dialog's slider.
        self._legend_scale = QSlider(Qt.Orientation.Horizontal)
        self._legend_scale.setRange(0, 100)
        self._legend_scale.setValue(50)  # middle of the track == default 1.0×
        self._legend_scale.setToolTip("Scale the plot legend smaller or larger")
        self._legend_scale.valueChanged.connect(self._preview_set_legend_scale)

        # Line thickness: pen width of every line, thin (left) to thick (right).
        self._line_width = QSlider(Qt.Orientation.Horizontal)
        self._line_width.setRange(0, 100)
        self._line_width.setValue(self._line_width_slider(_LINE_WIDTH_DEFAULT))
        self._line_width.setToolTip("Thickness of every line on the plot")
        self._line_width.valueChanged.connect(self._preview_set_line_width)

        self._plot_grid = QCheckBox("Show grid")
        self._plot_grid.setChecked(True)
        self._plot_grid.toggled.connect(self._preview_set_grid)
        self._plot_format = QComboBox()
        self._plot_format.addItems(["PNG", "JPG", "TIFF", "PDF"])

        form = QFormLayout()
        form.addRow("Aspect ratio", self._plot_aspect)
        form.addRow("Plot title", self._plot_title)
        form.addRow("Title size", self._title_size)
        form.addRow("X axis label", self._plot_xlabel)
        form.addRow("Y axis label", self._plot_ylabel)
        form.addRow("Axis label size", self._axis_label_size)
        form.addRow("Theme", self._plot_theme)
        form.addRow("Legend scale", self._legend_scale)
        form.addRow("Line thickness", self._line_width)
        form.addRow(self._plot_grid)
        form.addRow("Format", self._plot_format)

        col = QVBoxLayout()
        col.addWidget(self._header("Options"))
        col.addLayout(form)
        col.addStretch(1)
        return col

    # --- option slider mappings (shared with the Export dialog) -----------
    @staticmethod
    def _legend_factor(value: int) -> float:
        """Map the slider's 0–100 position to a legend scale factor, with the
        midpoint (50) at 1.0×; each half spans one octave (ends 0.5× and 2.0×)."""
        return 2.0 ** ((value - 50) / 50.0)

    @staticmethod
    def _legend_slider(factor: float) -> int:
        """The slider position that yields ``factor`` (inverse of _legend_factor)."""
        return round(50 + 50 * math.log2(factor)) if factor > 0 else 50

    @staticmethod
    def _line_width_for(value: int) -> float:
        """Map the slider's 0–100 position to a pen width across the thin–thick
        range."""
        span = _LINE_WIDTH_MAX - _LINE_WIDTH_MIN
        return _LINE_WIDTH_MIN + span * value / 100.0

    @staticmethod
    def _line_width_slider(width: float) -> int:
        """The slider position that yields ``width`` (inverse of _line_width_for)."""
        span = _LINE_WIDTH_MAX - _LINE_WIDTH_MIN
        return round((width - _LINE_WIDTH_MIN) / span * 100)

    @staticmethod
    def _text_size_for(value: int, lo: int, hi: int) -> int:
        """Map a slider's 0–100 position to a font size (points) in [lo, hi]."""
        return round(lo + (hi - lo) * value / 100.0)

    @staticmethod
    def _text_size_slider(pt: float, lo: int, hi: int) -> int:
        """The slider position that yields ``pt`` (inverse of _text_size_for)."""
        return round((pt - lo) / (hi - lo) * 100)

    def _configure_preview(self) -> None:
        """Match the preview's filtering/hover/theme to the app settings so it
        looks like the main plot view."""
        self._preview.set_category_controls_visible(False)
        s = self._settings
        if s is None:
            return
        self._preview.set_filter(s.hide_empty_monitors, s.monitor_zero_threshold)
        self._preview.set_hover_options(
            s.hover_show_monitor_name, s.hover_x_decimals, s.hover_y_decimals
        )
        self._preview.set_region_stats(s.region_stats)
        self._preview.apply_theme(s.export_plot_theme)
        idx = self._plot_theme.findData(s.export_plot_theme)
        if idx >= 0:
            self._plot_theme.setCurrentIndex(idx)

    def _update_preview(self, *_args) -> None:
        """Show the preview window (and the Add Plot button) while the Plots tab
        is in front; hide them otherwise. The Save Scene button likewise shows
        only on the Scenes tab."""
        on_plots = self._tabs.currentWidget() is self._plots_tab
        self._add_plot.setVisible(on_plots)
        self._save_scene.setVisible(self._tabs.currentWidget() is self._scenes_tab)
        if on_plots:
            frame = self.frameGeometry()
            self._preview_window.move(frame.right() + 8, frame.top())
            self._preview_window.show()
            self._preview_window.raise_()
            self._render_preview()
        else:
            self._preview_window.hide()

    def _capture_plot(self) -> dict:
        """Snapshot the current plot characteristics for a saved plot. The batch
        run will later regenerate this plot per data set; for now it's stored on
        the saved-plot list item (the run wiring comes later)."""
        series_colors, pair_colors = self._preview.color_overrides()
        monitors = self._monitor_tree.checked_monitors()
        # The resolved (drawn) colour of each selected monitor, captured now for
        # the saved plot's Properties view since the preview may change later.
        monitor_colors = {
            s: self._preview.series_color(s)
            for series in monitors.values()
            for s in series
        }
        # The legend position as a list (YAML-safe) so it saves in batch profiles.
        legend_offset = self._preview.legend_offset()
        return {
            "title": self._plot_title.text(),
            "title_size": self._text_size_for(
                self._title_size.value(), _TITLE_PT_MIN, _TITLE_PT_MAX
            ),
            "x_label": self._plot_xlabel.text(),
            "y_label": self._plot_ylabel.text(),
            "axis_label_size": self._text_size_for(
                self._axis_label_size.value(),
                _AXIS_LABEL_PT_MIN, _AXIS_LABEL_PT_MAX,
            ),
            "aspect": self._plot_aspect.currentText(),
            "monitors": monitors,
            "monitor_colors": monitor_colors,
            "theme": self._plot_theme.currentData(),
            "legend_scale": self._legend_factor(self._legend_scale.value()),
            "legend_offset": list(legend_offset) if legend_offset else None,
            "line_width": self._line_width_for(self._line_width.value()),
            "grid": self._plot_grid.isChecked(),
            "format": self._plot_format.currentText(),
            "series_colors": dict(series_colors),
            "pair_colors": dict(pair_colors),
        }

    def _on_add_plot(self) -> None:
        """Prompt for a name and add the current plot setup to Saved Plots."""
        name, ok = QInputDialog.getText(self, "Add plot", "Saved plot name:")
        name = name.strip() if ok else ""
        if not name:
            return
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, self._capture_plot())
        self._saved_plots.addItem(item)

    def _apply_plot(self, data: dict) -> None:
        """Load a saved plot's captured settings back into the Plots-tab controls
        and the live preview (the inverse of :meth:`_capture_plot`)."""
        # Each control drives the preview through its own signal; setting them all
        # rebuilds the preview to match the saved plot.
        self._plot_aspect.setCurrentText(data.get("aspect") or "Custom")
        self._plot_title.setText(data.get("title", ""))
        self._plot_xlabel.setText(data.get("x_label", ""))
        self._plot_ylabel.setText(data.get("y_label", ""))
        ti = self._plot_theme.findData(data.get("theme"))
        if ti >= 0:
            self._plot_theme.setCurrentIndex(ti)
        fi = self._plot_format.findText(
            data.get("format", ""), Qt.MatchFlag.MatchFixedString
        )
        if fi >= 0:
            self._plot_format.setCurrentIndex(fi)
        self._plot_grid.setChecked(bool(data.get("grid", True)))
        if data.get("title_size") is not None:
            self._title_size.setValue(
                self._text_size_slider(
                    data["title_size"], _TITLE_PT_MIN, _TITLE_PT_MAX
                )
            )
        if data.get("axis_label_size") is not None:
            self._axis_label_size.setValue(
                self._text_size_slider(
                    data["axis_label_size"], _AXIS_LABEL_PT_MIN, _AXIS_LABEL_PT_MAX
                )
            )
        if data.get("legend_scale") is not None:
            self._legend_scale.setValue(self._legend_slider(data["legend_scale"]))
        if data.get("line_width") is not None:
            self._line_width.setValue(self._line_width_slider(data["line_width"]))
        # Monitor selection triggers _render_preview (draws the plots + swatches).
        self._monitor_tree.set_selection(data.get("monitors") or {})
        # Colours need the curves drawn first (above).
        self._preview.set_color_overrides(
            data.get("series_colors") or {}, data.get("pair_colors") or {}
        )
        self._refresh_monitor_swatches()
        # Surface the preview window in case it's hidden or behind the dialog.
        self._preview_window.show()
        self._preview_window.raise_()
        # Restore the legend position last — once the preview window is shown and
        # its plot area has its final size (the offset is a fraction of it).
        if data.get("legend_offset"):
            self._preview.set_legend_offset(data["legend_offset"])

    def _checked_views(self) -> list[str]:
        """The checked saved camera views, in list order."""
        return [
            self._views_window.item(i).text()
            for i in range(self._views_window.count())
            if self._views_window.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _capture_scene(self) -> dict:
        """Snapshot the current scene setup for a saved scene: the checked scenes
        and their displayers, the chosen views, and the image options."""
        return {
            "displayers": self._scene_tree.checked_displayers(),
            "views": self._checked_views(),
            "resolution": self._scene_resolution.currentData(),
            "format": self._scene_format.currentData(),
        }

    def _on_save_scene(self) -> None:
        """Prompt for a name and add the current scene setup to Saved Scenes."""
        name, ok = QInputDialog.getText(self, "Save scene", "Saved scene name:")
        name = name.strip() if ok else ""
        if not name:
            return
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, self._capture_scene())
        self._saved_scenes.addItem(item)

    def _on_saved_plot_menu(self, pos) -> None:
        """Right-click a saved plot: Properties (its captured settings) or Delete."""
        item = self._saved_plots.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self._saved_plots)
        menu.addAction("Preview", lambda: self._preview_saved_plot(item))
        menu.addAction("Properties", lambda: self._show_saved_plot_properties(item))
        menu.addAction("Delete", lambda: self._delete_saved_plot(item))
        menu.exec(self._saved_plots.viewport().mapToGlobal(pos))

    def _preview_saved_plot(self, item) -> None:
        """Load a saved plot's captured settings into the live preview."""
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        self._apply_plot(data)

    def _show_saved_plot_properties(self, item) -> None:
        """Open the read-only properties window for a saved plot."""
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        _SavedPlotPropertiesDialog(item.text(), data, self).exec()

    def _delete_saved_plot(self, item) -> None:
        """Remove a saved plot from the list."""
        self._saved_plots.takeItem(self._saved_plots.row(item))

    def _on_saved_scene_menu(self, pos) -> None:
        """Right-click a saved scene: Properties (its captured settings) or
        Delete."""
        item = self._saved_scenes.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self._saved_scenes)
        menu.addAction("Properties", lambda: self._show_saved_scene_properties(item))
        menu.addAction("Delete", lambda: self._delete_saved_scene(item))
        menu.exec(self._saved_scenes.viewport().mapToGlobal(pos))

    def _show_saved_scene_properties(self, item) -> None:
        """Open the read-only properties window for a saved scene."""
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        _SavedScenePropertiesDialog(item.text(), data, self).exec()

    def _delete_saved_scene(self, item) -> None:
        """Remove a saved scene from the list."""
        self._saved_scenes.takeItem(self._saved_scenes.row(item))

    def _on_summary_plot_menu(self, pos) -> None:
        """Right-click a Summary-tab plot: Properties or Delete (mirrors the
        Plots tab; deleting also removes it from Saved Plots)."""
        item = self._summary_plots.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self._summary_plots)
        menu.addAction("Properties", lambda: self._show_saved_plot_properties(item))
        menu.addAction("Delete", lambda: self._delete_summary_plot(item))
        menu.exec(self._summary_plots.viewport().mapToGlobal(pos))

    def _delete_summary_plot(self, item) -> None:
        """Delete a plot from Saved Plots via the Summary tab, then refresh."""
        self._saved_plots.takeItem(self._summary_plots.row(item))
        self._refresh_summary()

    def _on_summary_scene_menu(self, pos) -> None:
        """Right-click a Summary-tab scene: Properties or Delete (mirrors the
        Scenes tab; deleting also removes it from Saved Scenes)."""
        item = self._summary_scenes.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self._summary_scenes)
        menu.addAction("Properties", lambda: self._show_saved_scene_properties(item))
        menu.addAction("Delete", lambda: self._delete_summary_scene(item))
        menu.exec(self._summary_scenes.viewport().mapToGlobal(pos))

    def _delete_summary_scene(self, item) -> None:
        """Delete a scene from Saved Scenes via the Summary tab, then refresh."""
        self._saved_scenes.takeItem(self._summary_scenes.row(item))
        self._refresh_summary()

    def _render_preview(self) -> None:
        """Draw the checked monitors into the preview for a SINGLE data set (the
        first loaded sim, as a representative). The batch run will later generate
        the same plot per data set; this preview is only for choosing the plot's
        appearance (title, colours, legend, …)."""
        selection = self._monitor_tree.checked_monitors()
        groups = set(selection)
        plots = (
            [p for p in self._results[0].plots if p.name in groups]
            if self._results and groups else []
        )
        if plots:
            # Selection first (no render), so show_plots draws it in one pass.
            self._preview.set_monitor_selection(selection, render=False)
            self._preview.show_plots(plots)
        else:
            self._preview.clear()
        # Keep each checked monitor's swatch in step with the colour it's drawn in.
        self._refresh_monitor_swatches()

    # --- monitor colour swatches ----------------------------------------
    @staticmethod
    def _color_icon(color: str) -> QIcon:
        """A filled square swatch of ``color`` for the tree and the colour menu."""
        px = QPixmap(_SWATCH_SIZE, _SWATCH_SIZE)
        px.fill(QColor(color))
        return QIcon(px)

    def _refresh_monitor_swatches(self) -> None:
        """Give every checked monitor a colour swatch matching the colour it's
        drawn in (the representative data set's line); clear it on unchecked
        monitors. Signals are blocked so setting an icon doesn't re-fire
        itemChanged."""
        tree = self._monitor_tree
        tree.setIconSize(QSize(_SWATCH_SIZE, _SWATCH_SIZE))
        tree.blockSignals(True)
        root = tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            for j in range(group.childCount()):
                m = group.child(j)
                if m.checkState(0) == Qt.CheckState.Checked:
                    name = m.data(0, Qt.ItemDataRole.UserRole)
                    color = self._preview.series_color(name) or "#888888"
                    m.setData(0, _SWATCH_ROLE, [color])
                    m.setIcon(0, self._color_icon(color))
                else:
                    m.setData(0, _SWATCH_ROLE, None)
                    m.setIcon(0, QIcon())
        tree.blockSignals(False)

    def _pick_monitor_color(self, item, _swatch: int) -> None:
        """Colour menu for a monitor's swatch: pick a palette colour or a custom
        one; the choice recolours that monitor's line in the preview and updates
        the swatch."""
        name = item.data(0, Qt.ItemDataRole.UserRole)
        current = self._preview.series_color(name)
        menu = QMenu(self)
        for c in _COLORS:
            menu.addAction(self._color_icon(c), c).setData(c)
        menu.addSeparator()
        custom = menu.addAction("Custom…")
        chosen = menu.exec(QCursor.pos())
        if chosen is None:
            return
        if chosen is custom:
            picked = QColorDialog.getColor(
                QColor(current or "#ffffff"), self, "Monitor colour"
            )
            if not picked.isValid():
                return
            color = picked.name()
        else:
            color = chosen.data()
        self._preview.set_series_color(name, color)
        self._refresh_monitor_swatches()

    # Preview option handlers.
    def _preview_set_title(self, text) -> None:
        self._preview.set_title_override(text)

    def _preview_set_xlabel(self, text) -> None:
        self._preview.set_x_label_override(text)

    def _preview_set_ylabel(self, text) -> None:
        self._preview.set_y_label_override(text)

    def _preview_set_theme(self, *_a) -> None:
        self._preview.apply_theme(self._plot_theme.currentData())

    def _preview_set_grid(self, checked) -> None:
        self._preview.set_grid_visible(checked)

    def _preview_set_legend_scale(self, value) -> None:
        self._preview.set_legend_scale(self._legend_factor(value))

    def _preview_set_title_size(self, value) -> None:
        self._preview.set_title_size(
            self._text_size_for(value, _TITLE_PT_MIN, _TITLE_PT_MAX)
        )

    def _preview_set_axis_label_size(self, value) -> None:
        self._preview.set_axis_label_size(
            self._text_size_for(value, _AXIS_LABEL_PT_MIN, _AXIS_LABEL_PT_MAX)
        )

    def _preview_set_line_width(self, value) -> None:
        self._preview.set_line_width(self._line_width_for(value))

    def _on_aspect_changed(self, text) -> None:
        """Lock the preview window to the chosen aspect ratio; "Custom" (any
        non-ratio text) frees it to resize to any size."""
        if ":" not in text:  # "Custom"
            self._preview_window.set_aspect(None)
            return
        w, h = text.split(":")
        self._preview_window.set_aspect(int(w) / int(h))

    def _on_summary(self) -> bool:
        return self._tabs.currentIndex() == self._tabs.count() - 1

    def _sync_button(self) -> None:
        self._next.setText("Batch run" if self._on_summary() else "Continue")
        self._back.setEnabled(self._tabs.currentIndex() > 0)

    def _advance(self) -> None:
        """Continue moves to the next tab; on Summary, "Batch run" runs the batch.
        Leaving the Source tab requires at least one selected source, and — with
        "Has similar format" — extracts the first selected .sim to set up the
        downstream tabs."""
        if self._tabs.currentIndex() == 0:
            if not self._source_panel.has_checked():
                QMessageBox.warning(
                    self, "Run batch",
                    "No data selected. Select at least one source to continue.",
                )
                return
            sim_mode = self._source_panel.current_mode() == "sim"
            if sim_mode and self._source_panel._has_similar_format.isChecked():
                if not self._extract_setup_sim():
                    return  # extraction failed or was unavailable; stay put
        if self._on_summary():
            self._run_batch()
        else:
            self._tabs.setCurrentIndex(self._tabs.currentIndex() + 1)

    # --- the run ----------------------------------------------------------
    def _run_batch(self) -> None:
        """Batch run: write each data set's reports, saved-plot images and
        saved-scene stills into a per-data-set folder, packed into one archive
        (ZIP or 7Z) in the chosen output folder. Runs on a worker thread behind a
        progress dialog."""
        from starpost.batch.run import BatchConfig

        sources = self._source_panel.sources()
        if not sources:
            QMessageBox.warning(self, "Run batch", "No data selected.")
            return
        reports = {
            self._reports_window.item(i).text()
            for i in range(self._reports_window.count())
            if self._reports_window.item(i).checkState() == Qt.CheckState.Checked
        }
        saved_plots = self._saved_entries(self._saved_plots)
        saved_scenes = self._saved_entries(self._saved_scenes)
        include_dataset_csv = self._include_dataset_csv.isChecked()
        if (not reports and not saved_plots and not saved_scenes
                and not include_dataset_csv):
            QMessageBox.warning(
                self, "Run batch",
                "Nothing to output — select reports or save a plot/scene first.",
            )
            return

        # STAR-CCM+ is needed to extract .sim sources or render any scenes.
        needs_exe = any(s.result is None for s in sources) or (
            bool(saved_scenes) and any(s.sim_file for s in sources)
        )
        if needs_exe and (self._settings is None or not self._settings.starccm_path):
            QMessageBox.warning(
                self, "Run batch",
                "Set the STAR-CCM+ executable path in Settings first.",
            )
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not out_dir:
            return
        fmt = self._export_format.currentData()
        dest = Path(out_dir) / f"starpost_batch_{datetime.now():%Y%m%d_%H%M%S}.{fmt}"
        config = BatchConfig(
            sources=sources,
            reports=reports,
            report_format=self._report_format.currentText().lower(),
            include_units=self._report_include_units.isChecked(),
            saved_plots=saved_plots,
            saved_scenes=saved_scenes,
            include_dataset_csv=include_dataset_csv,
            combined_report=self._report_combined.isChecked(),
            archive_format=fmt,
        )
        runner = StarRunner(self._settings) if self._settings else None
        error = execute_batch(self, config, self._settings, runner, dest)
        if error is not None:
            QMessageBox.critical(self, "Run batch failed", error)
            return
        QMessageBox.information(self, "Run batch", f"Batch written to:\n{dest}")
        self.accept()

    def _retreat(self) -> None:
        """Back moves to the previous tab (disabled on the first)."""
        idx = self._tabs.currentIndex()
        if idx > 0:
            self._tabs.setCurrentIndex(idx - 1)
