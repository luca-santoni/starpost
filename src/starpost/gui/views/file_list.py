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

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from starpost.gui import shortcuts
from starpost.gui.theme import DEFAULT_ACCENT, contrast_color

from starpost.gui.widgets import (
    DangerMenuItem,
    clear_item_view_hover,
    enable_range_selection,
)
from starpost.utils.paths import file_list_cache_path

MAX_FILES = 25  # v1 expected ceiling; warn beyond this

# Item data roles and the type tag they carry.
_PATH_ROLE = int(Qt.ItemDataRole.UserRole)      # a file item's full path (str)
_TYPE_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # "file" or "folder"
_SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 2  # a folder's chosen sort mode

DEFAULT_SORT = "name_az"  # A–Z, used by the tab sort and each new folder

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


def _tinted_icon(base: QIcon, color: str, size: int = 32) -> QIcon:
    """Recolour ``base``'s silhouette to ``color`` (keeping its alpha), e.g. to
    tint the standard folder icon to the user's chosen folder colour."""
    pixmap = base.pixmap(QSize(size, size))
    tinted = QPixmap(pixmap.size())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()
    return QIcon(tinted)


# Leaf items (.sim files, data sets) get a small round "node" icon, mirroring
# STAR-CCM+'s tree, where leaves carry a blue node dot rather than a dash.
_LEAF_COLOR = "#4a90d9"


def _dot_pixmap(color: str, size: int) -> QPixmap:
    """A small filled circle of ``color`` on a transparent square."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    margin = round(size * 0.3)  # a compact dot, ~40% of the icon box
    painter.drawEllipse(pixmap.rect().adjusted(margin, margin, -margin, -margin))
    painter.end()
    return pixmap


def _dot_icon(color: str, selected_color: str | None = None, size: int = 32) -> QIcon:
    """A small filled circle icon for a tree's leaf items, like STAR-CCM+'s node
    icons. When ``selected_color`` is given, the icon also carries a Selected-mode
    pixmap in that colour, so a selected row shows a contrasting dot instead of
    one that blends into the accent highlight (Qt's default selected tint leaves a
    same-hue dot barely visible)."""
    icon = QIcon(_dot_pixmap(color, size))
    if selected_color:
        icon.addPixmap(_dot_pixmap(selected_color, size), QIcon.Mode.Selected)
    return icon


# Colour of the tree connector lines that link nested items to their parent.
_LINE_COLOR = "#6f6f6f"


def _has_following_sibling(tree: QTreeWidget, item: QTreeWidgetItem) -> bool:
    """Whether ``item`` has another sibling below it (so its branch continues)."""
    parent = item.parent()
    if parent is None:
        i = tree.indexOfTopLevelItem(item)
        return 0 <= i < tree.topLevelItemCount() - 1
    i = parent.indexOfChild(item)
    return 0 <= i < parent.childCount() - 1


def _draw_tree_lines(tree: QTreeWidget, painter, rect, index) -> None:
    """Draw STAR-CCM+-style connector lines in a row's branch area: a hook from
    each item to its parent's vertical line, with the vertical continued through
    ancestor columns whose branch hasn't ended. Call after the base
    ``drawBranches`` so it overlays the expand arrows."""
    item = tree.itemFromIndex(index)
    indent = tree.indentation()
    if item is None or item.parent() is None or indent <= 0:
        return  # top-level rows get no hook (there's no parent to link to)
    painter.save()
    pen = QPen(QColor(_LINE_COLOR))
    pen.setStyle(Qt.PenStyle.SolidLine)
    painter.setPen(pen)
    top, bottom, cy = rect.top(), rect.bottom(), rect.center().y()
    # The hook sits in the indent slot one level left of the item's content —
    # i.e. under the parent's expand arrow.
    x = rect.right() - indent + indent // 2
    painter.drawLine(x, top, x, cy)                 # up to the parent/prev sibling
    if _has_following_sibling(tree, item):
        painter.drawLine(x, cy, x, bottom)          # down to the next sibling
    painter.drawLine(x, cy, rect.right(), cy)       # across to the item
    # Ancestor columns still carrying a vertical line (they have siblings below).
    ax, anc = x - indent, item.parent()
    while anc is not None:
        if _has_following_sibling(tree, anc):
            painter.drawLine(ax, top, ax, bottom)
        anc, ax = anc.parent(), ax - indent
    painter.restore()


class _FileTree(QTreeWidget):
    """A tree whose drag-drop re-parents items, refusing only the one move Qt
    would otherwise allow into corruption: a folder into its own subtree."""

    dropped = Signal()

    def drawBranches(self, painter, rect, index) -> None:  # noqa: N802 (Qt override)
        super().drawBranches(painter, rect, index)
        _draw_tree_lines(self, painter, rect, index)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        target = self._drop_parent(event)
        for item in self.selectedItems():
            if _is_folder(item) and self._is_self_or_descendant(item, target):
                event.ignore()
                return
        super().dropEvent(event)
        self.dropped.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().mousePressEvent(event)
        # A click in empty space clears the selection and current row: the view
        # otherwise leaves the last-clicked item selected, so its highlight
        # lingers (fading only while the window is inactive) until another item
        # is clicked.
        if self.itemAt(event.position().toPoint()) is None:
            self.clearSelection()
            self.setCurrentItem(None)

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

    def __init__(
        self,
        parent=None,
        *,
        show_full_names: bool = False,
        folder_color: str = "",
        node_color: str = "",
        accent: str = DEFAULT_ACCENT,
    ) -> None:
        super().__init__(parent)
        # Each file item stores its full path; the displayed text is either that
        # path or just the file name, per this flag.
        self._show_full_names = show_full_names
        # Active tab-wide sort, kept in sync with the header menu's checkmark.
        self._sort_mode = DEFAULT_SORT
        # Folder icon: the standard one, optionally tinted to a chosen colour
        # ("" = leave the default icon as-is).
        self._base_folder_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_DirIcon
        )
        self._folder_color = folder_color or ""
        self._folder_icon = self._build_folder_icon()
        # Leaf node dot: coloured to a chosen colour ("" = the STAR-CCM+ blue),
        # with a contrasting variant (the accent's contrast colour) for the
        # selected row so the dot stays visible on the accent highlight.
        self._node_color = node_color or _LEAF_COLOR
        self._accent = accent or DEFAULT_ACCENT
        self._file_icon = _dot_icon(self._node_color, contrast_color(self._accent))

        self._tree = _FileTree()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        enable_range_selection(self._tree)  # Shift/Ctrl+click multi-select
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu_at)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        # Internal drag-drop re-parents items; persist the new layout afterwards.
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._tree.setDragEnabled(True)
        self._tree.setAcceptDrops(True)
        self._tree.dropped.connect(self._on_dropped)
        # Persist a folder's open/closed state when the user expands or collapses
        # it (programmatic changes during load/rebuild are guarded by blocking
        # the tree's signals, so they don't trigger a save).
        self._tree.itemExpanded.connect(self._on_expansion_changed)
        self._tree.itemCollapsed.connect(self._on_expansion_changed)

        # Keyboard shortcuts, active only while the file tree has focus. The
        # context menu displays the same keys, but its actions are rebuilt on
        # every popup — these persistent bindings do the real work.
        for shortcut_id, slot in (
            ("file_load", self._load_selected),
            ("file_props", self._properties_current),
            ("file_remove", self._remove_selected),
        ):
            sc = QShortcut(QKeySequence(shortcuts.key(shortcut_id)), self._tree)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

        # No button row: adding lives in the File menu (Add ▸ Files…/Folder…),
        # removal in the item context menu / Delete key, and Clear in the tab's
        # right-click menu.
        layout = QVBoxLayout(self)
        layout.addWidget(self._tree)

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
        item.setIcon(0, self._file_icon)
        item.setFlags(_FILE_FLAGS)
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

    def _build_folder_icon(self) -> QIcon:
        """The folder icon for the active colour ("" keeps the default icon)."""
        if not self._folder_color:
            return self._base_folder_icon
        return _tinted_icon(self._base_folder_icon, self._folder_color)

    def set_folder_color(self, color: str) -> None:
        """Tint every folder icon to ``color``; an empty string restores the
        default folder icon. Mirrors the Appearance setting."""
        color = color or ""
        if color == self._folder_color:
            return
        self._folder_color = color
        self._folder_icon = self._build_folder_icon()
        for item in self._iter_all():
            if _is_folder(item):
                item.setIcon(0, self._folder_icon)

    def set_node_color(self, color: str) -> None:
        """Recolour every leaf node dot to ``color``; an empty string restores
        the default STAR-CCM+ blue. Mirrors the Appearance setting."""
        color = color or _LEAF_COLOR
        if color == self._node_color:
            return
        self._node_color = color
        self._rebuild_file_icon()

    def set_accent(self, accent: str) -> None:
        """Update the accent so the selected-row dot keeps a contrasting colour."""
        accent = accent or DEFAULT_ACCENT
        if accent == self._accent:
            return
        self._accent = accent
        self._rebuild_file_icon()

    def _rebuild_file_icon(self) -> None:
        """Rebuild the leaf dot icon (normal + selected variants) and re-apply it
        to every file item."""
        self._file_icon = _dot_icon(self._node_color, contrast_color(self._accent))
        for item in self._iter_all():
            if not _is_folder(item):
                item.setIcon(0, self._file_icon)

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
        """Show the tab context menu (sort options + Clear) at a global
        position (the Files tab is right-clicked). The active sort mode shows
        a checkmark. Sorting orders each folder's contents, folders before
        files."""
        menu, actions, _clear_act = self._build_sort_menu()
        self._on_sort_menu_chosen(menu.exec(global_pos), actions)

    def _build_sort_menu(self):
        """The Files tab context menu: the four sort modes, then a destructive
        Clear entry below a separator — the same confirm-and-clear as the
        panel's Clear button. Returns ``(menu, {action: sort_mode}, clear_act)``;
        Clear handles itself through its signals (click closes the menu, and a
        keyboard Enter triggers the action), so the exec dispatch skips it."""
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
        menu.addSeparator()
        label = DangerMenuItem("Clear")
        clear_act = QWidgetAction(menu)
        clear_act.setDefaultWidget(label)
        menu.addAction(clear_act)
        # Close first, confirm second: the confirmation box must not sit under
        # a still-open menu holding the mouse grab.
        label.clicked.connect(menu.close)
        label.clicked.connect(self._clear_confirmed)
        clear_act.triggered.connect(self._clear_confirmed)
        return menu, actions, clear_act

    def _on_sort_menu_chosen(self, chosen, actions) -> None:
        """Apply the picked sort mode; Clear (or a dismissed menu) is not a
        sort choice and does nothing here."""
        if chosen in actions:
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

    def _sorted_level(self, nodes: list[dict], mode: str) -> list[dict]:
        """Order one level of nodes by ``mode``: folders first (always by name),
        then files by the chosen key. Does not recurse."""
        folders = sorted(
            (n for n in nodes if "folder" in n), key=lambda n: n["folder"].lower()
        )
        files = [n for n in nodes if "file" in n]
        if mode in ("name_az", "name_za"):
            files.sort(
                key=lambda n: Path(n["file"]).name.lower(), reverse=mode == "name_za"
            )
        elif mode == "size_large":
            files.sort(key=lambda n: self._size(Path(n["file"])), reverse=True)
        elif mode == "size_small":
            files.sort(key=lambda n: self._size(Path(n["file"])))
        return list(folders) + files

    def _sort_nodes(self, nodes: list[dict], mode: str) -> list[dict]:
        """Sort a container's nodes by ``mode``, recursing into every folder."""
        ordered = self._sorted_level(nodes, mode)
        for n in ordered:
            if "folder" in n:
                n["items"] = self._sort_nodes(n.get("items", []), mode)
        return ordered

    def _apply_sort(self) -> None:
        self._rebuild(self._sort_nodes(self._serialize(), self._sort_mode))

    def _sort_folder(self, folder: QTreeWidgetItem, mode: str) -> None:
        """Sort just ``folder``'s immediate contents by ``mode`` (folders first,
        then files), leaving everything else — including each subfolder's own
        internal order — untouched. The mode is remembered on the folder so its
        menu shows the active choice."""
        folder.setData(0, _SORT_ROLE, mode)
        nodes = self._sorted_level(
            [self._node(folder.child(i)) for i in range(folder.childCount())], mode
        )
        folder.takeChildren()
        for node in nodes:
            folder.addChild(self._build_item(node))
        # Block signals so restoring each subfolder's expansion doesn't fire a
        # save per subfolder; the single _changed() below persists the result.
        self._tree.blockSignals(True)
        for node, i in zip(nodes, range(folder.childCount())):
            self._restore_expansion(node, folder.child(i))
        self._tree.blockSignals(False)
        self._changed()

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
                "sort": self._folder_sort_mode(item),
                "items": [self._node(item.child(i)) for i in range(item.childCount())],
            }
        return {"file": item.data(0, _PATH_ROLE)}

    def _build_item(self, node: dict) -> QTreeWidgetItem:
        if "folder" in node:
            item = self._make_folder_item(
                node["folder"], node.get("sort", DEFAULT_SORT)
            )
            for child in node.get("items", []):
                item.addChild(self._build_item(child))
            return item
        return self._make_file_item(Path(node["file"]))

    def _rebuild(self, nodes: list[dict]) -> None:
        """Replace the whole tree from a serialised structure, restoring folder
        expansion state."""
        # Block signals so the programmatic setExpanded calls below don't fire
        # itemExpanded/itemCollapsed and trigger a save (load restores silently).
        self._tree.blockSignals(True)
        self._tree.clear()
        items = [self._build_item(n) for n in nodes]
        for item in items:
            self._tree.addTopLevelItem(item)
        for node, item in zip(nodes, items):
            self._restore_expansion(node, item)
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
        self._changed()

    def _rename_folder(self, item: QTreeWidgetItem) -> None:
        name, ok = QInputDialog.getText(
            self, "Rename Folder", "Folder name:", text=item.text(0)
        )
        if ok and name.strip():
            item.setText(0, name.strip())
            self._changed()

    def _delete_folder(self, item: QTreeWidgetItem) -> None:
        """Delete a folder, moving its contents up to the parent. Files and
        subfolders move up together; moved subfolders keep their own contents.
        A folder holding .sim files asks first."""
        parent = item.parent()
        if list(self._iter_files(item)):
            where = "the main files list" if parent is None else f"“{parent.text(0)}”"
            if QMessageBox.warning(
                self, "Delete folder",
                f"“{item.text(0)}” will be deleted.\n\n"
                f"Its contents will be moved up to {where}.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
        # Re-parent the immediate children (files and subfolders, each keeping
        # its own contents), then drop the now-empty folder.
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

    def _folder_properties(self, item: QTreeWidgetItem) -> None:
        """Show the folder's combined .sim size and file count (recursively)."""
        from starpost.gui.views.properties_dialog import FolderPropertiesDialog

        paths = [Path(f.data(0, _PATH_ROLE)) for f in self._iter_files(item)]
        total = 0
        for p in paths:
            try:
                total += p.stat().st_size
            except OSError:  # missing/unreadable file contributes nothing
                pass
        FolderPropertiesDialog(item.text(0), total, len(paths), self).exec()

    # --- slots -----------------------------------------------------------
    def add_files_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add .sim files", "", "STAR-CCM+ sim (*.sim)"
        )
        self._add_paths([Path(p) for p in paths])

    def add_folder_dialog(self) -> None:
        """Pick a folder and add its .sim files inside a new internal folder named
        after it (skipping any already present elsewhere in the list)."""
        chosen = QFileDialog.getExistingDirectory(self, "Add folder of .sim files")
        if not chosen:
            return
        folder = Path(chosen)
        sims = sorted(folder.glob("*.sim"))
        if not sims:
            QMessageBox.information(
                self, "Add folder", f"No .sim files found in “{folder.name}”."
            )
            return
        existing = {p.resolve() for p in self.files()}
        new = [p for p in sims if p.resolve() not in existing]
        if not new:
            QMessageBox.information(
                self, "Add folder",
                f"Every .sim file in “{folder.name}” is already in the list.",
            )
            return

        item = self._make_folder_item(folder.name)
        for p in new:
            item.addChild(self._make_file_item(p))
        self._tree.addTopLevelItem(item)
        item.setExpanded(True)  # captured by _apply_sort's serialize/rebuild
        self._apply_sort()
        self._changed()

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

    def _on_expansion_changed(self, _item: QTreeWidgetItem) -> None:
        """A folder was expanded/collapsed by the user; persist the new layout so
        the open/closed state survives a restart. Only the layout changed, so
        save without re-emitting files_changed."""
        self._save()

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

    def _load_selected(self) -> None:
        """Queue the selected files for extraction (Ctrl+L), falling back to the
        current item when nothing is selected. Same signal as the context
        menu's Load file entry."""
        paths = [
            Path(f.data(0, _PATH_ROLE)) for f in self._iter_files() if f.isSelected()
        ]
        if not paths:
            item = self._tree.currentItem()
            if item is not None and not _is_folder(item):
                paths = [Path(item.data(0, _PATH_ROLE))]
        if paths:
            self.open_requested.emit(paths)

    def _properties_current(self) -> None:
        """Properties for the current item (Ctrl+P): the folder dialog for a
        folder, the file-properties signal for a file."""
        item = self._tree.currentItem()
        if item is None:
            return
        if _is_folder(item):
            self._folder_properties(item)
        else:
            self.properties_requested.emit(item.data(0, _PATH_ROLE))

    def _context_menu_at(self, pos) -> None:
        """Show the item context menu, then clear the row's leftover hover
        highlight — the menu grabbed the mouse, so the view never saw the pointer
        leave the row it popped up over."""
        try:
            self._show_context_menu(pos)
        finally:
            clear_item_view_hover(self._tree)

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
            # Sort submenu: orders only this folder's contents. The folder's
            # active mode (default A–Z) shows a checkmark.
            sort_menu = menu.addMenu("Sort")
            current_sort = self._folder_sort_mode(item)
            sort_actions = {}
            for label, mode in (
                ("A–Z", "name_az"),
                ("Z–A", "name_za"),
                ("File Size Largest", "size_large"),
                ("File Size Smallest", "size_small"),
            ):
                act = sort_menu.addAction(label)
                act.setCheckable(True)
                act.setChecked(mode == current_sort)
                sort_actions[act] = mode
            menu.addSeparator()
            rename_act = menu.addAction("Rename")
            # Delete folder dissolves the folder but keeps its files, so it
            # does not get the Del hint; that key actually runs Remove below.
            delete_act = menu.addAction("Delete folder")
            remove_act = menu.addAction(shortcuts.menu_label("Remove"))
            menu.addSeparator()
            props_act = menu.addAction(shortcuts.menu_label("Properties"))
            for act, shortcut_id in (
                (remove_act, "file_remove"),
                (props_act, "file_props"),
            ):
                act.setShortcut(QKeySequence(shortcuts.key(shortcut_id)))
                act.setShortcutVisibleInContextMenu(True)
            chosen = menu.exec(global_pos)
            if chosen is open_act:
                self._open_folder(item)
            elif chosen is new_act:
                self._new_folder(item)
            elif chosen in sort_actions:
                self._sort_folder(item, sort_actions[chosen])
            elif chosen is rename_act:
                self._rename_folder(item)
            elif chosen is delete_act:
                self._delete_folder(item)
            elif chosen is remove_act:
                # Removing acts on the selection; make the right-clicked
                # folder part of it when nothing was selected.
                if not item.isSelected():
                    self._tree.setCurrentItem(item)
                    item.setSelected(True)
                self._remove_selected()
            elif chosen is props_act:
                self._folder_properties(item)
            return

        # A file: Load acts on every selected file (top-to-bottom); Properties
        # on just the right-clicked one. With two or more files selected the
        # action loads them all, so label it "Load files".
        paths = [Path(f.data(0, _PATH_ROLE)) for f in self._iter_files()
                 if f.isSelected()] or [Path(item.data(0, _PATH_ROLE))]
        load_act = menu.addAction(
            shortcuts.menu_label("Load files" if len(paths) >= 2 else "Load file")
        )
        props_act = menu.addAction(shortcuts.menu_label("Properties"))
        remove_act = menu.addAction(shortcuts.menu_label("Remove"))
        for act, shortcut_id in (
            (load_act, "file_load"),
            (props_act, "file_props"),
            (remove_act, "file_remove"),
        ):
            # Display only (Qt hides shortcuts in context menus by default);
            # the always-active bindings are the tree's QShortcuts.
            act.setShortcut(QKeySequence(shortcuts.key(shortcut_id)))
            act.setShortcutVisibleInContextMenu(True)
        chosen = menu.exec(global_pos)
        if chosen is load_act:
            self.open_requested.emit(paths)
        elif chosen is props_act:
            self.properties_requested.emit(item.data(0, _PATH_ROLE))
        elif chosen is remove_act:
            # Removing acts on the selection; make the right-clicked item part
            # of it when nothing was selected.
            if not item.isSelected():
                self._tree.setCurrentItem(item)
                item.setSelected(True)
            self._remove_selected()

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
