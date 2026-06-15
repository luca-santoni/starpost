"""Export dialog: a tabbed shell mirroring the main interface's Reports/Plots
tabs.

Each tab is laid out as three columns. The Reports tab is Data / Reports /
Options; the Plots tab is Data / Monitors / Options. The Data column is shared
in spirit across both tabs (the same loaded data sets, kept in lock-step), while
the remaining columns are filled out per tab in later steps. The shape and tab
styling match the main window so the dialog feels like a focused view onto the
same Reports/Plots split.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from starpost.core.settings import DEFAULT_PROFILE_NAME, Profile, list_profiles
from starpost.gui.views.data_list import _CheckList
from starpost.gui.views.plot_view import _COLORS, PlotView, _display_name
from starpost.gui.widgets import UniformTabBar


class _PreviewWindow(QDialog):
    """Top-level window holding the plot preview. It can lock its size to a fixed
    aspect ratio (width / height): the window then keeps that ratio as it is
    resized. Dragging an edge scales the window proportionally — whichever side
    the drag changes drives the other — so a single-edge drag doesn't snap back
    (which left rendering artifacts). A ratio of None lets it resize freely."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._aspect: float | None = None
        self._adjusting = False  # guards the resize-inside-resizeEvent re-entry

    def set_aspect(self, ratio: float | None) -> None:
        """Lock the window to ``ratio`` (width/height), or None for free resize.
        A fixed ratio is applied immediately, keeping the current width."""
        self._aspect = ratio
        if ratio is not None:
            self.resize(self.width(), max(1, round(self.width() / ratio)))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if self._aspect is None or self._adjusting:
            return
        old = event.oldSize()
        w, h = event.size().width(), event.size().height()
        # A pure vertical-edge drag changes height but not width: scale width to
        # match. Anything else (horizontal edge or corner) scales height from
        # width. Exact equality — rather than a magnitude comparison — keeps the
        # choice stable, so corner drags don't wobble between the two.
        if old.width() == w and old.height() != h and old.height() > 0:
            target = max(1, round(h * self._aspect))
            if target != w:
                self._resize(target, h)
        else:
            target = max(1, round(w / self._aspect))
            if target != h:
                self._resize(w, target)

    def _resize(self, w: int, h: int) -> None:
        self._adjusting = True
        self.resize(w, h)
        self._adjusting = False


class _MonitorTree(QTreeWidget):
    """The Monitors tree, plus detection of clicks on a monitor's colour swatch
    (the icon between its checkbox and name). Such clicks emit ``swatch_clicked``
    instead of toggling the checkbox."""

    swatch_clicked = Signal(object)  # the monitor item whose swatch was clicked

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        pos = event.position().toPoint()
        item = self.itemAt(pos)
        # Only monitors (children) carry a swatch, and only while checked (icon set).
        if (
            item is not None
            and item.parent() is not None
            and not item.icon(0).isNull()
            and self._swatch_rect(item).contains(pos)
        ):
            self.swatch_clicked.emit(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def _swatch_rect(self, item) -> QRect:
        """The clickable band of the colour swatch: just right of the checkbox,
        one icon wide."""
        index = self.indexFromItem(item, 0)
        item_rect = self.visualRect(index)
        opt = QStyleOptionViewItem()
        opt.initFrom(self)
        opt.rect = item_rect
        opt.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        opt.checkState = item.checkState(0)
        check = self.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, self
        )
        return QRect(
            check.right() + 2, item_rect.top(), self.iconSize().width() + 6,
            item_rect.height(),
        )


class ExportDialog(QDialog):
    def __init__(
        self,
        default_dir: str = "",
        data_names: list[str] | None = None,
        checked_names: list[str] | None = None,
        report_names: list[str] | None = None,
        checked_reports: list[str] | None = None,
        monitor_groups: dict[str, list[str]] | None = None,
        checked_groups: list[str] | None = None,
        checked_monitors: dict[str, list[str]] | None = None,
        results=None,
        settings=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.resize(660, 460)

        # Kept for the export wiring that will live inside the tabs.
        self._default_dir = default_dir
        # Loaded results (the actual plot data) and app settings, used to draw the
        # plot preview that opens in its own window.
        self._results = list(results or [])
        self._settings = settings
        # Loaded data sets and available reports, mirroring the main window, with
        # the same entries ticked as are selected there when the dialog opens.
        self._data_names = list(data_names or [])
        self._checked_names = set(checked_names or [])
        self._report_names = list(report_names or [])
        self._checked_reports = set(checked_reports or [])
        # Monitor groups (plots) and their member monitors (series), plus which
        # groups/monitors are selected in the main window's plot view.
        self._monitor_groups = dict(monitor_groups or {})
        self._checked_groups = set(checked_groups or [])
        self._checked_monitors = {
            k: list(v) for k, v in (checked_monitors or {}).items()
        }

        tabs = QTabWidget()
        tabs.setTabBar(UniformTabBar())
        self._reports_tab = self._build_reports_tab()
        self._plots_tab = self._build_plots_tab()
        tabs.addTab(self._reports_tab, "Reports")
        tabs.addTab(self._plots_tab, "Plots")

        # Keep the two tabs' Data columns in lock-step, and initialise the
        # "Separate files" enabled state from the shared selection.
        self._wire_data_sync()

        # Open the preview window when the Plots tab is brought to the front, and
        # close it together with the dialog.
        self._tabs = tabs
        tabs.currentChanged.connect(self._on_tab_changed)
        self.finished.connect(lambda _r: self._preview_window.close())

        # Match the main interface: give both tabs the width of the wider one.
        bar = tabs.tabBar()
        width = max(bar.tabSizeHint(i).width() for i in range(tabs.count()))
        bar.set_tab_width(width)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self._on_export)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_profile_bar())
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    # --- profiles --------------------------------------------------------
    def _build_profile_bar(self) -> QHBoxLayout:
        """A right-aligned Profile dropdown + Load button (matching the main
        window's profile menu), at the top of the dialog. Load only — saving
        profiles stays in the main window."""
        self._profile_box = QComboBox()
        names = [DEFAULT_PROFILE_NAME] + [
            n for n in list_profiles() if n != DEFAULT_PROFILE_NAME
        ]
        self._profile_box.addItems(names)
        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._load_profile)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(QLabel("Profile"))
        row.addWidget(self._profile_box)
        row.addWidget(load_btn)
        return row

    def _load_profile(self) -> None:
        """Apply the selected profile's report and monitor selections (data-set
        and per-tab options are left as-is — profiles don't store them)."""
        name = self._profile_box.currentText()
        if not name:
            return
        if name == DEFAULT_PROFILE_NAME:
            # Built-in: every available report, no monitor groups.
            reports = {
                self._report_list.item(i).text()
                for i in range(self._report_list.count())
            }
            groups_on: set[str] = set()
            monitors: dict[str, list[str]] = {}
        else:
            prof = Profile.load(name)
            reports = set(prof.reports)
            groups_on = set(prof.plots)
            monitors = prof.monitors

        self._apply_profile_reports(reports)
        self._apply_profile_monitors(groups_on, monitors)
        self._refresh_preview_if_visible()

    def _apply_profile_reports(self, checked: set[str]) -> None:
        lst = self._report_list
        lst.blockSignals(True)
        for i in range(lst.count()):
            item = lst.item(i)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.text() in checked
                else Qt.CheckState.Unchecked
            )
        lst.blockSignals(False)

    def _apply_profile_monitors(
        self, groups_on: set[str], monitors: dict[str, list[str]]
    ) -> None:
        tree = self._monitor_tree
        tree.blockSignals(True)
        root = tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            on = group.text(0) in groups_on
            group.setCheckState(
                0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
            )
            # A group absent from the profile's monitor map shows all its monitors.
            if group.text(0) in monitors:
                selected = set(monitors[group.text(0)])
            else:
                selected = {
                    group.child(j).data(0, Qt.ItemDataRole.UserRole)
                    for j in range(group.childCount())
                }
            for j in range(group.childCount()):
                m = group.child(j)
                raw = m.data(0, Qt.ItemDataRole.UserRole)
                m.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if raw in selected
                    else Qt.CheckState.Unchecked,
                )
            group.setExpanded(on)
        tree.blockSignals(False)

    # --- export ----------------------------------------------------------
    def _on_export(self) -> None:
        """The Export button: act on whichever tab is in front."""
        if self._tabs.currentWidget() is self._reports_tab:
            self._export_reports()
        else:
            self._export_plot()

    def _export_plot(self) -> None:
        """Export a high-quality image of the plot preview in the chosen Format.
        The user names the file (default: the data set's name for a single data
        set, else "plot") via the native save dialog."""
        active = [
            r for r in self._results if r.sim_name in set(self.checked_data_names())
        ]
        if not active or not self.checked_monitor_groups():
            QMessageBox.information(
                self, "Export", "Select data sets and monitors to plot first."
            )
            return

        # Make sure the preview reflects the current selection before capturing.
        self._render_preview()
        if not self._preview.has_content():
            QMessageBox.information(
                self, "Export", "Nothing is plotted — select monitors to show."
            )
            return

        fmt = self._plot_format.currentText().lower()
        default = active[0].sim_name if len(active) == 1 else "plot"
        path = self._ask_save_path(default, fmt)
        if path is None:
            return
        try:
            self._preview.export(path, fmt)
        except Exception as exc:  # surface any render/write error to the user
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.accept()

    def _export_reports(self) -> None:
        """Export the selected reports for the selected data sets, in the chosen
        format. The user names the file via the native save dialog (opened in the
        default output folder). With "Separate files" on, one file per data set
        is written, each named in turn."""
        from starpost.batch.aggregator import reports_wide_frame, write_report_table

        names = set(self.checked_data_names())
        reports = set(self.checked_report_names())
        if not names:
            QMessageBox.information(self, "Export", "Select at least one data set.")
            return
        if not reports:
            QMessageBox.information(self, "Export", "Select at least one report.")
            return

        results = [r for r in self._results if r.sim_name in names]
        fmt = self.file_format()
        units = self.include_units()

        try:
            if self.separate_files():
                # One file per data set; the user names each in turn. Cancelling
                # any prompt aborts the whole export.
                for res in results:
                    path = self._ask_save_path(res.sim_name, fmt)
                    if path is None:
                        return
                    # Same layout as a singular-file export, just one sim per file.
                    df = reports_wide_frame([res], reports, units).reset_index()
                    write_report_table(df, path, fmt)
            else:
                # A single data set is named after it; combining several keeps
                # the generic "reports".
                default = results[0].sim_name if len(results) == 1 else "reports"
                path = self._ask_save_path(default, fmt)
                if path is None:
                    return
                df = reports_wide_frame(results, reports, units).reset_index()
                write_report_table(df, path, fmt)
        except Exception as exc:  # surface any write/engine error to the user
            QMessageBox.critical(self, "Export failed", str(exc))
            return

        self.accept()

    def _ask_save_path(self, default_name: str, fmt: str):
        """Native save dialog in the default output folder, pre-named and filtered
        to ``fmt``. Returns the chosen Path (with the right suffix) or None if the
        user cancelled."""
        ext = f".{fmt}"
        start_dir = self._default_dir or str(Path.home())
        start = str(Path(start_dir) / f"{default_name}{ext}")
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Export", start, f"{fmt.upper()} file (*{ext})"
        )
        if not chosen:
            return None
        path = Path(chosen)
        if path.suffix.lower() != ext:
            path = path.with_suffix(ext)
        return path

    def _build_reports_tab(self) -> QWidget:
        """The Reports tab is split into three columns, left to right: Data
        (which data sets to export), Reports (which reports), and Options (how).
        Data and Reports mirror the main window's selections; Options is an empty
        header for now — its controls are added in later steps."""
        tab = QWidget()

        self._reports_data = QGroupBox("Data")
        self._reports_reports = QGroupBox("Reports")
        self._reports_options = QGroupBox("Options")

        # Data and Reports columns mirror the main window: every entry has a
        # checkbox, ticked to match what is selected there when the dialog opens.
        self._data_list = self._checklist(self._data_names, self._checked_names)
        QVBoxLayout(self._reports_data).addWidget(self._data_list)

        self._report_list = self._checklist(self._report_names, self._checked_reports)
        QVBoxLayout(self._reports_reports).addWidget(self._report_list)

        self._build_options(self._reports_options)

        row = QHBoxLayout(tab)
        for box in (self._reports_data, self._reports_reports, self._reports_options):
            row.addWidget(box, 1)
        return tab

    def _build_plots_tab(self) -> QWidget:
        """The Plots tab mirrors the Reports tab's three-column shape: Data,
        Monitors, Options. The plot preview lives in its own separate window
        (built here, opened when this tab is shown — see _on_tab_changed)."""
        tab = QWidget()

        self._plots_data = QGroupBox("Data")
        self._plots_monitors = QGroupBox("Monitors")
        self._plots_options = QGroupBox("Options")

        self._plots_data_list = self._checklist(self._data_names, self._checked_names)
        QVBoxLayout(self._plots_data).addWidget(self._plots_data_list)

        self._build_monitors(self._plots_monitors)
        self._build_plot_options(self._plots_options)

        row = QHBoxLayout(tab)
        for box in (self._plots_data, self._plots_monitors, self._plots_options):
            row.addWidget(box, 1)

        # Preview of the exported plot, in a separate top-level window so it sits
        # apart from the export menu. Parented to the dialog so it's owned/cleaned
        # up with it, but stays interactive alongside the modal export dialog.
        self._preview = PlotView()
        self._configure_preview()
        self._preview_window = _PreviewWindow(self)
        self._preview_window.setWindowTitle("Plot preview")
        self._preview_window.resize(720, 480)
        pv = QVBoxLayout(self._preview_window)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(self._preview)

        return tab

    def _configure_preview(self) -> None:
        """Match the preview's filtering, hover and theme to the app settings so
        it looks like the main window's plot."""
        # The Monitors list in this dialog drives which series are shown, so the
        # plot's own per-category dropdowns are hidden on the preview.
        self._preview.set_category_controls_visible(False)
        s = self._settings
        if s is None:
            return
        self._preview.set_filter(s.hide_empty_monitors, s.monitor_zero_threshold)
        self._preview.set_hover_options(
            s.hover_show_monitor_name, s.hover_x_decimals, s.hover_y_decimals
        )
        self._preview.set_region_stats(s.region_stats)
        self._preview.apply_theme(s.appearance.mode)

    def _on_tab_changed(self, _index) -> None:
        """Open the preview window beside the Plots tab; hide it otherwise."""
        if self._tabs.currentWidget() is self._plots_tab:
            # Place it just to the right of the export menu rather than over it.
            frame = self.frameGeometry()
            self._preview_window.move(frame.right() + 8, frame.top())
            self._preview_window.show()
            self._preview_window.raise_()
            self._refresh_preview()
        else:
            self._preview_window.hide()

    def _refresh_preview_if_visible(self) -> None:
        if self._tabs.currentWidget() is self._plots_tab:
            self._refresh_preview()

    def _refresh_preview(self) -> None:
        """Redraw the preview, then sync the monitor colour swatches to match the
        colours actually drawn."""
        self._render_preview()
        self._refresh_monitor_swatches()

    def _render_preview(self) -> None:
        """Draw the currently selected monitors into the preview, mirroring how
        the main window renders plots: a comparison when 2+ data sets are
        selected, otherwise a single-file view. Only checked groups are shown,
        and within each only the checked monitors."""
        active_names = set(self.checked_data_names())
        active = [r for r in self._results if r.sim_name in active_names]
        groups = set(self.checked_monitor_groups())
        if not active or not groups:
            self._preview.clear()
            return

        if len(active) >= 2:
            categories = []
            for group in sorted(groups, key=str.lower):
                pairs = [
                    (r.sim_name, p)
                    for r in active
                    for p in r.plots
                    if p.name == group
                ]
                if pairs:
                    categories.append((group, pairs))
            if not categories:
                self._preview.clear()
                return
            self._preview.show_comparison(categories)
        else:
            plots = [p for p in active[0].plots if p.name in groups]
            if not plots:
                self._preview.clear()
                return
            self._preview.show_plots(plots)

        # Restrict each group to the monitors ticked in the Monitors column.
        self._preview.set_monitor_selection(self.checked_monitors())

    def _build_plot_options(self, box: QGroupBox) -> None:
        """Options column for the Plots tab. Framework only — the controls are
        created with the right widget type but are not wired up yet (dropdowns
        are left empty; their choices and behaviour come in later steps)."""
        self._plot_aspect = QComboBox()
        self._plot_aspect.addItems(["1:1", "3:2", "4:3", "16:9", "Custom"])
        self._plot_aspect.setCurrentText("Custom")  # free resize by default
        # Connect after setting the default so it doesn't fire during setup (the
        # preview window is also created later in _build_plots_tab).
        self._plot_aspect.currentTextChanged.connect(self._on_aspect_changed)
        # Title and axis labels live-update the preview as the user types; an
        # empty field reverts that label to the plot's auto value.
        self._plot_title = QLineEdit()
        self._plot_title.textChanged.connect(
            lambda t: self._preview.set_title_override(t)
        )
        self._plot_xlabel = QLineEdit()
        self._plot_xlabel.textChanged.connect(
            lambda t: self._preview.set_x_label_override(t)
        )
        self._plot_ylabel = QLineEdit()
        self._plot_ylabel.textChanged.connect(
            lambda t: self._preview.set_y_label_override(t)
        )
        # Theme defaults to the program's current theme (the preview is already
        # themed to match); changing it re-themes the preview.
        self._plot_theme = QComboBox()
        self._plot_theme.addItems(["Light", "Dark"])
        mode = self._settings.appearance.mode if self._settings else "dark"
        self._plot_theme.setCurrentText(mode.capitalize())
        self._plot_theme.currentTextChanged.connect(
            lambda t: self._preview.apply_theme(t.lower())
        )
        # Output image format for the rendered plot (wired to plot export later).
        self._plot_format = QComboBox()
        self._plot_format.addItems(["PNG", "JPG", "TIFF", "PDF"])

        form = QFormLayout(box)
        form.addRow("Aspect ratio", self._plot_aspect)
        form.addRow("Plot title", self._plot_title)
        form.addRow("X axis label", self._plot_xlabel)
        form.addRow("Y axis label", self._plot_ylabel)
        form.addRow("Theme", self._plot_theme)
        form.addRow("Format", self._plot_format)

    def _on_aspect_changed(self, text: str) -> None:
        """Apply the chosen aspect ratio to the preview window. "Custom" (or any
        non-ratio text) frees it to resize to any size."""
        if ":" not in text:  # "Custom"
            self._preview_window.set_aspect(None)
            return
        w, h = text.split(":")
        self._preview_window.set_aspect(int(w) / int(h))

    def _build_monitors(self, box: QGroupBox) -> None:
        """Monitors column: a tree of monitor groups, each with a checkbox. A
        group's monitors are revealed only while the group is checked; unchecking
        a group hides its monitor list. Group and per-monitor ticks mirror the
        main window's plot selection when the dialog opens."""
        self._monitor_tree = _MonitorTree()
        self._monitor_tree.setHeaderHidden(True)
        self._monitor_tree.setIconSize(QSize(14, 14))  # colour swatch size
        self._monitor_tree.swatch_clicked.connect(self._pick_monitor_color)
        # Visibility of a group's monitors is driven solely by its checkbox, so
        # disable the user-facing expand controls (arrows, double-click).
        self._monitor_tree.setRootIsDecorated(False)
        self._monitor_tree.setItemsExpandable(False)
        self._monitor_tree.setExpandsOnDoubleClick(False)
        # Show full monitor names: let the column grow to its contents and add a
        # horizontal scroll bar rather than eliding long labels.
        self._monitor_tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._monitor_tree.header().setStretchLastSection(False)
        self._monitor_tree.header().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._monitor_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self._monitor_tree.blockSignals(True)  # building shouldn't fire itemChanged
        for group in sorted(self._monitor_groups, key=str.lower):
            monitors = self._monitor_groups[group]
            group_on = group in self._checked_groups
            # Groups the plot view never showed have no remembered monitor
            # selection; fall back to all monitors, as the plot view does.
            selected = set(self._checked_monitors.get(group, monitors))

            gi = QTreeWidgetItem([group])
            gi.setFlags(
                (gi.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                & ~Qt.ItemFlag.ItemIsSelectable
            )
            gi.setCheckState(
                0, Qt.CheckState.Checked if group_on else Qt.CheckState.Unchecked
            )
            for mon in sorted(monitors, key=str.lower):
                # Show the collapsed label, but keep the raw series name (the
                # selection/lookup key) in the item's data.
                mi = QTreeWidgetItem([_display_name(mon)])
                mi.setData(0, Qt.ItemDataRole.UserRole, mon)
                mi.setFlags(
                    (mi.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    & ~Qt.ItemFlag.ItemIsSelectable
                )
                mi.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if mon in selected
                    else Qt.CheckState.Unchecked,
                )
                gi.addChild(mi)
            self._monitor_tree.addTopLevelItem(gi)
            gi.setExpanded(group_on)  # reveal monitors only for checked groups
            # (after addTopLevelItem, else it has no effect)
        self._monitor_tree.blockSignals(False)
        self._monitor_tree.itemChanged.connect(self._on_monitor_item_changed)

        QVBoxLayout(box).addWidget(self._monitor_tree)

    def _on_monitor_item_changed(self, item, _column) -> None:
        """Toggling a group reveals (expands) or hides (collapses) its monitors.
        Selecting a group does not select any of its monitors — they are revealed
        unticked so the user picks them deliberately. Either kind of change
        refreshes the preview."""
        if item.parent() is None:  # a group, not one of its monitors
            checked = item.checkState(0) == Qt.CheckState.Checked
            item.setExpanded(checked)
            if checked:
                self._monitor_tree.blockSignals(True)
                for j in range(item.childCount()):
                    item.child(j).setCheckState(0, Qt.CheckState.Unchecked)
                self._monitor_tree.blockSignals(False)
        self._refresh_preview_if_visible()

    # --- monitor colour swatches ----------------------------------------
    @staticmethod
    def _color_icon(color: str) -> QIcon:
        """A filled square swatch of ``color`` for the tree / colour menu."""
        px = QPixmap(14, 14)
        px.fill(QColor(color))
        return QIcon(px)

    def _refresh_monitor_swatches(self) -> None:
        """Give every checked monitor a colour swatch matching its plot colour;
        clear the swatch on unchecked ones. Done with signals blocked so setting
        an icon doesn't re-trigger itemChanged."""
        tree = self._monitor_tree
        tree.blockSignals(True)
        root = tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            for j in range(group.childCount()):
                m = group.child(j)
                if m.checkState(0) == Qt.CheckState.Checked:
                    name = m.data(0, Qt.ItemDataRole.UserRole)
                    color = self._preview.series_color(name) or "#888888"
                    m.setIcon(0, self._color_icon(color))
                else:
                    m.setIcon(0, QIcon())
        tree.blockSignals(False)

    def _pick_monitor_color(self, item) -> None:
        """Colour menu for a monitor's swatch: pick a palette colour (or a custom
        one); the choice recolours the monitor in the preview and its swatch."""
        name = item.data(0, Qt.ItemDataRole.UserRole)
        current = self._preview.series_color(name)
        menu = QMenu(self)
        for c in _COLORS:
            act = menu.addAction(self._color_icon(c), c)
            act.setData(c)
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

    def _wire_data_sync(self) -> None:
        """Mirror the two tabs' Data columns onto each other so toggling a data
        set in either tab updates the other, and refresh the "Separate files"
        enabled state (which keys off the shared selection)."""
        self._data_list.itemChanged.connect(self._on_reports_data_changed)
        self._plots_data_list.itemChanged.connect(self._on_plots_data_changed)
        self._update_separate_enabled()

    def _on_reports_data_changed(self, _item) -> None:
        self._mirror_checks(self._data_list, self._plots_data_list)
        self._update_separate_enabled()
        self._refresh_preview_if_visible()

    def _on_plots_data_changed(self, _item) -> None:
        self._mirror_checks(self._plots_data_list, self._data_list)
        self._update_separate_enabled()
        self._refresh_preview_if_visible()

    def _mirror_checks(self, src: _CheckList, dst: _CheckList) -> None:
        """Copy ``src``'s checked state onto ``dst`` (matched by row text),
        without emitting ``dst``'s itemChanged so the mirror can't loop back."""
        checked = set(self._checked(src))
        dst.blockSignals(True)
        for i in range(dst.count()):
            item = dst.item(i)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.text() in checked
                else Qt.CheckState.Unchecked
            )
        dst.blockSignals(False)

    def _build_options(self, box: QGroupBox) -> None:
        """Options column: output file format and a couple of toggles."""
        self._format = QComboBox()
        self._format.addItems(["CSV", "TSV", "XLSX", "ODS"])

        self._include_units = QCheckBox("Include units")
        self._include_units.setChecked(True)

        self._separate_files = QCheckBox("Separate files")
        self._separate_files.setToolTip(
            "Export each data set to its own file instead of combining them into "
            "one (requires two or more data sets)."
        )

        form = QFormLayout(box)
        form.addRow("File format", self._format)
        form.addRow(self._include_units)
        form.addRow(self._separate_files)

    def _update_separate_enabled(self) -> None:
        """Grey out "Separate files" unless at least two data sets are selected —
        with fewer there is nothing to split apart."""
        self._separate_files.setEnabled(len(self.checked_data_names()) >= 2)

    @staticmethod
    def _checklist(names: list[str], checked: set[str]) -> _CheckList:
        """A click-to-toggle checklist (as in the main window) listing ``names``
        A–Z, with those in ``checked`` ticked."""
        lst = _CheckList()
        lst.setSelectionMode(_CheckList.NoSelection)
        for name in sorted(names, key=str.lower):
            item = QListWidgetItem(name)
            item.setFlags(
                (item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                & ~Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(
                Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked
            )
            lst.addItem(item)
        return lst

    @staticmethod
    def _checked(lst: _CheckList) -> list[str]:
        return [
            lst.item(i).text()
            for i in range(lst.count())
            if lst.item(i).checkState() == Qt.CheckState.Checked
        ]

    def checked_data_names(self) -> list[str]:
        """The data sets currently ticked in the Data column."""
        return self._checked(self._data_list)

    def checked_report_names(self) -> list[str]:
        """The reports currently ticked in the Reports column."""
        return self._checked(self._report_list)

    def checked_monitor_groups(self) -> list[str]:
        """The monitor groups currently ticked in the Monitors column."""
        root = self._monitor_tree.invisibleRootItem()
        return [
            root.child(i).text(0)
            for i in range(root.childCount())
            if root.child(i).checkState(0) == Qt.CheckState.Checked
        ]

    def checked_monitors(self) -> dict[str, list[str]]:
        """The ticked monitors per ticked group (unchecked groups are omitted)."""
        out: dict[str, list[str]] = {}
        root = self._monitor_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            if group.checkState(0) != Qt.CheckState.Checked:
                continue
            out[group.text(0)] = [
                group.child(j).data(0, Qt.ItemDataRole.UserRole)
                for j in range(group.childCount())
                if group.child(j).checkState(0) == Qt.CheckState.Checked
            ]
        return out

    def file_format(self) -> str:
        """The chosen output format, lower-cased (e.g. "csv")."""
        return self._format.currentText().lower()

    def include_units(self) -> bool:
        return self._include_units.isChecked()

    def separate_files(self) -> bool:
        """Whether to write one file per data set. Always False when the control
        is disabled (fewer than two data sets selected)."""
        return self._separate_files.isEnabled() and self._separate_files.isChecked()
