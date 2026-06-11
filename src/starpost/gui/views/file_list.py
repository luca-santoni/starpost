"""Left panel: the batch list of .sim files (add files/folder, remove, clear)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MAX_FILES = 25  # v1 expected ceiling; warn beyond this


class FileListPanel(QWidget):
    files_changed = Signal(list)  # list[Path]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.ExtendedSelection)

        add_files = QPushButton("Add files…")
        add_folder = QPushButton("Add folder…")
        remove = QPushButton("Remove")
        clear = QPushButton("Clear")
        add_files.clicked.connect(self._add_files)
        add_folder.clicked.connect(self._add_folder)
        remove.clicked.connect(self._remove_selected)
        clear.clicked.connect(self._clear)

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

    def _clear(self) -> None:
        self._list.clear()
        self.files_changed.emit([])
