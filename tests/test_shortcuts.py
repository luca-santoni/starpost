"""Keyboard-shortcut tests: the central table, app-wide keys, and per-widget keys."""
import pytest

import starpost.utils.paths as paths
from starpost.gui import shortcuts


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


def test_key_and_hint():
    assert shortcuts.key("tab_reports") == "F1"
    assert shortcuts.hint("Switch to Reports", "tab_reports") == "Switch to Reports (F1)"


def test_expected_bindings():
    """The bindings agreed in the spec, verbatim."""
    expected = {
        "tab_files": "1",
        "tab_data": "2",
        "tab_reports": "F1",
        "tab_plots": "F2",
        "tab_scenes": "F3",
        "tab_screenplays": "F4",
        "batch_full": "Ctrl+Shift+B",
        "batch_express": "Ctrl+Shift+E",
        "select_all": "Ctrl+Shift+A",
        "clear_selection": "Ctrl+Shift+D",
        "run_render": "Ctrl+R",
        "smooth": "Alt+Shift+S",
        "file_load": "Ctrl+L",
        "file_props": "Ctrl+P",
        "file_remove": "Delete",
    }
    assert {sid: shortcuts.key(sid) for sid in expected} == expected


def test_no_duplicate_keys():
    """App-wide keys must be unique among themselves; the file-list keys (their
    own focus scope) must be unique among themselves."""
    file_ids = {"file_load", "file_props", "file_remove"}
    appwide = [k for sid, (k, _) in shortcuts.SHORTCUTS.items() if sid not in file_ids]
    filekeys = [k for sid, (k, _) in shortcuts.SHORTCUTS.items() if sid in file_ids]
    assert len(appwide) == len(set(appwide))
    assert len(filekeys) == len(set(filekeys))


def _make_window():
    """A shown, active MainWindow with the scenes/screenplays warning dialog off
    (it's modal and would hang a test that switches to those tabs)."""
    import starpost.gui.main_window as mw
    from PySide6.QtWidgets import QApplication
    from starpost.core.settings import Settings

    s = Settings()
    s.show_scenes_warning = False
    win = mw.MainWindow(s)
    win.show()
    win.activateWindow()
    QApplication.processEvents()
    return win


def test_tab_keys_switch_tabs(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    win = _make_window()
    try:
        for qtkey, index in (
            (Qt.Key_F2, 1), (Qt.Key_F3, 2), (Qt.Key_F4, 3), (Qt.Key_F1, 0),
        ):
            QTest.keyClick(win, qtkey)
            assert win._center_tabs.currentIndex() == index
        QTest.keyClick(win, Qt.Key_2)
        assert win._left_tabs.currentIndex() == 1
        QTest.keyClick(win, Qt.Key_1)
        assert win._left_tabs.currentIndex() == 0
    finally:
        win.close()


def test_tab_tooltips_show_keys(app):
    win = _make_window()
    try:
        for i, key_text in enumerate(("(F1)", "(F2)", "(F3)", "(F4)")):
            assert key_text in win._center_tabs.tabToolTip(i)
        assert "(1)" in win._left_tabs.tabToolTip(0)
        assert "(2)" in win._left_tabs.tabToolTip(1)
    finally:
        win.close()
