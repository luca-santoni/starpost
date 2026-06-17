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
        # Only the left button toggles; right-click falls through so a context
        # menu (e.g. the Data tab's "Properties") can open instead.
        item = self.itemAt(event.position().toPoint())
        if item is not None and event.button() == Qt.MouseButton.LeftButton:
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
    import_requested = Signal()
    export_requested = Signal()
    delete_requested = Signal()  # delete the checked data sets
    clear_requested = Signal()
    properties_requested = Signal(object)  # a data set name to show properties for

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._names: list[str] = []
        # Active sort, kept in sync with the Data tab's right-click menu.
        self._sort_mode = "name_az"
        self._list = _CheckList()
        self._list.setSelectionMode(QListWidget.NoSelection)
        self._list.itemChanged.connect(lambda _i: self.selection_changed.emit())
        # Right-click a data set for its Properties.
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)

        import_btn = QPushButton("Import")
        import_btn.clicked.connect(self.import_requested)
        export = QPushButton("Export Data")
        export.clicked.connect(self.export_requested)
        delete = QPushButton("Delete")
        delete.clicked.connect(self.delete_requested)
        clear = QPushButton("Clear Data")
        clear.setObjectName("clearDataButton")
        clear.clicked.connect(self.clear_requested)
        # Buttons in a row with uniform spacing between them, left-aligned.
        buttons = QHBoxLayout()
        buttons.addWidget(import_btn)
        buttons.addWidget(export)
        buttons.addWidget(delete)
        buttons.addWidget(clear)
        buttons.addStretch(1)

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

    # --- context menu ----------------------------------------------------
    def _show_context_menu(self, pos) -> None:
        """Right-clicking a data set offers its Properties (size, report,
        monitor and iteration counts)."""
        item = self._list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        props_act = menu.addAction("Properties")
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen is props_act:
            self.properties_requested.emit(item.text())

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
