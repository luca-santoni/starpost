"""Application icon loading and drawn menu glyphs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

# Shipped alongside this package (see pyproject package-data / PyInstaller spec).
_ICON_FILE = Path(__file__).resolve().parent / "resources" / "StarPost-logo.png"


def app_icon() -> QIcon:
    """The StarPost window/taskbar icon."""
    return QIcon(str(_ICON_FILE))


def logo_pixmap() -> QPixmap:
    """The StarPost logo as a pixmap (e.g. for the About page)."""
    return QPixmap(str(_ICON_FILE))


# --- dropdown menu glyphs -------------------------------------------------
#
# Flat monochrome line glyphs for the top bar's dropdown entries (File, Run
# batch), in the same hand-drawn style as the window caption buttons: QPainter
# strokes on a 16x16 logical grid, tinted to the theme at build time (menus in
# STAR-CCM+, the visual reference, carry a small icon beside each entry).

_MENU_ICON_PX = 16


def _plus(p: QPainter, cx: float, cy: float, r: float) -> None:
    p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
    p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))


def _tray(p: QPainter) -> None:
    """An open-topped tray in the lower part of the box (import/export target)."""
    p.drawPolyline(
        [QPointF(3.0, 9.5), QPointF(3.0, 13.0), QPointF(13.0, 13.0), QPointF(13.0, 9.5)]
    )


def _arrow(p: QPainter, tip_y: float, tail_y: float) -> None:
    """A vertical arrow on the centre line; points down when tip_y > tail_y."""
    head = 2.2 if tip_y > tail_y else -2.2
    p.drawLine(QPointF(8.0, tail_y), QPointF(8.0, tip_y))
    p.drawLine(QPointF(8.0, tip_y), QPointF(8.0 - 2.2, tip_y - head))
    p.drawLine(QPointF(8.0, tip_y), QPointF(8.0 + 2.2, tip_y - head))


def _draw_add(p: QPainter) -> None:
    _plus(p, 8.0, 8.0, 4.5)


def _draw_add_files(p: QPainter) -> None:
    # Document with a folded top-right corner, plus mark at its foot.
    p.drawPolyline(
        [
            QPointF(9.0, 2.5),
            QPointF(4.0, 2.5),
            QPointF(4.0, 13.5),
            QPointF(8.0, 13.5),
        ]
    )
    p.drawPolyline([QPointF(9.0, 2.5), QPointF(11.5, 5.0), QPointF(11.5, 8.0)])
    p.drawLine(QPointF(9.0, 2.5), QPointF(9.0, 5.0))
    p.drawLine(QPointF(9.0, 5.0), QPointF(11.5, 5.0))
    _plus(p, 11.5, 11.5, 2.4)


def _draw_add_folder(p: QPainter) -> None:
    # Folder silhouette (back tab + body), plus mark inside.
    p.drawPolyline(
        [
            QPointF(2.5, 12.5),
            QPointF(2.5, 4.0),
            QPointF(6.5, 4.0),
            QPointF(8.0, 5.8),
            QPointF(13.5, 5.8),
            QPointF(13.5, 12.5),
            QPointF(2.5, 12.5),
        ]
    )
    _plus(p, 8.0, 9.3, 2.0)


def _draw_import(p: QPainter) -> None:
    _tray(p)
    _arrow(p, tip_y=9.8, tail_y=2.8)  # down, into the tray


def _draw_export(p: QPainter) -> None:
    _tray(p)
    _arrow(p, tip_y=2.8, tail_y=9.8)  # up, out of the tray


def _draw_batch_full(p: QPainter) -> None:
    # Filled play triangle.
    p.setBrush(p.pen().color())
    p.drawPolygon(QPolygonF([QPointF(4.5, 3.0), QPointF(13.0, 8.0), QPointF(4.5, 13.0)]))


def _draw_batch_express(p: QPainter) -> None:
    # Fast-forward: two filled play triangles.
    p.setBrush(p.pen().color())
    p.drawPolygon(QPolygonF([QPointF(2.5, 4.0), QPointF(8.0, 8.0), QPointF(2.5, 12.0)]))
    p.drawPolygon(QPolygonF([QPointF(9.0, 4.0), QPointF(14.5, 8.0), QPointF(9.0, 12.0)]))


_MENU_GLYPHS = {
    "add": _draw_add,
    "add-files": _draw_add_files,
    "add-folder": _draw_add_folder,
    "import": _draw_import,
    "export": _draw_export,
    "batch-full": _draw_batch_full,
    "batch-express": _draw_batch_express,
}

MENU_ICON_KINDS = tuple(_MENU_GLYPHS)


def _menu_glyph_pixmap(kind: str, color: str) -> QPixmap:
    # Drawn at 2x and tagged with the device pixel ratio so the thin strokes
    # stay crisp on HiDPI screens.
    dpr = 2.0
    pixmap = QPixmap(int(_MENU_ICON_PX * dpr), int(_MENU_ICON_PX * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color), 1.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    _MENU_GLYPHS[kind](p)
    p.end()
    return pixmap


def menu_icon(
    kind: str,
    color: str,
    active_color: str | None = None,
    disabled_color: str | None = None,
) -> QIcon:
    """A theme-tinted dropdown-menu glyph. ``kind`` is one of
    :data:`MENU_ICON_KINDS` (KeyError otherwise). ``active_color`` draws the
    Active/Selected variant shown on the accent-highlighted row (where the
    normal tint may not contrast); ``disabled_color`` the greyed-out variant."""
    icon = QIcon()
    icon.addPixmap(_menu_glyph_pixmap(kind, color), QIcon.Mode.Normal)
    if active_color:
        active = _menu_glyph_pixmap(kind, active_color)
        icon.addPixmap(active, QIcon.Mode.Active)
        icon.addPixmap(active, QIcon.Mode.Selected)
    if disabled_color:
        icon.addPixmap(_menu_glyph_pixmap(kind, disabled_color), QIcon.Mode.Disabled)
    return icon
