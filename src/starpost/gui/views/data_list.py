"""Left 'Data' tab: the data sets loaded from .sim files, organisable into
virtual folders.

Mirrors the Files tab's folder system — right-click empty space for "New
Folder", drag data sets/folders to re-parent them, and nest folders to any
depth — but for extracted data sets rather than .sim files. Each data set is a
**checkable** row; checking it selects which sets feed the Reports/Plots views.

The set of data sets is supplied by the main window via :meth:`set_entries`
(driven by the store); the folder layout the user builds is owned and persisted
here, and reconciled against the live data on each ``set_entries`` call.
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Reuse the Files tab's folder-icon tinting and the nested-row dash so the two
# tabs look identical. Both tag item type at UserRole+1, so the dash delegate
# (which skips folders) works unchanged for data rows too.
from starpost.gui.views.file_list import _NestedDashDelegate, _tinted_icon
from starpost.utils.paths import data_list_cache_path

# Item data roles and the type tag they carry (matching file_list's layout).
_NAME_ROLE = int(Qt.ItemDataRole.UserRole)      # a data set's name (str)
_TYPE_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # "data" or "folder"
_SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 2  # a folder's chosen sort mode

DEFAULT_SORT = "name_az"  # A–Z, used by the tab sort and each new folder
CACHE_VERSION = 1

# Data sets can be dragged and checked but not dropped onto; folders accept
# drops so data sets/folders can be moved inside them, but aren't checkable.
_DATA_FLAGS = (
    Qt.ItemFlag.ItemIsEnabled
    | Qt.ItemFlag.ItemIsSelectable
    | Qt.ItemFlag.ItemIsDragEnabled
    | Qt.ItemFlag.ItemIsUserCheckable
)
_FOLDER_FLAGS = (
    Qt.ItemFlag.ItemIsEnabled
    | Qt.ItemFlag.ItemIsSelectable
    | Qt.ItemFlag.ItemIsDragEnabled
    | Qt.ItemFlag.ItemIsDropEnabled
)


class _CheckList(QListWidget):
    """A flat list whose rows toggle their checkbox when clicked anywhere, not
    just on the small indicator.

    Kept here as a lightweight, reusable checklist: the export dialogs
    (``export_dialog`` and ``data_export_dialog``) build their Data/Reports
    columns from it. The Data tab itself now uses the folder tree below.
    """

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Only the left button toggles; right-click falls through so a context
        # menu can open instead.
        item = self.itemAt(event.position().toPoint())
        if item is not None and event.button() == Qt.MouseButton.LeftButton:
            checked = item.checkState() == Qt.CheckState.Checked
            item.setCheckState(
                Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
            )
            event.accept()  # we handled the toggle; skip the default indicator hit
            return
        super().mousePressEvent(event)


def _is_folder(item: QTreeWidgetItem) -> bool:
    return item.data(0, _TYPE_ROLE) == "folder"


class _DataTree(QTreeWidget):
    """A tree whose drag-drop re-parents items (refusing a folder into its own
    subtree). A plain click anywhere on a data row toggles its checkbox, while a
    press-and-drag re-parents instead — so checking and organising coexist."""

    dropped = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._press_pos = None
        self._press_item: QTreeWidgetItem | None = None
        self._press_on_check = False

    # --- drag-drop -------------------------------------------------------
    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        target = self._drop_parent(event)
        for item in self.selectedItems():
            if _is_folder(item) and self._is_self_or_descendant(item, target):
                event.ignore()
                return
        # A move recreates the items; carry each data set's check state across.
        states = self._capture_checks()
        super().dropEvent(event)
        self._restore_checks(states)
        self.dropped.emit()

    def _drop_parent(self, event) -> QTreeWidgetItem | None:
        item = self.itemAt(event.position().toPoint())
        indicator = self.dropIndicatorPosition()
        if item is None or indicator == QAbstractItemView.DropIndicatorPosition.OnViewport:
            return None
        if (
            indicator == QAbstractItemView.DropIndicatorPosition.OnItem
            and _is_folder(item)
        ):
            return item
        return item.parent()

    @staticmethod
    def _is_self_or_descendant(
        folder: QTreeWidgetItem, target: QTreeWidgetItem | None
    ) -> bool:
        node = target
        while node is not None:
            if node is folder:
                return True
            node = node.parent()
        return False

    def _capture_checks(self) -> dict[str, Qt.CheckState]:
        out: dict[str, Qt.CheckState] = {}
        for item in self._iter_all():
            if not _is_folder(item):
                out[item.data(0, _NAME_ROLE)] = item.checkState(0)
        return out

    def _restore_checks(self, states: dict[str, Qt.CheckState]) -> None:
        self.blockSignals(True)
        for item in self._iter_all():
            if not _is_folder(item) and item.data(0, _NAME_ROLE) in states:
                item.setCheckState(0, states[item.data(0, _NAME_ROLE)])
        self.blockSignals(False)

    def _iter_all(self, parent: QTreeWidgetItem | None = None):
        count = self.topLevelItemCount() if parent is None else parent.childCount()
        for i in range(count):
            item = self.topLevelItem(i) if parent is None else parent.child(i)
            yield item
            if _is_folder(item):
                yield from self._iter_all(item)

    # --- click-to-check (preserved alongside drag) -----------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        pos = event.position().toPoint()
        self._press_pos = pos
        self._press_item = self.itemAt(pos)
        self._press_on_check = (
            self._press_item is not None
            and not _is_folder(self._press_item)
            and self._on_check_indicator(self._press_item, pos)
        )
        super().mousePressEvent(event)  # selection + (on move) drag start

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().mouseReleaseEvent(event)
        item = self._press_item
        self._press_item = None
        # Toggle only on a genuine left-click on a data row away from the native
        # checkbox indicator (which Qt already toggles) and not after a drag.
        if (
            item is None
            or event.button() != Qt.MouseButton.LeftButton
            or _is_folder(item)
            or self._press_on_check
        ):
            return
        rel = event.position().toPoint()
        if (rel - self._press_pos).manhattanLength() > QApplication.startDragDistance():
            return
        if self.itemAt(rel) is not item:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        item.setCheckState(
            0, Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
        )

    def _on_check_indicator(self, item: QTreeWidgetItem, pos) -> bool:
        """Whether ``pos`` (viewport coords) falls on the row's checkbox."""
        opt = QStyleOptionViewItem()
        opt.initFrom(self)
        opt.rect = self.visualItemRect(item)
        opt.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        rect = self.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, self
        )
        return rect.contains(pos)


class DataListPanel(QWidget):
    # Emitted when the set of checked entries changes.
    selection_changed = Signal()
    import_requested = Signal()
    export_requested = Signal()
    delete_requested = Signal()  # delete the checked data sets
    clear_requested = Signal()
    properties_requested = Signal(object)  # a data set name to show properties for
    # A folder's name and its contained data set names, for aggregate properties.
    folder_properties_requested = Signal(object, object)

    def __init__(self, parent=None, *, folder_color: str = "") -> None:
        super().__init__(parent)
        # Active tab-wide sort, kept in sync with the right-click menu's checkmark.
        self._sort_mode = DEFAULT_SORT
        # Folder icon: the standard one, optionally tinted to a chosen colour
        # ("" = leave the default icon as-is). Mirrors the Files tab.
        self._base_folder_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_DirIcon
        )
        self._folder_color = folder_color or ""
        self._folder_icon = self._build_folder_icon()

        self._tree = _DataTree()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setItemDelegateForColumn(0, _NestedDashDelegate(self._tree))
        self._tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._tree.setDragEnabled(True)
        self._tree.setAcceptDrops(True)
        self._tree.dropped.connect(self._on_dropped)
        # A checkbox toggle (click or drag-in) changes which sets feed the views.
        self._tree.itemChanged.connect(self._on_item_changed)
        # Persist a folder's open/closed state when the user expands or collapses
        # it (programmatic changes during load/rebuild block the tree's signals,
        # so they don't trigger a save).
        self._tree.itemExpanded.connect(self._on_expansion_changed)
        self._tree.itemCollapsed.connect(self._on_expansion_changed)

        import_btn = QPushButton("Import")
        import_btn.setToolTip("Import data from a portable StarPost CSV file")
        import_btn.clicked.connect(self.import_requested)
        export = QPushButton("Export Data")
        export.setToolTip("Export loaded data sets to portable StarPost CSV files")
        export.clicked.connect(self.export_requested)
        delete = QPushButton("Delete")
        delete.setToolTip("Delete the selected data sets")
        delete.clicked.connect(self.delete_requested)
        clear = QPushButton("Clear Data")
        clear.setObjectName("clearDataButton")
        clear.setToolTip("Remove all loaded data")
        clear.clicked.connect(self.clear_requested)
        buttons = QHBoxLayout()
        for b in (import_btn, export, delete, clear):
            buttons.addWidget(b)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._tree)
        layout.addLayout(buttons)

        self._load()

    # --- public API ------------------------------------------------------
    def set_entries(self, names: list[str]) -> None:
        """Reconcile the tree against the live set of data set ``names``: add new
        ones (at the top level, or in their remembered folder on first load),
        drop ones no longer present, and leave the rest in place — preserving each
        kept set's folder and check state."""
        wanted = list(names)
        wanted_set = set(wanted)
        present = {it.data(0, _NAME_ROLE): it for it in self._iter_data()}

        changed = False
        self._tree.blockSignals(True)
        # Remove data sets that are gone.
        for name, item in present.items():
            if name not in wanted_set:
                (item.parent() or self._tree.invisibleRootItem()).removeChild(item)
                changed = True
        # Add data sets that are new, restoring a remembered folder if one exists.
        for name in wanted:
            if name in present:
                continue
            item = self._make_data_item(name)
            target = self._find_folder(self._folder_for.get(name))
            if target is not None:
                target.addChild(item)
            else:
                self._tree.addTopLevelItem(item)
            changed = True
        self._tree.blockSignals(False)

        if changed:
            self._apply_sort()
            self._save()

    def checked_names(self) -> list[str]:
        return [
            it.data(0, _NAME_ROLE)
            for it in self._iter_data()
            if it.checkState(0) == Qt.CheckState.Checked
        ]

    def show_sort_menu(self, global_pos) -> None:
        """Tab-wide sort (the Data tab is right-clicked); orders each folder's
        contents, folders before data sets. The active mode shows a checkmark."""
        menu = QMenu(self)
        actions = {}
        for text, key in (("Name (A–Z)", "name_az"), ("Name (Z–A)", "name_za")):
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(key == self._sort_mode)
            actions[act] = key
        chosen = menu.exec(global_pos)
        if chosen is not None:
            self._sort_mode = actions[chosen]
            self._apply_sort()
            self._save()

    def set_folder_color(self, color: str) -> None:
        """Tint every folder icon to ``color`` ("" restores the default), to match
        the Appearance setting and the Files tab."""
        color = color or ""
        if color == self._folder_color:
            return
        self._folder_color = color
        self._folder_icon = self._build_folder_icon()
        for item in self._tree._iter_all():
            if _is_folder(item):
                item.setIcon(0, self._folder_icon)

    # --- item factories --------------------------------------------------
    def _make_data_item(self, name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name])
        item.setData(0, _NAME_ROLE, name)
        item.setData(0, _TYPE_ROLE, "data")
        item.setFlags(_DATA_FLAGS)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        return item

    def _make_folder_item(
        self, name: str, sort_mode: str = DEFAULT_SORT
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name])
        item.setData(0, _TYPE_ROLE, "folder")
        item.setData(0, _SORT_ROLE, sort_mode)
        item.setIcon(0, self._folder_icon)
        item.setFlags(_FOLDER_FLAGS)
        return item

    @staticmethod
    def _folder_sort_mode(item: QTreeWidgetItem) -> str:
        return item.data(0, _SORT_ROLE) or DEFAULT_SORT

    def _build_folder_icon(self):
        if not self._folder_color:
            return self._base_folder_icon
        return _tinted_icon(self._base_folder_icon, self._folder_color)

    # --- iteration -------------------------------------------------------
    def _iter_data(self, parent: QTreeWidgetItem | None = None):
        """Yield every data set item, depth-first, across the whole tree."""
        count = (
            self._tree.topLevelItemCount()
            if parent is None
            else parent.childCount()
        )
        for i in range(count):
            item = self._tree.topLevelItem(i) if parent is None else parent.child(i)
            if _is_folder(item):
                yield from self._iter_data(item)
            else:
                yield item

    def _find_folder(self, name: str | None) -> QTreeWidgetItem | None:
        if not name:
            return None
        for item in self._tree._iter_all():
            if _is_folder(item) and item.text(0) == name:
                return item
        return None

    # --- sorting ---------------------------------------------------------
    def _sorted_level(self, nodes: list[dict], mode: str) -> list[dict]:
        """Order one level: folders first (always A–Z), then data sets by the
        chosen name direction. Does not recurse."""
        folders = sorted(
            (n for n in nodes if "folder" in n), key=lambda n: n["folder"].lower()
        )
        data = [n for n in nodes if "data" in n]
        data.sort(key=lambda n: n["data"].lower(), reverse=mode == "name_za")
        return list(folders) + data

    def _sort_nodes(self, nodes: list[dict], mode: str) -> list[dict]:
        ordered = self._sorted_level(nodes, mode)
        for n in ordered:
            if "folder" in n:
                n["items"] = self._sort_nodes(n.get("items", []), mode)
        return ordered

    def _apply_sort(self) -> None:
        self._rebuild(self._sort_nodes(self._serialize(), self._sort_mode))

    def _sort_folder(self, folder: QTreeWidgetItem, mode: str) -> None:
        """Sort just ``folder``'s immediate contents (folders first, then data
        sets), remembering the mode so its menu shows the active choice."""
        folder.setData(0, _SORT_ROLE, mode)
        nodes = self._sorted_level(
            [self._node(folder.child(i)) for i in range(folder.childCount())], mode
        )
        states = self._tree._capture_checks()
        folder.takeChildren()
        for node in nodes:
            folder.addChild(self._build_item(node))
        # Block signals so restoring each subfolder's expansion doesn't fire a
        # save per subfolder; the single _save() below persists the result.
        self._tree.blockSignals(True)
        for node, i in zip(nodes, range(folder.childCount())):
            self._restore_expansion(node, folder.child(i))
        self._tree.blockSignals(False)
        self._tree._restore_checks(states)
        self._save()

    # --- (de)serialisation -----------------------------------------------
    def _serialize(self) -> list[dict]:
        return [
            self._node(self._tree.topLevelItem(i))
            for i in range(self._tree.topLevelItemCount())
        ]

    def _node(self, item: QTreeWidgetItem) -> dict:
        if _is_folder(item):
            return {
                "folder": item.text(0),
                "expanded": item.isExpanded(),
                "sort": self._folder_sort_mode(item),
                "items": [self._node(item.child(i)) for i in range(item.childCount())],
            }
        return {"data": item.data(0, _NAME_ROLE)}

    def _build_item(self, node: dict) -> QTreeWidgetItem:
        if "folder" in node:
            item = self._make_folder_item(node["folder"], node.get("sort", DEFAULT_SORT))
            for child in node.get("items", []):
                item.addChild(self._build_item(child))
            return item
        return self._make_data_item(node["data"])

    def _rebuild(self, nodes: list[dict]) -> None:
        """Replace the whole tree from a serialised structure, preserving check
        state (by name) and folder expansion."""
        states = self._tree._capture_checks()
        self._tree.blockSignals(True)
        self._tree.clear()
        items = [self._build_item(n) for n in nodes]
        for item in items:
            self._tree.addTopLevelItem(item)
        for node, item in zip(nodes, items):
            self._restore_expansion(node, item)
        self._tree._restore_checks(states)
        self._tree.blockSignals(False)

    def _restore_expansion(self, node: dict, item: QTreeWidgetItem) -> None:
        if "folder" not in node:
            return
        item.setExpanded(node.get("expanded", True))
        for child_node, i in zip(node.get("items", []), range(item.childCount())):
            self._restore_expansion(child_node, item.child(i))

    # --- folder operations -----------------------------------------------
    def _new_folder(self, parent_item: QTreeWidgetItem | None) -> None:
        name, ok = QInputDialog.getText(
            self, "New Folder", "Folder name:", text="New Folder"
        )
        if not ok or not name.strip():
            return
        item = self._make_folder_item(name.strip())
        if parent_item is None:
            self._tree.addTopLevelItem(item)
        else:
            parent_item.addChild(item)
            parent_item.setExpanded(True)
        self._save()

    def _rename_folder(self, item: QTreeWidgetItem) -> None:
        name, ok = QInputDialog.getText(
            self, "Rename Folder", "Folder name:", text=item.text(0)
        )
        if ok and name.strip():
            item.setText(0, name.strip())
            self._save()

    def _delete_folder(self, item: QTreeWidgetItem) -> None:
        """Delete a folder, moving its contents up to the parent. A folder
        holding data sets asks first. (Data itself is never deleted here — use
        the Delete button for that.)"""
        parent = item.parent()
        if list(self._iter_data(item)):
            where = "the main data list" if parent is None else f"“{parent.text(0)}”"
            if QMessageBox.warning(
                self, "Delete folder",
                f"“{item.text(0)}” will be deleted.\n\n"
                f"Its contents will be moved up to {where}.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
        states = self._tree._capture_checks()
        for child in [item.child(i) for i in range(item.childCount())]:
            item.removeChild(child)
            if parent is None:
                self._tree.addTopLevelItem(child)
            else:
                parent.addChild(child)
        if parent is None:
            self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(item))
        else:
            parent.removeChild(item)
        self._tree._restore_checks(states)
        self._save()

    def _set_folder_checked(self, item: QTreeWidgetItem, checked: bool) -> None:
        """Check or uncheck every data set inside a folder (recursively)."""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._tree.blockSignals(True)
        for data_item in self._iter_data(item):
            data_item.setCheckState(0, state)
        self._tree.blockSignals(False)
        self.selection_changed.emit()

    def _folder_properties(self, item: QTreeWidgetItem) -> None:
        names = [d.data(0, _NAME_ROLE) for d in self._iter_data(item)]
        self.folder_properties_requested.emit(item.text(0), names)

    # --- context menu ----------------------------------------------------
    def _show_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        global_pos = self._tree.viewport().mapToGlobal(pos)

        if item is None:
            new_act = menu.addAction("New Folder")
            if menu.exec(global_pos) is new_act:
                self._new_folder(None)
            return

        if _is_folder(item):
            check_act = menu.addAction("Check all")
            uncheck_act = menu.addAction("Uncheck all")
            new_act = menu.addAction("New Nested Folder")
            sort_menu = menu.addMenu("Sort")
            current_sort = self._folder_sort_mode(item)
            sort_actions = {}
            for label, mode in (("A–Z", "name_az"), ("Z–A", "name_za")):
                act = sort_menu.addAction(label)
                act.setCheckable(True)
                act.setChecked(mode == current_sort)
                sort_actions[act] = mode
            menu.addSeparator()
            rename_act = menu.addAction("Rename")
            delete_act = menu.addAction("Delete folder")
            menu.addSeparator()
            props_act = menu.addAction("Properties")
            chosen = menu.exec(global_pos)
            if chosen is check_act:
                self._set_folder_checked(item, True)
            elif chosen is uncheck_act:
                self._set_folder_checked(item, False)
            elif chosen is new_act:
                self._new_folder(item)
            elif chosen in sort_actions:
                self._sort_folder(item, sort_actions[chosen])
            elif chosen is rename_act:
                self._rename_folder(item)
            elif chosen is delete_act:
                self._delete_folder(item)
            elif chosen is props_act:
                self._folder_properties(item)
            return

        # A data set: Properties on the right-clicked one.
        props_act = menu.addAction("Properties")
        if menu.exec(global_pos) is props_act:
            self.properties_requested.emit(item.data(0, _NAME_ROLE))

    # --- slots -----------------------------------------------------------
    def _on_item_changed(self, _item, _column) -> None:
        # A checkbox toggled (check state isn't persisted, so no save needed).
        self.selection_changed.emit()

    def _on_expansion_changed(self, _item) -> None:
        """A folder was expanded/collapsed by the user; persist the layout so the
        open/closed state survives a restart."""
        self._save()

    def _on_dropped(self) -> None:
        """After a drag-drop re-parent: restore type-correct flags (a move can
        reset them) and persist the new layout."""
        self._tree.blockSignals(True)
        for item in self._tree._iter_all():
            item.setFlags(_FOLDER_FLAGS if _is_folder(item) else _DATA_FLAGS)
        self._tree.blockSignals(False)
        self._save()

    # --- persistence -----------------------------------------------------
    def _save(self) -> None:
        # Remember each data set's folder so a set re-added later returns to it.
        self._folder_for = {
            it.data(0, _NAME_ROLE): (it.parent().text(0) if it.parent() else None)
            for it in self._iter_data()
        }
        payload = {"version": CACHE_VERSION, "items": self._serialize()}
        try:
            data_list_cache_path().write_text(json.dumps(payload))
        except OSError:
            pass

    def _load(self) -> None:
        """Restore the saved folder layout on startup (without re-saving). The
        data set rows are placeholders until set_entries reconciles them against
        what's actually loaded."""
        self._folder_for: dict[str, str | None] = {}
        path = data_list_cache_path()
        if not path.exists():
            return
        try:
            saved = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        nodes = saved.get("items", []) if isinstance(saved, dict) else []
        self._rebuild(nodes)
        self._folder_for = {
            it.data(0, _NAME_ROLE): (it.parent().text(0) if it.parent() else None)
            for it in self._iter_data()
        }
