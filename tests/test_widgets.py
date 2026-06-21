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


def test_other_style_hints_delegate_unchanged(app):
    """Only the fall-asleep delay is overridden; everything else (including the
    wake-up delay and unrelated hints) is delegated to the base style so the
    app's appearance is untouched."""
    style = ToolTipResetStyle()
    base = QProxyStyle()
    for hint in (
        QStyle.StyleHint.SH_ToolTip_WakeUpDelay,
        QStyle.StyleHint.SH_ComboBox_Popup,
        QStyle.StyleHint.SH_Slider_SnapToValue,
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
