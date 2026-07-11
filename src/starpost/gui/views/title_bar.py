"""Custom window title bar for the frameless main window.

The main window is frameless (no OS-drawn title bar), so this widget supplies
the caption: the StarPost version centred (where a vendor name sits in a classic
title bar) and integrated minimise / maximise / close buttons on the right.

Dragging the bar moves the window and pressing near a window edge resizes it;
both defer to the window manager via ``startSystemMove`` / ``startSystemResize``
so native snapping, maximise-by-drag-to-top and multi-monitor behaviour are
preserved on both Linux (X11) and Windows.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, Property
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QHBoxLayout,
    QLabel,
    QWidget,
)

TITLEBAR_HEIGHT = 32
_BTN_W = 46


class CaptionButton(QAbstractButton):
    """A flat window-caption button that paints its own glyph (minimise,
    maximise, restore or close). Its colours are Qt properties so the app
    stylesheet themes them (see theme.py)."""

    def __init__(self, kind: str, parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._hover = False
        self._glyph = QColor("#cfcfcf")
        self._hover_bg = QColor("#353535")
        self._hover_glyph = QColor("#e6e6e6")
        self.setFixedSize(_BTN_W, TITLEBAR_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_kind(self, kind: str) -> None:
        if kind != self._kind:
            self._kind = kind
            self.update()

    # --- themable colours (set from QSS via qproperty-*) -----------------
    def _get_glyph(self) -> QColor:
        return self._glyph

    def _set_glyph(self, c: QColor) -> None:
        self._glyph = c
        self.update()

    glyphColor = Property(QColor, _get_glyph, _set_glyph)

    def _get_hover_bg(self) -> QColor:
        return self._hover_bg

    def _set_hover_bg(self, c: QColor) -> None:
        self._hover_bg = c
        self.update()

    hoverBg = Property(QColor, _get_hover_bg, _set_hover_bg)

    def _get_hover_glyph(self) -> QColor:
        return self._hover_glyph

    def _set_hover_glyph(self, c: QColor) -> None:
        self._hover_glyph = c
        self.update()

    hoverGlyph = Property(QColor, _get_hover_glyph, _set_hover_glyph)

    # --- painting --------------------------------------------------------
    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        active = self._hover or self.isDown()
        if active:
            p.fillRect(self.rect(), self._hover_bg)
        glyph = self._hover_glyph if active else self._glyph
        p.setPen(QPen(glyph, 1.1))
        c = self.rect().center()
        cx, cy = c.x() + 0.5, c.y() + 0.5
        h = 4.0  # glyph half-size (~8 px box)
        if self._kind == "min":
            p.drawLine(QPointF(cx - h, cy + 3), QPointF(cx + h, cy + 3))
        elif self._kind == "max":
            p.drawRect(QRectF(cx - h, cy - h, 2 * h, 2 * h))
        elif self._kind == "restore":
            # Two offset squares reading as "overlapping windows".
            front = QRectF(cx - h - 1, cy - h + 2, 2 * h, 2 * h)
            back = QRectF(cx - h + 2, cy - h - 1, 2 * h, 2 * h)
            p.drawRect(back)
            p.fillRect(front, self._hover_bg if active else self.palette().window())
            p.drawRect(front)
        elif self._kind == "close":
            p.drawLine(QPointF(cx - h, cy - h), QPointF(cx + h, cy + h))
            p.drawLine(QPointF(cx - h, cy + h), QPointF(cx + h, cy - h))
        p.end()


class TitleBar(QWidget):
    """The frameless window's caption strip: centred version, window buttons."""

    def __init__(self, window: QWidget, version_text: str) -> None:
        super().__init__()
        self._win = window
        self.setObjectName("titleBar")
        self.setFixedHeight(TITLEBAR_HEIGHT)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # The version sits at the far right, just left of the window buttons, so
        # the whole cluster lines up above the right-hand panel (Profile). The
        # empty stretch on the left is the draggable region.
        lay.addStretch(1)

        self.version = QLabel(version_text)
        self.version.setObjectName("titleVersion")
        self.version.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        # Let clicks on the label fall through to the bar so it stays draggable.
        self.version.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.version)
        lay.addSpacing(12)

        self.btn_min = CaptionButton("min")
        self.btn_min.setObjectName("winMin")
        self.btn_max = CaptionButton("max")
        self.btn_max.setObjectName("winMax")
        self.btn_close = CaptionButton("close")
        self.btn_close.setObjectName("winClose")
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)

        self.btn_min.setToolTip("Minimise")
        self.btn_max.setToolTip("Maximise")
        self.btn_close.setToolTip("Close")
        self.btn_min.clicked.connect(self._win.showMinimized)
        self.btn_max.clicked.connect(self.toggle_maximized)
        self.btn_close.clicked.connect(self._win.close)

    def toggle_maximized(self) -> None:
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def set_maximized(self, is_max: bool) -> None:
        """Swap the maximise button between the maximise and restore glyphs."""
        self.btn_max.set_kind("restore" if is_max else "max")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._win.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()


class FramelessResizeFilter(QObject):
    """Application event filter that resizes a frameless window when the pointer
    presses near an edge, and shows the matching resize cursor on hover.

    Resizing itself is handed to the window manager (``startSystemResize``), so
    it behaves natively; this filter only detects the edge and kicks it off."""

    MARGIN = 6

    _CURSORS = {
        (True, False, True, False): Qt.CursorShape.SizeFDiagCursor,   # top-left
        (False, True, False, True): Qt.CursorShape.SizeFDiagCursor,   # bot-right
        (False, True, True, False): Qt.CursorShape.SizeBDiagCursor,   # top-right
        (True, False, False, True): Qt.CursorShape.SizeBDiagCursor,   # bot-left
        (True, False, False, False): Qt.CursorShape.SizeHorCursor,
        (False, True, False, False): Qt.CursorShape.SizeHorCursor,
        (False, False, True, False): Qt.CursorShape.SizeVerCursor,
        (False, False, False, True): Qt.CursorShape.SizeVerCursor,
    }

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._win = window
        self._override = False

    def eventFilter(self, obj, event) -> bool:
        t = event.type()
        if t == QEvent.Type.MouseMove:
            if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                self._update_cursor()
        elif t == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton and self._edges():
                self._restore_cursor()
                handle = self._win.windowHandle()
                if handle is not None:
                    handle.startSystemResize(self._edges())
                    return True
        return super().eventFilter(obj, event)

    def _flags(self):
        """(left, right, top, bottom) booleans for the pointer's proximity to
        each window edge, or None when not near any / not resizable."""
        if self._win.isMaximized() or self._win.isFullScreen():
            return None
        g = self._win.geometry()
        p = QCursor.pos()
        m = self.MARGIN
        if not g.adjusted(-m, -m, m, m).contains(p):
            return None
        flags = (
            p.x() <= g.left() + m,
            p.x() >= g.right() - m,
            p.y() <= g.top() + m,
            p.y() >= g.bottom() - m,
        )
        return flags if any(flags) else None

    def _edges(self):
        flags = self._flags()
        if flags is None:
            return None
        left, right, top, bottom = flags
        edges = Qt.Edge(0)
        if left:
            edges |= Qt.Edge.LeftEdge
        if right:
            edges |= Qt.Edge.RightEdge
        if top:
            edges |= Qt.Edge.TopEdge
        if bottom:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _update_cursor(self) -> None:
        flags = self._flags()
        cursor = self._CURSORS.get(flags) if flags is not None else None
        if cursor is not None:
            if self._override:
                QApplication.changeOverrideCursor(QCursor(cursor))
            else:
                QApplication.setOverrideCursor(QCursor(cursor))
                self._override = True
        else:
            self._restore_cursor()

    def _restore_cursor(self) -> None:
        if self._override:
            QApplication.restoreOverrideCursor()
            self._override = False
