"""Left panel: the batch list of .sim files (add files/folder, remove, clear)."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from starpost.utils.paths import file_list_cache_path

MAX_FILES = 25  # v1 expected ceiling; warn beyond this


class FileListPanel(QWidget):
    files_changed = Signal(list)  # list[Path]
    open_requested = Signal(Path)  # a single .sim to extract & view

    def __init__(self, parent=None, *, show_full_names: bool = False) -> None:
        super().__init__(parent)
        # Each item stores its full path in Qt.UserRole; the displayed text is
        # either that path or just the file name, per this flag.
        self._show_full_names = show_full_names
        # Active sort, kept in sync with the header menu's checkmark. The list is
        # always ordered by this; A–Z is the default.
        self._sort_mode = "name_az"
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.ExtendedSelection)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)

        add_files = QPushButton("Add files…")
        add_folder = QPushButton("Add folder…")
        remove = QPushButton("Remove")
        clear = QPushButton("Clear")
        add_files.clicked.connect(self._add_files)
        add_folder.clicked.connect(self._add_folder)
        remove.clicked.connect(self._remove_selected)
        clear.clicked.connect(self._clear_confirmed)

        buttons = QHBoxLayout()
        for b in (add_files, add_folder, remove, clear):
            buttons.addWidget(b)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(buttons)

        # The list survives restarts even though it's separate from the
        # extracted-result cache, so changes are persisted to disk.
        self.files_changed.connect(self._save)
        self._load()

    # --- data ------------------------------------------------------------
    def files(self) -> list[Path]:
        return [self._item_path(self._list.item(i)) for i in range(self._list.count())]

    def set_show_full_names(self, show_full_names: bool) -> None:
        """Switch between showing full paths and file names only, re-rendering
        the existing items' labels (the stored paths are unaffected)."""
        if show_full_names == self._show_full_names:
            return
        self._show_full_names = show_full_names
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setText(self._label(self._item_path(item)))

    def _label(self, path: Path) -> str:
        return str(path) if self._show_full_names else path.name

    @staticmethod
    def _item_path(item: QListWidgetItem) -> Path:
        return Path(item.data(Qt.UserRole))

    def _make_item(self, path: Path) -> QListWidgetItem:
        # Display the name or full path; always keep the full path in UserRole
        # (so it survives a display toggle) and the tooltip (handy when only the
        # name is shown).
        item = QListWidgetItem(self._label(path))
        item.setData(Qt.UserRole, str(path))
        item.setToolTip(str(path))
        return item

    def _add_paths(self, paths: list[Path]) -> None:
        existing = {p.resolve() for p in self.files()}
        for p in paths:
            if p.suffix == ".sim" and p.resolve() not in existing:
                self._list.addItem(self._make_item(p))
        self._apply_sort()  # keep the list in the active sort order
        self.files_changed.emit(self.files())

    # --- sorting ---------------------------------------------------------
    def show_sort_menu(self, global_pos) -> None:
        """Show the sort options at a global position (the Files tab is
        right-clicked). The active mode shows a checkmark."""
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
            self._sort_files(actions[chosen])

    @staticmethod
    def _size(path: Path) -> int:
        # Missing files sort as smallest so a broken path doesn't raise.
        try:
            return path.stat().st_size
        except OSError:
            return -1

    def _sort_files(self, mode: str) -> None:
        self._sort_mode = mode
        self._apply_sort()
        self.files_changed.emit(self.files())

    def _apply_sort(self) -> None:
        """Reorder the existing items by the active sort mode. Pure display
        reorder: callers emit files_changed when the new order should persist."""
        paths = self.files()
        if self._sort_mode == "name_az":
            paths.sort(key=lambda p: p.name.lower())
        elif self._sort_mode == "name_za":
            paths.sort(key=lambda p: p.name.lower(), reverse=True)
        elif self._sort_mode == "size_large":
            paths.sort(key=self._size, reverse=True)
        elif self._sort_mode == "size_small":
            paths.sort(key=self._size)
        self._list.clear()
        for p in paths:
            self._list.addItem(self._make_item(p))

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
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))
        self.files_changed.emit(self.files())

    def _show_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        # Right-clicking outside the current selection acts on just that item.
        if not item.isSelected():
            self._list.setCurrentItem(item)
        menu = QMenu(self)
        open_act = menu.addAction("Open")
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen is open_act:
            self.open_requested.emit(self._item_path(item))

    def _clear_confirmed(self) -> None:
        """Clear the list only after the user confirms the warning."""
        if self._list.count() == 0:
            return
        if QMessageBox.warning(
            self, "Clear files",
            "This will remove all files from the list. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes:
            self._clear()

    def _clear(self) -> None:
        self._list.clear()
        self.files_changed.emit([])

    # --- persistence -----------------------------------------------------
    def _save(self) -> None:
        path = file_list_cache_path()
        path.write_text(json.dumps([str(p) for p in self.files()], indent=2))

    def _load(self) -> None:
        """Restore the saved list on startup, adding items directly so this
        does not re-trigger a save of what we just read."""
        path = file_list_cache_path()
        if not path.exists():
            return
        try:
            saved = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for p in saved:
            self._list.addItem(self._make_item(Path(p)))
        self._apply_sort()  # present in the default (A–Z) order
