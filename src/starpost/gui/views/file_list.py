"""Left panel: the batch list of .sim files (add files/folder, remove, clear)."""
from __future__ import annotations

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

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(buttons)

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
