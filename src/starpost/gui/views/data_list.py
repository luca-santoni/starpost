"""Left 'Data' tab: the data loaded from .sim files, each named after its
source .sim. Checking entries selects which files feed the Reports/Plots views.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
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
    export_requested = Signal()
    delete_requested = Signal()  # delete the checked data sets
    clear_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._names: list[str] = []
        # Active sort, kept in sync with the Data tab's right-click menu.
        self._sort_mode = "name_az"
        self._list = _CheckList()
        self._list.setSelectionMode(QListWidget.NoSelection)
        self._list.itemChanged.connect(lambda _i: self.selection_changed.emit())

        export = QPushButton("Export")
        export.clicked.connect(self.export_requested)
        delete = QPushButton("Delete")
        delete.clicked.connect(self.delete_requested)
        clear = QPushButton("Clear data")
        clear.setObjectName("clearDataButton")
        clear.clicked.connect(self.clear_requested)
        # Export on the left; Delete and Clear data anchored to the bottom
        # right, with Delete immediately left of Clear data.
        buttons = QHBoxLayout()
        buttons.addWidget(export)
        buttons.addStretch(1)
        buttons.addWidget(delete)
        buttons.addWidget(clear)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(buttons)

    def set_entries(self, names: list[str]) -> None:
        """Replace the listed entries (one per loaded .sim, by name), keeping
        the existing checked state for names that are still present."""
        self._names = list(names)
        self._render()

    def checked_names(self) -> list[str]:
        return [
            self._list.item(i).text()
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
        ]

    # --- sorting ---------------------------------------------------------
    def show_sort_menu(self, global_pos) -> None:
        """Show the sort options at a global position (the Data tab is
        right-clicked). The active mode shows a checkmark."""
        menu = QMenu(self)
        options = [("Name (A–Z)", "name_az"), ("Name (Z–A)", "name_za")]
        actions = {}
        for text, key in options:
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(key == self._sort_mode)
            actions[act] = key
        chosen = menu.exec(global_pos)
        if chosen is not None:
            self._sort_mode = actions[chosen]
            self._render()

    def _render(self) -> None:
        """Rebuild the rows in the active sort order, preserving checked state."""
        checked = set(self.checked_names())
        names = sorted(self._names, key=str.lower,
                       reverse=self._sort_mode == "name_za")
        self._list.blockSignals(True)  # rebuilding shouldn't emit per item
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
