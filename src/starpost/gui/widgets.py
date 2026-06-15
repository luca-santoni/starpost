"""Small shared Qt widgets reused across the GUI."""
from __future__ import annotations

from PySide6.QtWidgets import QTabBar


class UniformTabBar(QTabBar):
    """A tab bar whose tabs all render at one shared width (set externally), so
    sibling tab bars (e.g. Files/Data and Reports/Plots) can match each other
    exactly."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tab_width = 0  # 0 = use each tab's natural width

    def set_tab_width(self, width: int) -> None:
        self._tab_width = width
        self.updateGeometry()

    def tabSizeHint(self, index):  # noqa: N802 (Qt override)
        size = super().tabSizeHint(index)
        if self._tab_width:
            size.setWidth(self._tab_width)
        return size
