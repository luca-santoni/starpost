"""Left panel: the batch list of .sim files (add files/folder, remove, clear).

Files can be organised into virtual folders that exist only here (never on
disk): right-click empty space for "New Folder", drag files/folders to
re-parent them, and nest folders to any depth. A folder lists its contents as
an expandable dropdown; the flat set of files (for running a batch) is still
available via :meth:`files`.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from starpost.utils.paths import file_list_cache_path

MAX_FILES = 25  # v1 expected ceiling; warn beyond this

# Item data roles and the type tag they carry.
_PATH_ROLE = int(Qt.ItemDataRole.UserRole)      # a file item's full path (str)
_TYPE_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # "file" or "folder"

# Files can be dragged but not dropped onto (so they never gain children);
# folders accept drops so files/folders can be moved inside them.
_FILE_FLAGS = (
    Qt.ItemFlag.ItemIsEnabled
    | Qt.ItemFlag.ItemIsSelectable
    | Qt.ItemFlag.ItemIsDragEnabled
)
_FOLDER_FLAGS = _FILE_FLAGS | Qt.ItemFlag.ItemIsDropEnabled

CACHE_VERSION = 2  # nested-folder cache layout (v1 was a flat list of paths)


def _is_folder(item: QTreeWidgetItem) -> bool:
    return item.data(0, _TYPE_ROLE) == "folder"


class _FileTree(QTreeWidget):
    """A tree whose drag-drop re-parents items, refusing only the one move Qt
    would otherwise allow into corruption: a folder into its own subtree."""

    dropped = Signal()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        target = self._drop_parent(event)
        for item in self.selectedItems():
            if _is_folder(item) and self._is_self_or_descendant(item, target):
                event.ignore()
                return
        super().dropEvent(event)
        self.dropped.emit()

    def _drop_parent(self, event) -> QTreeWidgetItem | None:
        """The folder a drop would land in (None = top level), from the drop
        indicator: onto a folder nests into it; onto a file, or between rows,
        targets that row's parent."""
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


class FileListPanel(QWidget):
    files_changed = Signal(list)  # list[Path]
    open_requested = Signal(list)  # list[Path] to extract & view (in order)
    properties_requested = Signal(object)  # a single Path to show properties for

    def __init__(self, parent=None, *, show_full_names: bool = False) -> None:
        super().__init__(parent)
        # Each file item stores its full path; the displayed text is either that
        # path or just the file name, per this flag.
        self._show_full_names = show_full_names
        # Active sort, kept in sync with the header menu's checkmark.
        self._sort_mode = "name_az"
        self._folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)

        self._tree = _FileTree()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        # Internal drag-drop re-parents items; persist the new layout afterwards.
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._tree.setDragEnabled(True)
        self._tree.setAcceptDrops(True)
        self._tree.dropped.connect(self._on_dropped)

        add_files = QPushButton("Add files…")
        add_folder = QPushButton("Add folder…")
        remove = QPushButton("Remove")
        clear = QPushButton("Clear")
        clear.setObjectName("dangerButton")
        add_files.clicked.connect(self._add_files)
        add_folder.clicked.connect(self._add_folder)
        remove.clicked.connect(self._remove_selected)
        clear.clicked.connect(self._clear_confirmed)

        buttons = QHBoxLayout()
        for b in (add_files, add_folder, remove, clear):
            buttons.addWidget(b)

        layout = QVBoxLayout(self)
        layout.addWidget(self._tree)
        layout.addLayout(buttons)

        self._load()

    # --- data ------------------------------------------------------------
    def files(self) -> list[Path]:
        """Every .sim in the panel, flattened across all folders (run order)."""
        out: list[Path] = []
        for item in self._iter_files():
            out.append(Path(item.data(0, _PATH_ROLE)))
        return out

    def _iter_files(self, parent: QTreeWidgetItem | None = None):
        """Yield every file item, depth-first, across the whole tree."""
        count = (
            self._tree.topLevelItemCount()
            if parent is None
            else parent.childCount()
        )
        for i in range(count):
            item = (
                self._tree.topLevelItem(i) if parent is None else parent.child(i)
            )
            if _is_folder(item):
                yield from self._iter_files(item)
            else:
                yield item

    def set_show_full_names(self, show_full_names: bool) -> None:
        """Switch file labels between full paths and names only (folder names and
        the stored paths are unaffected)."""
        if show_full_names == self._show_full_names:
            return
        self._show_full_names = show_full_names
        for item in self._iter_files():
            item.setText(0, self._label(Path(item.data(0, _PATH_ROLE))))

    def _label(self, path: Path) -> str:
        return str(path) if self._show_full_names else path.name

    def _make_file_item(self, path: Path) -> QTreeWidgetItem:
        item = QTreeWidgetItem([self._label(path)])
        item.setData(0, _PATH_ROLE, str(path))
        item.setData(0, _TYPE_ROLE, "file")
        item.setToolTip(0, str(path))
        item.setFlags(_FILE_FLAGS)
        return item

    def _make_folder_item(self, name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name])
        item.setData(0, _TYPE_ROLE, "folder")
        item.setIcon(0, self._folder_icon)
        item.setFlags(_FOLDER_FLAGS)
        return item

    def _add_paths(self, paths: list[Path]) -> None:
        """Add new .sim files at the top level, skipping any already present
        anywhere in the tree."""
        existing = {p.resolve() for p in self.files()}
        added = False
        for p in paths:
            if p.suffix == ".sim" and p.resolve() not in existing:
                self._tree.addTopLevelItem(self._make_file_item(p))
                existing.add(p.resolve())
                added = True
        if added:
            self._apply_sort()
            self._changed()

    # --- sorting ---------------------------------------------------------
    def show_sort_menu(self, global_pos) -> None:
        """Show the sort options at a global position (the Files tab is
        right-clicked). The active mode shows a checkmark. Sorting orders each
        folder's contents, folders before files."""
        menu = QMenu(self)
        options = [
            ("Name (A–Z)", "name_az"),
            ("Name (Z–A)", "name_za"),
            ("File size (largest)", "size_large"),
            ("File size (smallest)", "size_small"),
        ]
        actions = {}
        for text, key in options:
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(key == self._sort_mode)
            actions[act] = key
        chosen = menu.exec(global_pos)
        if chosen is not None:
            self._sort_mode = actions[chosen]
            self._apply_sort()
            self._changed()

    @staticmethod
    def _size(path: Path) -> int:
        # Missing files sort as smallest so a broken path doesn't raise.
        try:
            return path.stat().st_size
        except OSError:
            return -1

    def _sort_nodes(self, nodes: list[dict]) -> list[dict]:
        """Sort one container's nodes by the active mode: folders first (always
        by name), then files by the chosen key. Recurses into folders."""
        folders = [n for n in nodes if "folder" in n]
        files = [n for n in nodes if "file" in n]
        reverse = self._sort_mode == "name_za"
        folders.sort(key=lambda n: n["folder"].lower())
        if self._sort_mode in ("name_az", "name_za"):
            files.sort(key=lambda n: Path(n["file"]).name.lower(), reverse=reverse)
        elif self._sort_mode == "size_large":
            files.sort(key=lambda n: self._size(Path(n["file"])), reverse=True)
        elif self._sort_mode == "size_small":
            files.sort(key=lambda n: self._size(Path(n["file"])))
        for n in folders:
            n["items"] = self._sort_nodes(n.get("items", []))
        return folders + files

    def _apply_sort(self) -> None:
        self._rebuild(self._sort_nodes(self._serialize()))

    # --- (de)serialisation of the tree -----------------------------------
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
                "items": [self._node(item.child(i)) for i in range(item.childCount())],
            }
        return {"file": item.data(0, _PATH_ROLE)}

    def _build_item(self, node: dict) -> QTreeWidgetItem:
        if "folder" in node:
            item = self._make_folder_item(node["folder"])
            for child in node.get("items", []):
                item.addChild(self._build_item(child))
            return item
        return self._make_file_item(Path(node["file"]))

    def _rebuild(self, nodes: list[dict]) -> None:
        """Replace the whole tree from a serialised structure, restoring folder
        expansion state."""
        self._tree.clear()
        items = [self._build_item(n) for n in nodes]
        for item in items:
            self._tree.addTopLevelItem(item)
        for node, item in zip(nodes, items):
            self._restore_expansion(node, item)

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
        self._changed()

    def _rename_folder(self, item: QTreeWidgetItem) -> None:
        name, ok = QInputDialog.getText(
            self, "Rename Folder", "Folder name:", text=item.text(0)
        )
        if ok and name.strip():
            item.setText(0, name.strip())
            self._changed()

    def _delete_folder(self, item: QTreeWidgetItem) -> None:
        """Remove a folder, moving its contents up to its parent so no files are
        lost."""
        parent = item.parent()
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
        self._changed()

    def _open_folder(self, item: QTreeWidgetItem) -> None:
        """Open (extract & view) every .sim in the folder, recursively."""
        paths = [Path(f.data(0, _PATH_ROLE)) for f in self._iter_files(item)]
        if paths:
            self.open_requested.emit(paths)

    # --- slots -----------------------------------------------------------
    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add .sim files", "", "STAR-CCM+ sim (*.sim)"
        )
        self._add_paths([Path(p) for p in paths])

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder of .sim files")
        if folder:
            self._add_paths(sorted(Path(folder).glob("*.sim")))

    def _remove_selected(self) -> None:
        """Remove the selected items. A selected folder takes its contents with
        it (use the folder's "Delete folder" to keep the files)."""
        items = self._topmost(self._tree.selectedItems())
        if not items:
            return
        target = (
            f"“{items[0].text(0)}”" if len(items) == 1 else f"{len(items)} items"
        )
        if QMessageBox.question(
            self, "Remove",
            f"Remove {target} from the list?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        for item in items:
            parent = item.parent()
            if parent is None:
                self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(item))
            else:
                parent.removeChild(item)
        self._changed()

    @staticmethod
    def _topmost(items: list[QTreeWidgetItem]) -> list[QTreeWidgetItem]:
        """Drop any item whose ancestor is also selected, so removing a folder
        doesn't also try to remove its (already-gone) children."""
        chosen = set(items)
        out = []
        for item in items:
            ancestor = item.parent()
            while ancestor is not None and ancestor not in chosen:
                ancestor = ancestor.parent()
            if ancestor is None:
                out.append(item)
        return out

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        """Double-clicking a file opens just it; folders fall through to the
        default expand/collapse."""
        if not _is_folder(item):
            self.open_requested.emit([Path(item.data(0, _PATH_ROLE))])

    def _on_dropped(self) -> None:
        """After a drag-drop re-parent: restore type-correct flags (a move can
        reset them) and persist the new layout."""
        for item in self._iter_all():
            item.setFlags(_FOLDER_FLAGS if _is_folder(item) else _FILE_FLAGS)
        self._changed()

    def _iter_all(self, parent: QTreeWidgetItem | None = None):
        """Yield every item (files and folders), depth-first."""
        count = (
            self._tree.topLevelItemCount()
            if parent is None
            else parent.childCount()
        )
        for i in range(count):
            item = (
                self._tree.topLevelItem(i) if parent is None else parent.child(i)
            )
            yield item
            if _is_folder(item):
                yield from self._iter_all(item)

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
            open_act = menu.addAction("Open All")
            new_act = menu.addAction("New Nested Folder")
            menu.addSeparator()
            rename_act = menu.addAction("Rename")
            delete_act = menu.addAction("Delete folder")
            chosen = menu.exec(global_pos)
            if chosen is open_act:
                self._open_folder(item)
            elif chosen is new_act:
                self._new_folder(item)
            elif chosen is rename_act:
                self._rename_folder(item)
            elif chosen is delete_act:
                self._delete_folder(item)
            return

        # A file: Open acts on every selected file (top-to-bottom); Properties
        # on just the right-clicked one.
        open_act = menu.addAction("Open")
        props_act = menu.addAction("Properties")
        chosen = menu.exec(global_pos)
        if chosen is open_act:
            paths = [Path(f.data(0, _PATH_ROLE)) for f in self._iter_files()
                     if f.isSelected()] or [Path(item.data(0, _PATH_ROLE))]
            self.open_requested.emit(paths)
        elif chosen is props_act:
            self.properties_requested.emit(item.data(0, _PATH_ROLE))

    def _clear_confirmed(self) -> None:
        """Clear the panel (files and folders) only after the user confirms."""
        if self._tree.topLevelItemCount() == 0:
            return
        if QMessageBox.warning(
            self, "Clear files",
            "This will remove all files and folders from the list. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes:
            self._tree.clear()
            self._changed()

    # --- persistence -----------------------------------------------------
    def _changed(self) -> None:
        """Notify listeners of the current files and persist the full layout."""
        self.files_changed.emit(self.files())
        self._save()

    def _save(self) -> None:
        path = file_list_cache_path()
        payload = {"version": CACHE_VERSION, "items": self._serialize()}
        path.write_text(json.dumps(payload, indent=2))

    def _load(self) -> None:
        """Restore the saved layout on startup (without re-saving). Accepts both
        the nested format and the old flat list of paths."""
        path = file_list_cache_path()
        if not path.exists():
            return
        try:
            saved = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(saved, list):  # legacy flat format: bare list of paths
            nodes = [{"file": p} for p in saved]
        else:
            nodes = saved.get("items", [])
        self._rebuild(nodes)
