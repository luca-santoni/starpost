"""Small shared Qt widgets reused across the GUI."""
from __future__ import annotations

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QStyledItemDelegate,
    QTabBar,
    QToolButton,
    QWidget,
)


class DangerMenuItem(QLabel):
    """A destructive entry for a QMenu, hosted by a QWidgetAction: red text
    like the danger buttons, with the theme's neutral hover fill (styled by
    the ``dangerMenuItem`` QSS rules). A plain QAction is no use here — the
    app stylesheet colours all menu items alike, with no per-item override.
    Emits ``clicked`` on a left-button release inside the label."""

    clicked = Signal()

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setObjectName("dangerMenuItem")

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def enable_range_selection(view: QAbstractItemView) -> None:
    """Give an item view (list/tree/table) Shift+click range selection and
    Ctrl+click toggle, matching the multi-select behaviour common to other
    desktop apps.

    A no-op for views whose selection is disabled (checkbox-driven lists use
    ``NoSelection``), so calling it is always safe. Navigation lists that must
    stay single-select simply don't call this."""
    if view.selectionMode() != QAbstractItemView.SelectionMode.NoSelection:
        view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)


def _apply_check_range(view, anchor: QPersistentModelIndex, target: QModelIndex) -> bool:
    """Set the check state of every checkable item between ``anchor`` and
    ``target`` (inclusive), in row order at their shared tree level, to the
    anchor's check state. Returns False (doing nothing) when the two sit under
    different parents (mixed tree levels)."""
    model = view.model()
    parent = anchor.parent()
    if parent != target.parent():
        return False
    col = target.column()
    lo, hi = sorted((anchor.row(), target.row()))
    state = model.data(
        model.index(anchor.row(), col, parent), Qt.ItemDataRole.CheckStateRole
    )
    if state is None:
        return False
    for r in range(lo, hi + 1):
        idx = model.index(r, col, parent)
        if bool(model.flags(idx) & Qt.ItemFlag.ItemIsUserCheckable):
            model.setData(idx, state, Qt.ItemDataRole.CheckStateRole)
    return True


class _CheckRangeFilter(QObject):
    """Viewport event filter adding Shift+click range check-toggling to a
    checkable list/tree.

    A plain left click on a checkable item records the range anchor; a Shift+left
    click sets every checkable item between the anchor and the clicked item
    (inclusive, at the same tree level) to the anchor's check state — the common
    "click one, Shift+click another" behaviour. The Shift press and its release
    are consumed so the view's own click-to-toggle doesn't also fire."""

    def __init__(self, view: QAbstractItemView) -> None:
        super().__init__(view)
        self._view = view
        self._anchor: QPersistentModelIndex | None = None
        self._suppress_release = False
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        et = event.type()
        if (
            et == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._suppress_release = False
            idx = self._view.indexAt(event.position().toPoint())
            if idx.isValid() and bool(
                self._view.model().flags(idx) & Qt.ItemFlag.ItemIsUserCheckable
            ):
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                if shift and self._anchor is not None and self._anchor.isValid():
                    if _apply_check_range(self._view, self._anchor, idx):
                        self._suppress_release = True
                        return True  # consume: skip the view's own toggle
                self._anchor = QPersistentModelIndex(idx)
            return False
        if (
            et == QEvent.Type.MouseButtonRelease
            and self._suppress_release
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._suppress_release = False
            return True  # swallow the release paired with a consumed Shift press
        return False


def enable_check_range(view: QAbstractItemView) -> None:
    """Give a checkable list/tree Shift+click range check-toggling (see
    :class:`_CheckRangeFilter`). Call once per view."""
    _CheckRangeFilter(view)


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


# Dynamic property marking an item view exempt from click-to-deselect — for
# views whose selection drives content and must never be cleared by a click.
_KEEP_SELECTION_PROP = "starpostKeepSelection"


def exempt_click_deselect(view: QAbstractItemView) -> None:
    """Opt ``view`` out of the app-wide click-to-deselect behaviour (see
    :class:`_ClickDeselectFilter`) — for navigation-style views (e.g. the
    settings dialog's group list) whose selection picks what is shown and so
    must never be empty."""
    view.setProperty(_KEEP_SELECTION_PROP, True)


class _ClickDeselectFilter(QObject):
    """Application event filter: a plain left click on an already-selected item
    clears its view's selection, so the accent highlight never lingers with no
    way to remove it (clicking a highlighted row again "un-highlights" it).

    Applies to every QAbstractItemView viewport except: popup views (combo
    dropdowns, completers — deselecting inside those breaks the control), the
    fallback QFileDialog's internals, header views (clicks there sort),
    NoSelection views, and views opted out via :func:`exempt_click_deselect`.

    Never consumes events, so dragging, double-click actions, context menus,
    editing and checkbox toggles keep their native behaviour. The clear runs
    one event-loop turn after the release — letting the view finish its own
    release handling first — and only when the click really was a click (same
    index, within the drag threshold, no modifiers) and didn't toggle the
    item's checkbox (a check action, not a deselect: covers native indicator
    clicks and the click-anywhere-toggles checklist rows)."""

    def __init__(self) -> None:
        super().__init__()
        # The last candidate press — a plain left press on an already-selected
        # index: (view, index, press pos, check state at press).
        self._pending: tuple | None = None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        et = event.type()
        if et == QEvent.Type.MouseButtonPress:
            self._pending = None
            if (
                event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
            ):
                view = self._deselectable_view(obj)
                if view is not None:
                    pos = event.position().toPoint()
                    idx = view.indexAt(pos)
                    if idx.isValid() and view.selectionModel().isSelected(idx):
                        self._pending = (
                            view,
                            QPersistentModelIndex(idx),
                            pos,
                            idx.data(Qt.ItemDataRole.CheckStateRole),
                        )
        elif et == QEvent.Type.MouseButtonDblClick:
            # The double-click replaces the second press; its trailing release
            # must not deselect (the double-click action is the intent).
            self._pending = None
        elif et == QEvent.Type.MouseButtonRelease and self._pending is not None:
            view, idx, press_pos, check = self._pending
            self._pending = None
            pos = event.position().toPoint()
            if (
                event.button() == Qt.MouseButton.LeftButton
                and obj is view.viewport()
                and (pos - press_pos).manhattanLength()
                <= QApplication.startDragDistance()
                and idx.isValid()
                and view.indexAt(pos) == idx
            ):
                QTimer.singleShot(0, lambda: self._clear(view, idx, check))
        return False  # never consume the event

    @staticmethod
    def _deselectable_view(obj) -> QAbstractItemView | None:
        """The item view whose viewport ``obj`` is, when click-to-deselect
        applies to it; None otherwise."""
        if not isinstance(obj, QWidget):
            return None
        view = obj.parent()
        if (
            not isinstance(view, QAbstractItemView)
            or isinstance(view, QHeaderView)
            or view.viewport() is not obj
            or view.selectionMode() == QAbstractItemView.SelectionMode.NoSelection
            or view.property(_KEEP_SELECTION_PROP)
        ):
            return None
        window = view.window()
        if window.windowType() == Qt.WindowType.Popup or isinstance(window, QFileDialog):
            return None
        return view

    @staticmethod
    def _clear(view, idx, check) -> None:
        try:
            if not idx.isValid() or idx.data(Qt.ItemDataRole.CheckStateRole) != check:
                return  # the row went away, or the click toggled its checkbox
            # Clears the selection *and* the current index, so the focus
            # outline goes together with the accent fill.
            view.selectionModel().clear()
        except RuntimeError:  # view destroyed before the deferred clear ran
            pass


_click_deselect_installer: _ClickDeselectFilter | None = None


def install_click_deselect(app) -> None:
    """Install (once) the app-wide filter that makes a plain click on an
    already-selected item clear the selection highlight."""
    global _click_deselect_installer
    if _click_deselect_installer is None:
        _click_deselect_installer = _ClickDeselectFilter()
        app.installEventFilter(_click_deselect_installer)


class BarMenu(QMenu):
    """A menu-bar-style dropdown for the top bar's menu buttons.

    Opened by clicking its :class:`BarMenuButton` (via ``InstantPopup``),
    it behaves like a menu on a traditional menu bar: it stays open no matter
    where the pointer goes, and only a click anywhere else (or Esc) dismisses
    it — both native QMenu popup behaviours.

    While open it holds the mouse grab, so it — not the bar's buttons — sees
    the pointer crossing the bar. When the pointer lands on a *different*
    enabled menu button on ``sibling_bar``, the menu hands off: it closes and
    opens that button's menu, so the bar's dropdowns can be browsed with a
    single click, menu-bar style.

    One limitation: while a child submenu (e.g. File ▸ Add) is the active
    popup, Qt delivers the grabbed moves to it, not to this menu, so the
    handoff pauses until the pointer re-crosses this menu (which closes the
    submenu) — a fast move straight to the other button needs a click.
    """

    def __init__(
        self,
        parent=None,
        owner: QWidget | None = None,
        sibling_bar: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # The button the menu belongs to: skipped when scanning for handoff
        # targets, and cleared of its stuck hover outline when the menu hides.
        self._owner = owner
        # The bar holding the owner; its *other* menu buttons are hover-switch
        # handoff targets while this menu is open.
        self._sibling_bar = sibling_bar

    @staticmethod
    def _global_rect(w: QWidget) -> QRect:
        return QRect(w.mapToGlobal(w.rect().topLeft()), w.size())

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if self._sibling_bar is None:
            return
        pos = event.globalPosition().toPoint()
        for btn in self._sibling_bar.findChildren(BarMenuButton):
            if (
                btn is not self._owner
                and btn.isEnabled()
                and btn.menu() is not None
                and self._global_rect(btn).contains(pos)
            ):
                # Hand off: close this menu, then open the hovered button's.
                # Deferred — showMenu blocks, so this close must unwind first.
                self.close()
                QTimer.singleShot(0, btn.showMenu)
                return

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        # The grab swallowed the owner's leave event; drop its stale hover
        # outline on every close path (outside click, Esc, handoff).
        if isinstance(self._owner, BarMenuButton):
            try:
                self._owner._clear_stuck_hover()
            except RuntimeError:  # owner already destroyed (app teardown)
                pass


class BarMenuButton(QToolButton):
    """A toolbar button for a :class:`BarMenu` dropdown. Opens on click only
    (callers set ``InstantPopup``); hovering never opens a closed menu. Hover
    *does* switch menus while a sibling's menu is already open — that handoff
    lives in :class:`BarMenu`, which holds the mouse grab at that point."""

    def _clear_stuck_hover(self) -> None:
        """After the popup closes, the button keeps its hover (auto-raise) outline:
        the menu grabbed the mouse, so no leaveEvent arrived to drop the mouse-over
        state. Clear it when the pointer is no longer over the button."""
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
            self.update()


def clear_item_view_hover(view) -> None:
    """Drop an item view's leftover hover highlight after a popup (a context menu
    or a dialog) grabbed the mouse, leaving the row it was over still painted as
    hovered. Sends a synthetic Leave to the viewport — which makes the view clear
    its hover index and repaint — but only when the pointer is no longer over the
    viewport (so a genuine hover is kept)."""
    viewport = view.viewport()
    if not viewport.rect().contains(viewport.mapFromGlobal(QCursor.pos())):
        QApplication.sendEvent(viewport, QEvent(QEvent.Type.Leave))
        viewport.update()
