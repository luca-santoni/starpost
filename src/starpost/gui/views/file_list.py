"""Left panel: the batch list of .sim files (add files/folder, remove, clear)."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from starpost.utils.paths import file_list_cache_path

MAX_FILES = 25  # v1 expected ceiling; warn beyond this


class FileListPanel(QWidget):
    files_changed = Signal(list)  # list[Path]
    open_requested = Signal(Path)  # a single .sim to extract & view

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
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

        header = QLabel("Files")
        header.setObjectName("panelHeader")
        # Hug the text so it reads as a single tab rather than a full-width bar.
        header.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(header)
        header_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(header_row)
        layout.addWidget(self._list)
        layout.addLayout(buttons)

        # The list survives restarts even though it's separate from the
        # extracted-result cache, so changes are persisted to disk.
        self.files_changed.connect(self._save)
        self._load()

    # --- data ------------------------------------------------------------
    def files(self) -> list[Path]:
        return [Path(self._list.item(i).text()) for i in range(self._list.count())]

    def _add_paths(self, paths: list[Path]) -> None:
        existing = {p.resolve() for p in self.files()}
        for p in paths:
            if p.suffix == ".sim" and p.resolve() not in existing:
                self._list.addItem(QListWidgetItem(str(p)))
        self.files_changed.emit(self.files())

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
        remove_act = menu.addAction("Remove")
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen is open_act:
            self.open_requested.emit(Path(item.text()))
        elif chosen is remove_act:
            self._remove_selected()

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
            self._list.addItem(QListWidgetItem(str(p)))
