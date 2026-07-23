"""'Part Search' window: find which loaded data sets contain a given part.

A search bar filters a two-level tree — data set → matching part names — driven
by the cached parts tree (``build_parts_tree``). Reads cached sim properties
only; it never re-runs STAR-CCM+. Double-clicking any row opens that sim's
Properties window (which carries the browsable Parts tab).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from starpost.data.parts_tree import build_parts_tree, matching_parts


class PartSearchDialog(QDialog):
    """Non-modal search window over the parts of every loaded data set."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Part Search")
        self.resize(420, 520)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search part names…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self._refresh())

        self._count = QLabel()
        self._count.setObjectName("partSearchCount")

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemDoubleClicked.connect(self._open_properties)

        layout = QVBoxLayout(self)
        layout.addWidget(self._search)
        layout.addWidget(self._count)
        layout.addWidget(self._tree)

        # (sim_name, sim_path, parts_tree) snapshot; refreshed on reopen.
        self._sims: list[tuple[str, str, object]] = []
        self.reload()
        self._search.setFocus()

    def reload(self) -> None:
        """Re-snapshot the loaded data sets and re-filter. Called on reopen so a
        re-raised window reflects the current store."""
        self._sims = [
            (r.sim_name, r.sim_path, build_parts_tree(r.properties))
            for r in self._store.all()
            if r.error is None
        ]
        self._refresh()

    def _refresh(self) -> None:
        query = self._search.text()
        expand = bool(query.strip())
        self._tree.clear()
        sim_count = 0
        part_count = 0
        for sim_name, sim_path, tree in self._sims:
            parts = matching_parts(tree, query)
            if not parts:
                continue
            sim_count += 1
            part_count += len(parts)
            top = QTreeWidgetItem([sim_name])
            top.setData(0, Qt.ItemDataRole.UserRole, sim_path)
            for name in parts:
                child = QTreeWidgetItem([name])
                child.setData(0, Qt.ItemDataRole.UserRole, sim_path)
                top.addChild(child)
            self._tree.addTopLevelItem(top)
            top.setExpanded(expand)
        self._count.setText(f"{sim_count} data sets, {part_count} parts")

    def _open_properties(self, item: QTreeWidgetItem, _col: int) -> None:
        from starpost.gui.views.properties_dialog import PropertiesDialog

        sim_path = item.data(0, Qt.ItemDataRole.UserRole)
        result = next(
            (r for r in self._store.all() if r.sim_path == sim_path), None
        )
        if result is None:
            return
        PropertiesDialog(Path(sim_path), result, self).exec()
