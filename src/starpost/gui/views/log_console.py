"""Bottom panel: an x/x counter and thin progress bar above the live batch log.

The counter and bar show only while a run is active, lingering a few seconds
after it finishes before disappearing.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

# The bar runs on a fine scale (not the job count) so it can show a small
# sliver while the first file is still opening.
_SCALE = 1000
_STARTING_FRACTION = 0.02  # ~2% shown before the first file finishes
_HIDE_DELAY_MS = 5000      # hide the counter/bar this long after a run finishes


class LogConsole(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # An x/x counter sits above a slim progress bar, both above the log.
        self._counter = QLabel("")
        self._progress = QProgressBar()
        self._progress.setObjectName("progressUnderline")
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(3)
        self._progress.setRange(0, _SCALE)
        self._text = QPlainTextEdit(readOnly=True)
        self._text.setMaximumBlockCount(5000)

        # Single-shot timer that hides the progress UI after a run completes.
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(lambda: self._set_progress_visible(False))

        layout = QVBoxLayout(self)
        layout.setSpacing(2)
        layout.addWidget(self._counter)
        layout.addWidget(self._progress)
        layout.addWidget(self._text)

        self._set_progress_visible(False)  # hidden until a run starts

    def _set_progress_visible(self, visible: bool) -> None:
        self._counter.setVisible(visible)
        self._progress.setVisible(visible)

    def append(self, line: str) -> None:
        self._text.appendPlainText(line)

    def start_progress(self, total: int) -> None:
        """Show the counter and a sliver of progress the moment a run begins,
        before the first file has finished."""
        self._hide_timer.stop()  # a new run cancels any pending hide
        self._set_progress_visible(True)
        self._counter.setText(f"0/{total}")
        self._progress.setValue(round(_SCALE * _STARTING_FRACTION))

    def set_progress(self, done: int, total: int) -> None:
        self._counter.setText(f"{done}/{total}")
        self._progress.setValue(round(_SCALE * done / max(total, 1)))

    def finish_progress(self) -> None:
        """Hide the counter and bar a few seconds after the run completes."""
        self._hide_timer.start(_HIDE_DELAY_MS)

    def clear(self) -> None:
        self._text.clear()
        self._progress.reset()
        self._counter.setText("")
