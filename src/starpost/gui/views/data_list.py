"""Left 'Data' tab: the data loaded from .sim files, each named after its
source .sim. Checking entries selects which files feed the Reports/Plots views.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class _CheckList(QListWidget):
    """A list whose rows toggle their checkbox when clicked anywhere, not just
    on the small indicator."""

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            checked = item.checkState() == Qt.CheckState.Checked
            item.setCheckState(
                Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
            )
            event.accept()  # we handled the toggle; skip the default indicator hit
            return
        super().mousePressEvent(event)


class DataListPanel(QWidget):
    # Emitted when the set of checked entries changes.
    selection_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._list = _CheckList()
        self._list.setSelectionMode(QListWidget.NoSelection)
        self._list.itemChanged.connect(lambda _i: self.selection_changed.emit())

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)

    def set_entries(self, names: list[str]) -> None:
        """Replace the listed entries (one per loaded .sim, by name), keeping
        the existing checked state for names that are still present."""
        checked = set(self.checked_names())
        self._list.blockSignals(True)  # repopulating shouldn't emit per item
        self._list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(
                (item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                & ~Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(
                Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)
        self._list.blockSignals(False)

    def checked_names(self) -> list[str]:
        return [
            self._list.item(i).text()
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
        ]
