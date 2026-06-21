"""Small shared Qt widgets reused across the GUI."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QStyledItemDelegate,
    QTabBar,
    QToolButton,
    QWidget,
)


class ToolTipResetStyle(QProxyStyle):
    """Proxy style that makes each hover wait the full tooltip delay.

    Qt normally keeps tooltips "awake" for a short window after one is hidden, so
    moving the cursor straight to another widget shows its tooltip instantly.
    Returning 0 for the fall-asleep delay removes that window: Qt sleeps as soon
    as a tooltip hides, so hovering a new button restarts the wake-up timer.
    Every other style decision is delegated unchanged to the base style, so the
    app's appearance (driven by the QSS theme) is untouched.

    The base style defaults to **Fusion** rather than the platform default, so the
    app uses one consistent style on every OS. Without this, Qt proxies the native
    style (Fusion on Linux, windows11/vista on Windows), whose differing item/tab
    metrics make lists and tabs space wider on Windows than on Linux. Fusion is a
    lightweight, fully cross-platform style, so this gives identical spacing with
    no meaningful rendering cost (the dark QSS theme already drives the look).
    """

    def __init__(self, base=None) -> None:
        super().__init__(base or QStyleFactory.create("Fusion"))

    def styleHint(  # noqa: N802 (Qt override)
        self, hint, option=None, widget=None, returnData=None
    ) -> int:
        if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return 0
        # Fusion's combo popup is a centred menu that opens over the box (so it
        # rises above the widget when a lower item is selected). Force the plain
        # list popup instead, so dropdowns always open downward.
        if hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)


class SecretLineEdit(QWidget):
    """A text field for a secret (e.g. the POD key): masked by default, with a
    Show/Hide toggle to reveal it on demand.

    Exposes the slice of the QLineEdit API the dialogs use (``text``,
    ``setText``, ``setPlaceholderText``), so it drops in where a plain
    QLineEdit was. Disabling the widget disables the field and toggle together.
    Re-created masked each time a dialog opens, so a stored key is never shown
    until the user asks.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)

        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setText("Show")
        self._toggle.setToolTip("Show or hide the key")
        self._toggle.toggled.connect(self._on_toggled)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._edit)
        row.addWidget(self._toggle)

    def _on_toggled(self, shown: bool) -> None:
        self._edit.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        )
        self._toggle.setText("Hide" if shown else "Show")

    # --- QLineEdit-compatible surface used by the dialogs ----------------
    def text(self) -> str:
        return self._edit.text()

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._edit.setText(text)

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._edit.setPlaceholderText(text)


class UniformTabBar(QTabBar):
    """A tab bar whose tabs all render at one shared width — the widest tab's
    natural size — so e.g. "Reports" and "Plots" are equal.

    The width is recomputed from the live tab size hints on every layout pass, so
    it tracks the current font (it grows with the Appearance text-size setting
    instead of clipping). Bars linked with :meth:`link` share a single width
    across the group, letting sibling tab bars (Files/Data and Reports/Plots)
    match each other exactly."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._peers: list[UniformTabBar] = []

    def link(self, *bars: "UniformTabBar") -> None:
        """Size this bar and ``bars`` to one shared width: the widest tab across
        the whole group, recomputed live so it follows font changes."""
        group = [self, *bars]
        for bar in group:
            bar._peers = [other for other in group if other is not bar]
            bar.updateGeometry()

    def _natural_max_width(self) -> int:
        """The widest natural tab width in this bar (bypassing the override below
        so linked bars can query each other without recursing)."""
        return max(
            (QTabBar.tabSizeHint(self, i).width() for i in range(self.count())),
            default=0,
        )

    def tabSizeHint(self, index):  # noqa: N802 (Qt override)
        size = super().tabSizeHint(index)
        width = max(
            [self._natural_max_width(), *(p._natural_max_width() for p in self._peers)]
        )
        size.setWidth(width)
        return size


# Accent colour used to outline the hovered dropdown item. Updated by the theme
# (apply_theme -> set_combo_accent_color) so the outline tracks the user's accent.
_combo_accent_color = "#ffc829"


def set_combo_accent_color(color: str) -> None:
    """Set the colour used to outline the hovered item in dropdown popups."""
    global _combo_accent_color
    if color:
        _combo_accent_color = color


# States that mark a dropdown item as the hovered / current / selected one.
_COMBO_HILITE = (
    QStyle.StateFlag.State_Selected
    | QStyle.StateFlag.State_MouseOver
    | QStyle.StateFlag.State_HasFocus
)

# Extra vertical space (px, total) added to each dropdown row so the options
# aren't cramped together.
_COMBO_ITEM_VPAD = 10


class _ComboItemDelegate(QStyledItemDelegate):
    """Draws a dropdown popup's hovered item with an accent outline instead of
    the style's default black focus rectangle (and without a background fill),
    and adds a little vertical breathing room between rows.

    The combo popup's items are painted by QStyleSheetStyle, which ignores QSS
    ``:hover``/``outline`` rules and the palette for this indicator — so the item
    is rendered plain (highlight states stripped) and the accent border is drawn
    on top here, the one place that reliably controls it."""

    def sizeHint(self, option, index):  # noqa: N802 (Qt override)
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + _COMBO_ITEM_VPAD)
        return size

    def paint(self, painter, option, index) -> None:  # noqa: N802 (Qt override)
        highlighted = bool(option.state & _COMBO_HILITE)
        # Render the item as a normal row: no fill, no black focus rectangle.
        option.state = option.state & ~_COMBO_HILITE
        super().paint(painter, option, index)
        if highlighted:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(QPen(QColor(_combo_accent_color), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(option.rect.adjusted(0, 0, -1, -1))
            painter.restore()


class _ComboAccentInstaller(QObject):
    """Application event filter that gives every QComboBox popup the accent-outline
    item delegate the first time the combo is shown."""

    _FLAG = "_starpostComboAccent"

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.Show and isinstance(obj, QComboBox):
            view = obj.view()
            if view is not None and not view.property(self._FLAG):
                view.setItemDelegate(_ComboItemDelegate(view))
                view.setProperty(self._FLAG, True)
        return False  # never consume the event


_combo_installer: _ComboAccentInstaller | None = None


def install_combo_accent(app) -> None:
    """Install (once) the app-wide filter that applies the accent-outline delegate
    to every dropdown popup."""
    global _combo_installer
    if _combo_installer is None:
        _combo_installer = _ComboAccentInstaller()
        app.installEventFilter(_combo_installer)
