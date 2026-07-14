"""Tests for the glyph icons on the toolbar dropdown menu entries."""
import pytest

import starpost.utils.paths as paths
from starpost.core.settings import Settings


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    """Point per-user config/cache at a temp dir so tests touch no real files."""
    monkeypatch.setattr(
        paths.platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path / "config")
    )
    monkeypatch.setattr(
        paths.platformdirs, "user_cache_dir", lambda *a, **k: str(tmp_path / "cache")
    )


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _opaque_pixels(pixmap) -> int:
    img = pixmap.toImage()
    return sum(
        1
        for x in range(img.width())
        for y in range(img.height())
        if img.pixelColor(x, y).alpha() > 0
    )


def test_menu_icon_draws_every_kind(app):
    """Every registered glyph kind renders visible (non-transparent) pixels."""
    from PySide6.QtCore import QSize

    from starpost.gui.icons import MENU_ICON_KINDS, menu_icon

    assert MENU_ICON_KINDS  # the registry is not empty
    for kind in MENU_ICON_KINDS:
        icon = menu_icon(kind, "#cfcfcf")
        assert not icon.isNull(), kind
        assert _opaque_pixels(icon.pixmap(QSize(16, 16))) > 0, kind


def test_menu_icon_unknown_kind_raises(app):
    from starpost.gui.icons import menu_icon

    with pytest.raises(KeyError):
        menu_icon("no-such-glyph", "#cfcfcf")


def test_menu_icon_tint_and_active_colour(app):
    """The glyph follows the requested colour, and the Active-mode pixmap (drawn
    on the accent-highlighted row) uses the separate active colour."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon

    from starpost.gui.icons import menu_icon

    size = QSize(16, 16)
    light = menu_icon("import", "#cfcfcf")
    dark = menu_icon("import", "#3a3a3a")
    assert light.pixmap(size).toImage() != dark.pixmap(size).toImage()

    two_tone = menu_icon("import", "#cfcfcf", active_color="#000000")
    assert (
        two_tone.pixmap(size, QIcon.Mode.Active).toImage()
        != two_tone.pixmap(size, QIcon.Mode.Normal).toImage()
    )


def test_file_and_run_batch_menu_entries_have_icons(app):
    """Every entry in the File dropdown (including the Add submenu and its
    children) and the Run batch dropdown carries an icon."""
    import starpost.gui.main_window as mw

    win = mw.MainWindow(Settings())
    menus = [win._file_menu, win._run_button.menu()]
    seen = 0
    while menus:
        menu = menus.pop()
        for act in menu.actions():
            if act.isSeparator():
                continue
            if act.menu() is not None:
                menus.append(act.menu())
            assert not act.icon().isNull(), act.text()
            seen += 1
    assert seen >= 7  # Add, Files…, Folder…, Import, Export, Full, Express
    win.close()


def test_menu_icons_follow_theme_mode(app):
    """Saving settings with a different theme mode re-tints the menu glyphs
    (dark mode's light-grey glyph would be invisible on the light theme)."""
    from PySide6.QtCore import QSize

    import starpost.gui.main_window as mw

    win = mw.MainWindow(Settings())
    act = next(a for a in win._file_menu.actions() if not a.isSeparator())
    before = act.icon().pixmap(QSize(16, 16)).toImage()
    win.settings.appearance.mode = (
        "light" if win.settings.appearance.mode == "dark" else "dark"
    )
    win._apply_settings_to_views()
    after = act.icon().pixmap(QSize(16, 16)).toImage()
    assert before != after
    win.close()
