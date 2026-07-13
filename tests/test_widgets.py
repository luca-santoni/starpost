import pytest
from PySide6.QtGui import QFont, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QProxyStyle,
    QStyle,
    QStyledItemDelegate,
    QTabWidget,
)

import starpost.gui.widgets as widgets
from starpost.gui.widgets import (
    ToolTipResetStyle,
    UniformTabBar,
    _ComboItemDelegate,
    install_combo_accent,
    set_combo_accent_color,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _tab_widget(bar: UniformTabBar, *labels: str) -> QTabWidget:
    """A QTabWidget using ``bar``, with one empty page per label. Returned so the
    caller keeps it alive (a dropped QTabWidget takes its tab bar with it)."""
    tabs = QTabWidget()
    tabs.setTabBar(bar)
    for label in labels:
        tabs.addTab(QTabWidget(), label)
    return tabs


def _widths(bar: UniformTabBar) -> list[int]:
    return [bar.tabSizeHint(i).width() for i in range(bar.count())]


def test_tooltip_fall_asleep_delay_is_zero(app):
    """Zeroing the fall-asleep delay makes Qt forget the previous tooltip the
    moment it hides, so hovering a new button waits the full wake-up delay again
    instead of showing its tooltip instantly."""
    style = ToolTipResetStyle()
    assert style.styleHint(QStyle.StyleHint.SH_ToolTip_FallAsleepDelay) == 0


def test_combo_popup_hint_forces_list_dropdown(app):
    """SH_ComboBox_Popup is forced off so dropdowns open as a downward list,
    never Fusion's centred menu popup that rises over the box."""
    style = ToolTipResetStyle()
    assert style.styleHint(QStyle.StyleHint.SH_ComboBox_Popup) == 0


def test_other_style_hints_delegate_unchanged(app):
    """Only the overridden hints differ; everything else (including the wake-up
    delay and unrelated hints) is delegated to the base style so the app's
    appearance is untouched."""
    style = ToolTipResetStyle()
    base = QProxyStyle()
    for hint in (
        QStyle.StyleHint.SH_ToolTip_WakeUpDelay,
        QStyle.StyleHint.SH_Slider_SnapToValue,
        QStyle.StyleHint.SH_ScrollBar_ContextMenu,
    ):
        assert style.styleHint(hint) == base.styleHint(hint)


def test_uniform_tab_bar_makes_its_tabs_equal_width(app):
    """Every tab renders at the widest tab's width, so e.g. "Plots" is as wide as
    "Reports"."""
    bar = UniformTabBar()
    _holder = _tab_widget(bar, "Reports", "Plots")  # noqa: F841 (keep alive)
    widths = _widths(bar)
    assert len(set(widths)) == 1  # all equal


def test_linked_tab_bars_share_one_width(app):
    """Linked bars (Files/Data and Reports/Plots) all match the widest tab across
    the whole group — "Reports" — so the four tabs line up."""
    center = UniformTabBar()
    left = UniformTabBar()
    _c = _tab_widget(center, "Reports", "Plots")  # noqa: F841 (keep alive)
    _l = _tab_widget(left, "Files", "Data")  # noqa: F841 (keep alive)
    center.link(left)
    assert len(set(_widths(center) + _widths(left))) == 1


def test_tab_width_grows_with_font_instead_of_clipping(app):
    """The shared width is recomputed from the live font, so enlarging the text
    (the Appearance text-size setting) widens the tabs rather than clipping."""
    center = UniformTabBar()
    left = UniformTabBar()
    _c = _tab_widget(center, "Reports", "Plots")  # noqa: F841 (keep alive)
    _l = _tab_widget(left, "Files", "Data")  # noqa: F841 (keep alive)
    center.link(left)

    small, big = QFont(), QFont()
    small.setPointSize(9)
    big.setPointSize(20)

    for b in (center, left):
        b.setFont(small)
    small_width = _widths(center)[0]
    for b in (center, left):
        b.setFont(big)
    big_width = _widths(center)[0]

    assert big_width > small_width
    # Still uniform across both bars at the larger size.
    assert len(set(_widths(center) + _widths(left))) == 1


def test_set_combo_accent_color_updates_and_ignores_empty(app):
    set_combo_accent_color("#123456")
    assert widgets._combo_accent_color == "#123456"
    set_combo_accent_color("")  # empty is ignored, keeps the previous colour
    assert widgets._combo_accent_color == "#123456"


def test_apply_theme_syncs_combo_accent_colour(app):
    from starpost.gui.theme import apply_theme

    apply_theme(app, "dark", "#4e79a7")
    assert widgets._combo_accent_color == "#4e79a7"
    apply_theme(app, "dark", "#e15759")
    assert widgets._combo_accent_color == "#e15759"


def test_installer_gives_combo_popup_the_accent_delegate(app):
    install_combo_accent(app)  # idempotent
    combo = QComboBox()
    combo.addItems(["a", "b", "c"])
    # The app-wide filter assigns the delegate when the combo is shown.
    app.sendEvent(combo, QShowEvent())
    assert isinstance(combo.view().itemDelegate(), _ComboItemDelegate)
    combo.deleteLater()


def test_combo_delegate_strips_highlight_states_before_painting(app):
    """The delegate renders the row plain (no fill / black focus rect) by clearing
    the highlight states; it draws its own accent outline instead."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionViewItem

    set_combo_accent_color("#ffc829")
    combo = QComboBox()
    combo.addItems(["a"])
    delegate = _ComboItemDelegate(combo.view())

    opt = QStyleOptionViewItem()
    opt.initFrom(combo.view())
    opt.rect = QRect(0, 0, 60, 20)
    opt.state |= QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus

    img = QImage(60, 20, QImage.Format.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    delegate.paint(painter, opt, combo.model().index(0, 0))
    painter.end()
    # The highlight states were cleared on the option passed to the base paint.
    assert not (opt.state & QStyle.StateFlag.State_Selected)
    assert not (opt.state & QStyle.StateFlag.State_HasFocus)
    combo.deleteLater()


def test_combo_delegate_adds_vertical_row_spacing(app):
    """The delegate enlarges each dropdown row so the options aren't cramped."""
    from PySide6.QtWidgets import QStyleOptionViewItem

    from starpost.gui.widgets import _COMBO_ITEM_VPAD

    combo = QComboBox()
    combo.addItems(["a"])
    delegate = _ComboItemDelegate(combo.view())
    opt = QStyleOptionViewItem()
    opt.initFrom(combo.view())
    index = combo.model().index(0, 0)

    base = QStyledItemDelegate(combo.view()).sizeHint(opt, index).height()
    assert delegate.sizeHint(opt, index).height() == base + _COMBO_ITEM_VPAD
    combo.deleteLater()


def _move_to(menu, global_pt):
    """Deliver a synthetic mouse-move at ``global_pt`` (a QPointF, in screen
    coords) to ``menu``, the way its live mouse grab would while it is open."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    ev = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(0, 0),
        global_pt,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    menu.mouseMoveEvent(ev)


def _shown_bar_menu():
    """A menu button on a bar with its menu open — the starting state for the
    stays-open and hover-switch tests. The bar is positioned but not shown
    (child mapToGlobal works without showing); only the menu is shown."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QWidget

    from starpost.gui.widgets import BarMenu, BarMenuButton

    bar = QWidget()
    bar.setGeometry(QRect(0, 0, 400, 30))
    btn = BarMenuButton(bar)
    btn.setGeometry(QRect(0, 0, 80, 30))
    menu = BarMenu(btn, owner=btn, sibling_bar=bar)
    menu.addAction("A")
    menu.setGeometry(QRect(200, 200, 120, 60))
    menu.show()
    return bar, btn, menu


def _other_menu_button(bar):
    """A second menu button on ``bar`` — a hover-switch handoff target."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QMenu

    from starpost.gui.widgets import BarMenuButton

    other = BarMenuButton(bar)
    other.setGeometry(QRect(100, 0, 80, 30))
    other_menu = QMenu(other)
    other_menu.addAction("B")
    other.setMenu(other_menu)
    return other


def test_bar_menu_stays_open_when_pointer_strays_far(app):
    """Moving the pointer far away leaves the menu open — it only dismisses on
    a click (native popup behaviour); there is no distance-based auto-close."""
    from PySide6.QtCore import QPointF

    bar, btn, menu = _shown_bar_menu()  # noqa: F841 (keep btn alive)
    _move_to(menu, QPointF(5000, 5000))
    assert menu.isVisible()
    bar.deleteLater()


def test_bar_menu_stays_open_over_sibling_bar(app):
    """The pointer crossing the bar's empty area (or its non-menu items) keeps
    the menu open — only another *menu* button is a handoff target."""
    from PySide6.QtCore import QPointF

    bar, btn, menu = _shown_bar_menu()  # noqa: F841 (keep btn alive)
    _move_to(menu, QPointF(300, 15))  # on the bar, away from any menu button
    assert menu.isVisible()
    bar.deleteLater()


def test_bar_menu_hands_off_to_other_menu_button(app, monkeypatch):
    """With a menu open, hovering a different menu button on the bar closes
    this menu and opens that button's menu without a click."""
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    bar, btn, menu = _shown_bar_menu()  # noqa: F841 (keep btn alive)
    other = _other_menu_button(bar)
    calls = []
    monkeypatch.setattr(other, "showMenu", lambda: calls.append(1))

    _move_to(menu, QPointF(140, 15))  # inside `other`
    assert not menu.isVisible()
    QApplication.processEvents()  # fire the deferred (singleShot) showMenu
    assert calls == [1]
    bar.deleteLater()


def test_bar_menu_handoff_skips_disabled_button(app, monkeypatch):
    """A disabled menu button (e.g. during a running batch) is not a handoff
    target — the open menu stays open and the disabled menu stays shut."""
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    bar, btn, menu = _shown_bar_menu()  # noqa: F841 (keep btn alive)
    other = _other_menu_button(bar)
    other.setEnabled(False)
    calls = []
    monkeypatch.setattr(other, "showMenu", lambda: calls.append(1))

    _move_to(menu, QPointF(140, 15))
    assert menu.isVisible()
    QApplication.processEvents()
    assert calls == []
    bar.deleteLater()


def test_bar_menu_button_hover_does_not_open(app, monkeypatch):
    """Hovering a menu button never opens its closed menu — opening is
    click-only (the button's InstantPopup mode, handled natively by Qt)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtWidgets import QMenu

    from starpost.gui.widgets import BarMenuButton

    btn = BarMenuButton()
    menu = QMenu(btn)
    menu.addAction("A")
    btn.setMenu(menu)
    calls = []
    monkeypatch.setattr(btn, "showMenu", lambda: calls.append(1))
    btn.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    assert calls == []
    btn.deleteLater()


def test_bar_menu_hide_clears_owner_stuck_hover(app, monkeypatch):
    """Closing the menu (any path: outside click, Esc, handoff) drops the owner
    button's leftover hover outline once the pointer has moved elsewhere — the
    menu's mouse grab swallowed the button's leave event."""
    from PySide6.QtCore import QPoint, Qt

    import starpost.gui.widgets as widgets

    bar, btn, menu = _shown_bar_menu()
    btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    monkeypatch.setattr(widgets.QCursor, "pos", staticmethod(lambda: QPoint(10000, 10000)))
    menu.hide()
    assert btn.testAttribute(Qt.WidgetAttribute.WA_UnderMouse) is False
    bar.deleteLater()


def test_enable_range_selection_sets_extended(app):
    """enable_range_selection turns a default (single-select) list into an
    extended-selection one, so Shift/Ctrl+click select multiple items."""
    from PySide6.QtWidgets import QAbstractItemView, QListWidget

    from starpost.gui.widgets import enable_range_selection

    lst = QListWidget()
    assert lst.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    enable_range_selection(lst)
    assert lst.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    lst.deleteLater()


def test_enable_range_selection_leaves_checkbox_lists_alone(app):
    """Checkbox-driven lists use NoSelection; the helper must not enable
    selection on them."""
    from PySide6.QtWidgets import QAbstractItemView, QListWidget

    from starpost.gui.widgets import enable_range_selection

    lst = QListWidget()
    lst.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    enable_range_selection(lst)
    assert lst.selectionMode() == QAbstractItemView.SelectionMode.NoSelection
    lst.deleteLater()
