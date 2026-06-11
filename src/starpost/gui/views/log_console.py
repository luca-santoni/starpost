"""Bottom panel: live batch log + progress bar."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class LogConsole(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = QPlainTextEdit(readOnly=True)
        self._text.setMaximumBlockCount(5000)
        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._progress)
        layout.addWidget(self._text)

    def append(self, line: str) -> None:
        self._text.appendPlainText(line)

    def set_progress(self, done: int, total: int) -> None:
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(done)
        self._progress.setFormat(f"{done}/{total}")

    def clear(self) -> None:
        self._text.clear()
        self._progress.reset()
