"""Run-batch dialog: a sequential, tabbed wizard for configuring a batch run.

Five tabs (Source → Reports → Plots → Scenes → Summary), styled like the Export
dialog's tabs. The user advances with the bottom-right **Continue** button, which
becomes **Batch run** on the final Summary tab. The tab contents and the actual
run wiring are filled in later — this is the navigation scaffold only.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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

from starpost.core.settings import BatchProfile, list_batch_profiles
from starpost.gui.views.export_dialog import _PreviewWindow
from starpost.gui.views.plot_view import PlotView, _display_name
from starpost.gui.widgets import UniformTabBar

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

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setItemsExpandable(False)
        self.setExpandsOnDoubleClick(False)
        self.setSelectionMode(self.SelectionMode.NoSelection)
        # Groups whose monitors are all checked when the group is ticked
        # (residual plots), so the whole set plots together.
        self._auto_select_groups: set[str] = set()
        self.itemChanged.connect(self._on_item_changed)

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


class BatchRunDialog(QDialog):
    def __init__(
        self, parent=None, *, data_sets=None, report_names=None,
        monitor_groups=None, residual_groups=None, results=None, settings=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run batch")
        self.resize(820, 460)  # room for the Plots tab's three columns
        self._data_sets = list(data_sets or [])  # data-set names shown in "data" mode
        self._sim_files: list[Path] = []          # .sim files added via Load File
        self._report_names = list(report_names or [])  # all reports across the sims
        self._monitor_groups = dict(monitor_groups or {})  # group -> [monitor names]
        self._residual_groups = set(residual_groups or [])  # auto-select groups
        self._results = list(results or [])       # SimResults, for the plot preview
        self._settings = settings

        self._tabs = QTabWidget()
        bar = _LockedTabBar()
        bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # no keyboard focus either
        self._tabs.setTabBar(bar)
        self._tabs.addTab(self._build_source_tab(), "Source")
        self._tabs.addTab(self._build_reports_tab(), "Reports")
        self._plots_tab = self._build_plots_tab()
        self._tabs.addTab(self._plots_tab, "Plots")
        for name in _TAB_NAMES[3:]:
            self._tabs.addTab(QWidget(), name)
        # Keep the button label in step with the active tab, however it changed.
        self._tabs.currentChanged.connect(self._sync_button)
        # Open the plot preview window beside the dialog while the Plots tab shows.
        self._tabs.currentChanged.connect(self._update_preview)
        self.finished.connect(lambda _r: self._preview_window.close())

        # Bottom-left Back button (disabled on the first tab) and bottom-right
        # Continue button (becomes "Batch run" on the last tab).
        self._back = QPushButton("Back")
        self._back.clicked.connect(self._retreat)
        # "Add Plot" saves the current plot setup; only shown on the Plots tab.
        self._add_plot = QPushButton("Add Plot")
        self._add_plot.setVisible(False)
        self._add_plot.clicked.connect(self._on_add_plot)
        self._next = QPushButton()
        self._next.clicked.connect(self._advance)
        row = QHBoxLayout()
        row.addWidget(self._back)
        row.addStretch(1)
        row.addWidget(self._add_plot)
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
        # Nothing to apply yet — the batch settings a profile captures are wired
        # in later; this just resolves the saved profile.
        BatchProfile.load(name)

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
        BatchProfile(name=name).save()
        self._refresh_profiles()
        self._profile_box.setCurrentText(name)

    @staticmethod
    def _header(text: str) -> QLabel:
        """A bold section header label."""
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold;")
        return label

    # --- Source tab -------------------------------------------------------
    def _build_source_tab(self) -> QWidget:
        """Options on the left (the source-input dropdown + a 'Has similar format'
        checkbox); on the right a window listing the source entries (checkable),
        with Load / Select All / Clear buttons beneath it."""
        tab = QWidget()

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
        options.addWidget(self._has_similar_format)
        options.addStretch(1)

        self._source_window = _CheckableList()

        # Load File / Load Data Set are mutually exclusive (one per source mode);
        # Select All / Clear act on the window's checkboxes.
        self._load_file_btn = QPushButton("Load File")
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

        row = QHBoxLayout(tab)
        row.addLayout(options, 1)
        row.addLayout(right, 2)

        self._refresh_source_window()
        return tab

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

    def _has_checked_source(self) -> bool:
        """Whether at least one source entry is checked in the current window."""
        return any(
            self._source_window.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self._source_window.count())
        )

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

    # --- Reports tab ------------------------------------------------------
    def _build_reports_tab(self) -> QWidget:
        """Options on the left (file format, Include units, Separate files); a
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
        self._report_separate_files = QCheckBox("Separate files")  # no logic yet

        options = QVBoxLayout()
        options.addWidget(self._header("Options"))
        options.addWidget(QLabel("File format"))
        options.addWidget(self._report_format)
        options.addWidget(self._report_include_units)
        options.addWidget(self._report_separate_files)
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

        options = self._build_plot_options()

        monitors = QVBoxLayout()
        monitors.addWidget(self._header("Monitors"))
        monitors.addWidget(self._monitor_tree)

        # Saved Plots: plots the user has captured with "Add Plot" (each item
        # holds its plot characteristics in its data).
        self._saved_plots = QListWidget()
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
        """Plot options (a subset of the Export dialog's), live-applied to the
        preview: title, axis labels, theme, grid, image format."""
        self._plot_title = QLineEdit()
        self._plot_title.textChanged.connect(self._preview_set_title)
        self._plot_xlabel = QLineEdit()
        self._plot_xlabel.textChanged.connect(self._preview_set_xlabel)
        self._plot_ylabel = QLineEdit()
        self._plot_ylabel.textChanged.connect(self._preview_set_ylabel)
        self._plot_theme = QComboBox()
        self._plot_theme.addItem("Light", "light")
        self._plot_theme.addItem("Dark", "dark")
        self._plot_theme.currentIndexChanged.connect(self._preview_set_theme)
        self._plot_grid = QCheckBox("Show grid")
        self._plot_grid.setChecked(True)
        self._plot_grid.toggled.connect(self._preview_set_grid)
        self._plot_format = QComboBox()
        self._plot_format.addItems(["PNG", "JPG", "TIFF", "PDF"])

        form = QFormLayout()
        form.addRow("Plot title", self._plot_title)
        form.addRow("X axis label", self._plot_xlabel)
        form.addRow("Y axis label", self._plot_ylabel)
        form.addRow("Theme", self._plot_theme)
        form.addRow(self._plot_grid)
        form.addRow("Format", self._plot_format)

        col = QVBoxLayout()
        col.addWidget(self._header("Options"))
        col.addLayout(form)
        col.addStretch(1)
        return col

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
        is in front; hide them otherwise."""
        on_plots = self._tabs.currentWidget() is self._plots_tab
        self._add_plot.setVisible(on_plots)
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
        return {
            "title": self._plot_title.text(),
            "x_label": self._plot_xlabel.text(),
            "y_label": self._plot_ylabel.text(),
            "monitors": self._monitor_tree.checked_monitors(),
            "theme": self._plot_theme.currentData(),
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

    def _render_preview(self) -> None:
        """Draw the checked monitors into the preview for a SINGLE data set (the
        first loaded sim, as a representative). The batch run will later generate
        the same plot per data set; this preview is only for choosing the plot's
        appearance (title, colours, legend, …)."""
        selection = self._monitor_tree.checked_monitors()
        groups = set(selection)
        if not self._results or not groups:
            self._preview.clear()
            return
        plots = [p for p in self._results[0].plots if p.name in groups]
        if not plots:
            self._preview.clear()
            return
        self._preview.show_plots(plots)
        self._preview.set_monitor_selection(selection)

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

    def _on_summary(self) -> bool:
        return self._tabs.currentIndex() == self._tabs.count() - 1

    def _sync_button(self) -> None:
        self._next.setText("Batch run" if self._on_summary() else "Continue")
        self._back.setEnabled(self._tabs.currentIndex() > 0)

    def _advance(self) -> None:
        """Continue moves to the next tab; on Summary, "Batch run" finishes (the
        run itself is wired in later). Leaving the Source tab requires at least
        one selected source."""
        if self._tabs.currentIndex() == 0 and not self._has_checked_source():
            QMessageBox.warning(
                self, "Run batch",
                "No data selected. Select at least one source to continue.",
            )
            return
        if self._on_summary():
            self.accept()
        else:
            self._tabs.setCurrentIndex(self._tabs.currentIndex() + 1)

    def _retreat(self) -> None:
        """Back moves to the previous tab (disabled on the first)."""
        idx = self._tabs.currentIndex()
        if idx > 0:
            self._tabs.setCurrentIndex(idx - 1)
