"""Pick which reports/plots to view & export, with Select All + profile load/save.

Operates on the *union* of names discovered across the loaded batch (homogeneous
batches share one set; heterogeneous batches show everything with a warning).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionGroupBox,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from starpost.core.settings import DEFAULT_PROFILE_NAME, Profile, list_profiles
from starpost.gui.views.plot_view import _display_name


class _CheckList(QListWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Connect once. User-driven check toggles emit `changed`; programmatic
        # updates below block signals to avoid storms and emit explicitly.
        self.itemChanged.connect(lambda _: self.changed.emit())
        # Active name sort, A–Z by default. Toggled via the group title's
        # right-click menu and re-applied whenever the list is rebuilt.
        self.sort_mode = "az"  # "az" | "za"

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # QoL: clicking anywhere on a row toggles its checkbox, not just the
        # small indicator. The indicator still toggles natively, so we only
        # toggle here when the click landed elsewhere on the row.
        pos = event.position().toPoint()
        item = self.itemAt(pos)
        if (
            item is not None
            and event.button() == Qt.LeftButton
            and bool(item.flags() & Qt.ItemIsUserCheckable)
            and not self._on_check_indicator(item, pos)
        ):
            item.setCheckState(
                Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
            )
        super().mousePressEvent(event)

    def _on_check_indicator(self, item: QListWidgetItem, pos) -> bool:
        """Whether `pos` (viewport coords) falls on the item's checkbox indicator."""
        opt = QStyleOptionViewItem()
        opt.initFrom(self)
        opt.rect = self.visualItemRect(item)
        opt.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        rect = self.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, self
        )
        return rect.contains(pos)

    def _sorted(self, names) -> list[str]:
        """Order names by the active sort mode (case-insensitive)."""
        return sorted(names, key=str.lower, reverse=self.sort_mode == "za")

    def set_items(self, names: list[str], checked: bool = True) -> None:
        self.blockSignals(True)
        self.clear()
        state = Qt.Checked if checked else Qt.Unchecked
        for n in self._sorted(names):
            item = QListWidgetItem(n)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(state)
            self.addItem(item)
        self.blockSignals(False)

    def set_sort_mode(self, mode: str) -> None:
        """Switch the A–Z/Z–A order, re-sorting the existing items in place and
        preserving each one's check state (a pure reorder, no `changed` emit)."""
        if mode == self.sort_mode:
            return
        self.sort_mode = mode
        kept = [(self.item(i).text(), self.item(i).checkState())
                for i in range(self.count())]
        kept.sort(key=lambda t: t[0].lower(), reverse=mode == "za")
        self.blockSignals(True)
        self.clear()
        for text, st in kept:
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(st)
            self.addItem(item)
        self.blockSignals(False)

    def set_checked(self, names: set[str]) -> None:
        self.blockSignals(True)
        for i in range(self.count()):
            it = self.item(i)
            it.setCheckState(Qt.Checked if it.text() in names else Qt.Unchecked)
        self.blockSignals(False)

    def checked(self) -> list[str]:
        return [
            self.item(i).text()
            for i in range(self.count())
            if self.item(i).checkState() == Qt.Checked
        ]

    def texts(self) -> list[str]:
        return [self.item(i).text() for i in range(self.count())]

    def set_all(self, state: bool) -> None:
        self.blockSignals(True)
        s = Qt.Checked if state else Qt.Unchecked
        for i in range(self.count()):
            self.item(i).setCheckState(s)
        self.blockSignals(False)


class _MonitorPlotTree(QTreeWidget):
    """Monitor-plot picker: a tree of plot groups, each a checkable parent whose
    monitors appear as checkable children. Checking a group reveals its monitors
    (unticked, so the user picks deliberately); the checked monitors are the ones
    drawn. This mirrors the Monitors column of the export menu, moving the old
    under-plot dropdowns into the selection list itself.

    Exposes ``set_all`` / ``sort_mode`` / ``set_sort_mode`` so it slots into the
    same group box (Select all / Clear, right-click-to-sort) the report list uses.
    """

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        # Group expansion is driven solely by the group checkbox, so disable the
        # user-facing expand controls (arrows, double-click).
        self.setRootIsDecorated(False)
        self.setItemsExpandable(False)
        self.setExpandsOnDoubleClick(False)
        self.setSelectionMode(self.SelectionMode.NoSelection)
        # Show full monitor names: scroll horizontally rather than eliding.
        self.setTextElideMode(Qt.ElideNone)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Active sort, A–Z by default (matches the report list).
        self.sort_mode = "az"
        self._groups: dict[str, list[str]] = {}
        self.itemChanged.connect(self._on_item_changed)

    def _sorted(self, names) -> list[str]:
        return sorted(names, key=str.lower, reverse=self.sort_mode == "za")

    def set_items(self, groups: dict[str, list[str]], preserve: bool = False) -> None:
        """Rebuild the tree from ``{group: [monitor, ...]}``. With ``preserve`` the
        prior group/monitor check state is carried across (for sorting and for
        setting-driven refreshes); otherwise everything starts unticked."""
        prev_groups = set(self.checked_groups()) if preserve else set()
        prev_monitors = self.checked_monitors() if preserve else {}
        self._groups = {g: list(m) for g, m in groups.items()}
        self.blockSignals(True)
        self.clear()
        for g in self._sorted(self._groups):
            gi = QTreeWidgetItem([g])
            gi.setFlags((gi.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsSelectable)
            group_on = g in prev_groups
            gi.setCheckState(0, Qt.Checked if group_on else Qt.Unchecked)
            selected = set(prev_monitors.get(g, []))
            for m in self._sorted(self._groups[g]):
                # Show the collapsed label, keep the raw series name as the key.
                mi = QTreeWidgetItem([_display_name(m)])
                mi.setData(0, Qt.UserRole, m)
                mi.setFlags(
                    (mi.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsSelectable
                )
                mi.setCheckState(0, Qt.Checked if m in selected else Qt.Unchecked)
                gi.addChild(mi)
            self.addTopLevelItem(gi)
            gi.setExpanded(group_on)  # reveal monitors only for checked groups
        self.blockSignals(False)

    def _on_item_changed(self, item, _column) -> None:
        """Toggling a group reveals (expands) or hides (collapses) its monitors; a
        freshly checked group reveals them unticked so the user picks
        deliberately. Either change re-emits ``changed`` to drive a redraw."""
        if item.parent() is None:  # a group, not one of its monitors
            checked = item.checkState(0) == Qt.Checked
            item.setExpanded(checked)
            if checked:
                self.blockSignals(True)
                for j in range(item.childCount()):
                    item.child(j).setCheckState(0, Qt.Unchecked)
                self.blockSignals(False)
        self.changed.emit()

    # --- read ------------------------------------------------------------
    def checked_groups(self) -> list[str]:
        root = self.invisibleRootItem()
        return [
            root.child(i).text(0)
            for i in range(root.childCount())
            if root.child(i).checkState(0) == Qt.Checked
        ]

    def checked_monitors(self) -> dict[str, list[str]]:
        """The checked monitors per checked group (unchecked groups omitted)."""
        out: dict[str, list[str]] = {}
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            g = root.child(i)
            if g.checkState(0) != Qt.Checked:
                continue
            out[g.text(0)] = [
                g.child(j).data(0, Qt.UserRole)
                for j in range(g.childCount())
                if g.child(j).checkState(0) == Qt.Checked
            ]
        return out

    # --- write -----------------------------------------------------------
    def set_all(self, state: bool) -> None:
        """Check/uncheck every group and monitor (Select all / Clear)."""
        self.blockSignals(True)
        cs = Qt.Checked if state else Qt.Unchecked
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            g = root.child(i)
            g.setCheckState(0, cs)
            for j in range(g.childCount()):
                g.child(j).setCheckState(0, cs)
            g.setExpanded(state)
        self.blockSignals(False)

    def set_selection(self, groups: set[str], monitors: dict[str, list[str]]) -> None:
        """Apply a profile: check exactly ``groups`` and, for each, the monitors in
        ``monitors[group]``. A group absent from the map shows all its monitors
        (matching how older profiles, which stored no monitor map, load)."""
        self.blockSignals(True)
        root = self.invisibleRootItem()
        for i in range(root.childCount()):
            g = root.child(i)
            on = g.text(0) in groups
            g.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
            if g.text(0) in monitors:
                sel = set(monitors[g.text(0)])
            else:
                sel = {g.child(j).data(0, Qt.UserRole) for j in range(g.childCount())}
            for j in range(g.childCount()):
                m = g.child(j)
                m.setCheckState(
                    0, Qt.Checked if m.data(0, Qt.UserRole) in sel else Qt.Unchecked
                )
            g.setExpanded(on)
        self.blockSignals(False)

    def set_sort_mode(self, mode: str) -> None:
        """Re-sort groups and monitors A–Z/Z–A, preserving the selection."""
        if mode == self.sort_mode:
            return
        self.sort_mode = mode
        self.set_items(self._groups, preserve=True)


class _SortableGroupBox(QGroupBox):
    """A group box whose title responds to a right-click: clicking the title
    text invokes ``on_sort(global_pos)`` (to raise a sort menu). Right-clicks
    elsewhere on the box keep their default behaviour.
    """

    def __init__(self, title: str, on_sort, parent=None) -> None:
        super().__init__(title, parent)
        self._on_sort = on_sort

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt override)
        opt = QStyleOptionGroupBox()
        self.initStyleOption(opt)
        label = self.style().subControlRect(
            QStyle.ComplexControl.CC_GroupBox, opt,
            QStyle.SubControl.SC_GroupBoxLabel, self,
        )
        if label.contains(event.pos()):
            self._on_sort(event.globalPos())
            event.accept()
        else:
            super().contextMenuEvent(event)


class SelectionPanel(QWidget):
    selection_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.reports = _CheckList()
        # Monitor plots: a tree of groups whose checked monitors are the ones
        # drawn (the per-monitor selection lives here, not under the plot).
        self.plots = _MonitorPlotTree()
        self.reports.changed.connect(self.selection_changed)
        self.plots.changed.connect(self.selection_changed)

        # Region-statistics selection hooks (wired by MainWindow), so profiles can
        # persist it. The setter takes a list of stat labels, or None to reset to
        # the application default.
        self._region_stats_getter = None   # () -> list[str]
        self._region_stats_setter = None   # (list[str] | None) -> None

        # Profiles
        self._profile_box = QComboBox()
        self._refresh_profiles()
        load_btn = QPushButton("Load")
        load_btn.setToolTip("Load the selected profile's report and plot selection")
        save_btn = QPushButton("Save as…")
        save_btn.setToolTip("Save the current selection as a new profile")
        load_btn.clicked.connect(self._load_profile)
        save_btn.clicked.connect(self._save_profile)
        prof_row = QHBoxLayout()
        prof_row.addWidget(self._profile_box)
        prof_row.addWidget(load_btn)
        prof_row.addWidget(save_btn)

        # Only one checklist is shown at a time, matching the active centre tab
        # (Reports table vs. Plots view); the visible one expands to fill the
        # panel. set_active_section toggles between them.
        self._reports_group = self._group("Reports", self.reports)
        self._plots_group = self._group("Monitor plots", self.plots)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Profile"))
        layout.addLayout(prof_row)
        # Stretch 1 so the shown checklist fills all the vertical space the panel
        # has — including whatever the hidden section would have used.
        layout.addWidget(self._reports_group, 1)
        layout.addWidget(self._plots_group, 1)
        # Default to the Reports section (the centre opens on the Reports tab).
        self.set_active_section("reports")

    def set_active_section(self, section: str) -> None:
        """Show only the checklist relevant to the active centre tab: ``"reports"``
        shows the Reports list, any other value shows the Monitor plots list. The
        hidden group's space is given to the visible one, which fills the panel."""
        reports = section == "reports"
        self._reports_group.setVisible(reports)
        self._plots_group.setVisible(not reports)

    def _group(self, title: str, lst: _CheckList) -> QGroupBox:
        # Right-clicking the title sorts this list A–Z / Z–A.
        box = _SortableGroupBox(
            title, on_sort=lambda gp, lst=lst: self._show_sort_menu(lst, gp)
        )
        box.setToolTip("Right-click the title to sort A–Z / Z–A")
        all_on = QPushButton("Select all")
        all_on.setToolTip(f"Select every entry under {title}")
        all_off = QPushButton("Clear")
        all_off.setToolTip(f"Deselect every entry under {title}")
        all_on.clicked.connect(lambda: (lst.set_all(True), self.selection_changed.emit()))
        all_off.clicked.connect(lambda: (lst.set_all(False), self.selection_changed.emit()))
        row = QHBoxLayout()
        row.addWidget(all_on)
        row.addWidget(all_off)
        v = QVBoxLayout(box)
        v.addLayout(row)
        v.addWidget(lst)
        return box

    def _show_sort_menu(self, lst: _CheckList, global_pos) -> None:
        """Sort menu for a checklist, raised from its group title's right-click.
        The active mode shows a checkmark."""
        menu = QMenu(self)
        options = [("Name (A–Z)", "az"), ("Name (Z–A)", "za")]
        actions = {}
        for text, mode in options:
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(lst.sort_mode == mode)
            actions[act] = mode
        chosen = menu.exec(global_pos)
        if chosen is not None:
            lst.set_sort_mode(actions[chosen])

    # --- data ------------------------------------------------------------
    def populate(
        self, report_names: list[str], plot_groups: dict[str, list[str]]
    ) -> None:
        # Reports default to selected; plot groups default to *deselected* so the
        # plot view starts blank (rendering every monitor plot is slow with many).
        # ``plot_groups`` maps each plot group to its member monitor (series) names.
        self.reports.set_items(sorted(report_names), checked=True)
        self.plots.set_items(plot_groups, preserve=False)

    def set_available_reports(self, report_names: list[str]) -> None:
        """Replace the available report list while preserving check state.

        Used when a setting (e.g. hide-empty-reports) changes the visible set
        without reloading data — so the user's current selection isn't lost.
        Names appearing for the first time default to checked.
        """
        prev_all = set(self.reports.texts())
        prev_checked = set(self.reports.checked())
        names = sorted(report_names)
        keep = {n for n in names if n in prev_checked or n not in prev_all}
        self.reports.set_items(names, checked=False)
        self.reports.set_checked(keep)

    def set_available_plots(self, plot_groups: dict[str, list[str]]) -> None:
        """Refresh the monitor tree's groups/monitors while preserving the current
        selection — used when a setting (e.g. hide-empty-monitors) changes the
        visible set without reloading data."""
        self.plots.set_items(plot_groups, preserve=True)

    def selected_reports(self) -> set[str]:
        return set(self.reports.checked())

    def selected_plots(self) -> set[str]:
        """The checked monitor-plot groups."""
        return set(self.plots.checked_groups())

    def selected_monitors(self) -> dict[str, list[str]]:
        """The checked monitors per checked group: ``{group: [monitor, ...]}``."""
        return self.plots.checked_monitors()

    def set_region_stats_provider(self, getter, setter) -> None:
        """Wire callbacks for reading/restoring the region-statistics selection.

        `getter()` returns the shown stat labels; `setter(labels)` applies a
        list (or None to reset to the app default). Lets profiles persist it.
        """
        self._region_stats_getter = getter
        self._region_stats_setter = setter

    # --- profiles --------------------------------------------------------
    def refresh_profiles(self) -> None:
        """Reload the profile dropdown (e.g. after profiles are deleted)."""
        self._refresh_profiles()

    def _refresh_profiles(self) -> None:
        current = self._profile_box.currentText()
        self._profile_box.clear()
        # The built-in Default profile always leads the list.
        names = [DEFAULT_PROFILE_NAME] + [
            n for n in list_profiles() if n != DEFAULT_PROFILE_NAME
        ]
        self._profile_box.addItems(names)
        if current in names:
            self._profile_box.setCurrentText(current)

    def load_default_profile(self) -> None:
        """Select and apply the built-in Default profile (every available report,
        no monitor plots), e.g. after the settings are reset to defaults."""
        self._profile_box.setCurrentText(DEFAULT_PROFILE_NAME)
        self._load_profile()

    def _load_profile(self) -> None:
        name = self._profile_box.currentText()
        if not name:
            return
        if name == DEFAULT_PROFILE_NAME:
            # Built-in: every available report, no monitor plots.
            if self._region_stats_setter is not None:
                self._region_stats_setter(None)  # reset stats to the app default
            self.reports.set_all(True)
            self.plots.set_all(False)
            self.selection_changed.emit()
            return
        prof = Profile.load(name)
        # Restore the saved region statistics; profiles predating this leave the
        # current selection untouched (region_stats is None).
        if self._region_stats_setter is not None and prof.region_stats is not None:
            self._region_stats_setter(prof.region_stats)
        self.reports.set_checked(set(prof.reports))
        # Apply the saved plot groups and their per-group monitor selection.
        self.plots.set_selection(set(prof.plots), prof.monitors)
        self.selection_changed.emit()

    def _save_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
        if not ok or not name.strip():
            return
        if name.strip() == DEFAULT_PROFILE_NAME:
            QMessageBox.warning(
                self, "Save profile",
                f"“{DEFAULT_PROFILE_NAME}” is a reserved profile name.",
            )
            return
        # Saving over an existing profile silently replaces it, so confirm first.
        if name.strip() in list_profiles():
            confirm = QMessageBox.question(
                self, "Save profile",
                f"A profile named “{name.strip()}” already exists. "
                "Would you like to overwrite it?",
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        # Save the monitor selection only for the plots in this profile.
        plots = self.selected_plots()
        monitors = {
            p: m for p, m in self.plots.checked_monitors().items() if p in plots
        }
        region_stats = (
            self._region_stats_getter() if self._region_stats_getter else None
        )
        Profile(
            name=name.strip(),
            reports=sorted(self.selected_reports()),
            plots=sorted(plots),
            monitors=monitors,
            region_stats=region_stats,
        ).save()
        self._refresh_profiles()
        self._profile_box.setCurrentText(name.strip())
