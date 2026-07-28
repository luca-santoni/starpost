"""Tests for the generated application stylesheet (theme.build_stylesheet)."""
import re

import pytest

import starpost.utils.paths as paths
from starpost.gui.theme import build_stylesheet


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path):
    """Send the generated checkmark icon to a temp cache dir, not the real one."""
    monkeypatch.setattr(
        paths.platformdirs, "user_cache_dir", lambda *a, **k: str(tmp_path / "cache")
    )


@pytest.fixture(scope="module")
def app():
    # build_stylesheet renders the checkmark icon (a QPixmap), so it needs a
    # running QApplication.
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _rule_body(qss: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", qss)
    assert m is not None, f"no rule for {selector!r}"
    return m.group(1)


def test_item_views_disable_focus_outline(app):
    """List/tree/table views drop the focus rectangle so a row doesn't keep a
    faint outline after its selection is cleared (clicking empty space)."""
    body = _rule_body(
        build_stylesheet("dark", "#ffc829"),
        "QListWidget, QTableView, QTableWidget, QTreeView",
    )
    assert re.search(r"outline:\s*0", body)


def test_highlighted_menu_checkmark_uses_a_distinct_glyph(app):
    """A highlighted (accent-background) menu item gets a contrast-colour
    checkmark so it stays visible instead of blending into the accent."""
    qss = build_stylesheet("dark", "#ffc829")
    normal = _rule_body(qss, "QMenu::indicator:checked")
    selected = _rule_body(qss, "QMenu::indicator:checked:selected")
    # Both reference a checkmark image, but different ones (accent vs contrast).
    assert "image: url(" in normal and "image: url(" in selected
    assert normal != selected


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_disabled_labels_and_spin_boxes_read_as_disabled(app, mode):
    """A widget switched off with setEnabled(False) has to *look* off.

    Two rules stand between intent and pixels here. `QLabel { color: $text }`
    is unconditional, so it paints disabled labels at full brightness unless
    a :disabled rule overrides it — which is why a greyed form label (the
    Convergence window's custom tolerance, the license-mode rows in Settings
    and Welcome) rendered identically to a live one. Spin boxes carry no
    stylesheet of their own, and the palette's disabled group does not reach
    their text, so the same held for a disabled QDoubleSpinBox."""
    qss = build_stylesheet(mode, "#ffc829")
    disabled_text = _rule_body(qss, "QComboBox:disabled, QLineEdit:disabled")
    colour = re.search(r"color:\s*(#[0-9a-fA-F]{3,8})", disabled_text).group(1)
    # Both fade to the same disabled colour the combos and line edits use, so
    # a form row greys uniformly rather than in two different shades.
    assert f"color: {colour}" in _rule_body(qss, "QLabel:disabled")
    assert f"color: {colour}" in _rule_body(qss, "QAbstractSpinBox:disabled")
    # ...and that colour is genuinely distinct from the enabled one, or the
    # rules would be decoration.
    assert f"color: {colour}" not in _rule_body(qss, "QLabel")


def test_disabled_spin_boxes_are_coloured_only(app):
    """Giving QAbstractSpinBox a border or background in the stylesheet
    switches the whole widget to stylesheet drawing and costs it the native
    up/down arrows, so the disabled rule sets colour and nothing else."""
    body = _rule_body(build_stylesheet("dark", "#ffc829"), "QAbstractSpinBox:disabled")
    assert "border" not in body
    assert "background" not in body


def test_danger_menu_item_is_red_and_inverts_on_hover(app):
    """The destructive context-menu entry (the tabs' Clear) is styled red like
    the danger buttons, and hovering inverts it: the red becomes the fill and
    the text goes white — its own version of the other items' accent
    highlight."""
    qss = build_stylesheet("dark", "#ffc829")
    body = _rule_body(qss, "QLabel#dangerMenuItem")
    assert "color: #e5484d" in body
    hover = _rule_body(qss, "QLabel#dangerMenuItem:hover")
    assert "background: #e5484d" in hover
    assert "color: #ffffff" in hover
