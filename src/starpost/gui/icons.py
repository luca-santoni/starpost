"""Application icon loading."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

# Shipped alongside this package (see pyproject package-data / PyInstaller spec).
_ICON_FILE = Path(__file__).resolve().parent / "resources" / "StarPost-logo.png"


def app_icon() -> QIcon:
    """The StarPost window/taskbar icon."""
    return QIcon(str(_ICON_FILE))


def logo_pixmap() -> QPixmap:
    """The StarPost logo as a pixmap (e.g. for the About page)."""
    return QPixmap(str(_ICON_FILE))
