"""Scenes view (centre tab): a gallery of rendered scene stills.

Mirrors the Reports/Plots centre tabs in spirit. It shows thumbnails of the
stills rendered for the ticked data sets; double-clicking one opens it in the
system image viewer. While nothing has been rendered it shows a centred hint.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStackedLayout,
    QWidget,
)

from starpost.data.models import MediaArtifact

_THUMB = 220  # thumbnail edge in px
_ART_ROLE = Qt.ItemDataRole.UserRole + 1  # the MediaArtifact behind a thumbnail


class _Gallery(QListWidget):
    """Thumbnail list that deselects when empty space is clicked, so the accent
    highlight is removed from any selected thumbnail (default Qt keeps it)."""

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.itemAt(event.position().toPoint()) is None:
            self.clearSelection()
            self.setCurrentItem(None)
        super().mousePressEvent(event)


class SceneView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._hint = QLabel("Select scenes and press Run to render stills")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setEnabled(False)  # muted, like a placeholder

        self._gallery = _Gallery()
        self._gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self._gallery.setIconSize(QSize(_THUMB, _THUMB))
        self._gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._gallery.setMovement(QListWidget.Movement.Static)
        self._gallery.setSpacing(8)
        self._gallery.setWordWrap(True)
        self._gallery.setUniformItemSizes(True)
        self._gallery.itemDoubleClicked.connect(self._open_item)
        self._gallery.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._gallery.customContextMenuRequested.connect(self._show_context_menu)

        self._stack = QStackedLayout(self)
        self._stack.addWidget(self._hint)
        self._stack.addWidget(self._gallery)
        self._stack.setCurrentWidget(self._hint)

    def clear(self) -> None:
        self._gallery.clear()
        self._stack.setCurrentWidget(self._hint)

    def show_media(self, artifacts: list[MediaArtifact]) -> None:
        """Show one thumbnail per still in ``artifacts`` (errored or missing
        files are listed without an image). Falls back to the hint when empty."""
        self._gallery.clear()
        stills = [a for a in artifacts if a.kind == "still"]
        if not stills:
            self._stack.setCurrentWidget(self._hint)
            return

        for art in stills:
            label = art.name or Path(art.path).stem
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, art.path)
            item.setData(_ART_ROLE, art)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            if art.error:
                item.setText(f"{label}\n(render failed)")
            elif art.path and Path(art.path).exists():
                pix = QPixmap(art.path)
                if not pix.isNull():
                    item.setIcon(QIcon(pix))
                item.setToolTip(art.path)
            else:
                item.setText(f"{label}\n(file missing)")
            self._gallery.addItem(item)

        self._stack.setCurrentWidget(self._gallery)

    def _open_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _show_context_menu(self, pos) -> None:
        """Right-clicking a thumbnail offers Properties for that rendered still."""
        item = self._gallery.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        properties = menu.addAction("Properties")
        chosen = menu.exec(self._gallery.viewport().mapToGlobal(pos))
        if chosen is properties:
            from starpost.gui.views.properties_dialog import ScenePropertiesDialog

            art = item.data(_ART_ROLE)
            if art is not None:
                ScenePropertiesDialog(art, self).exec()
