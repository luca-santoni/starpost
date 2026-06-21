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
