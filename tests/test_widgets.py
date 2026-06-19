import pytest
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle

from starpost.gui.widgets import ToolTipResetStyle


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


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
