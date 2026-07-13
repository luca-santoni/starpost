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


def test_batch_shortcuts_trigger_and_display(app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    import starpost.gui.main_window as mw

    calls = []
    # Patch on the class BEFORE construction: the menu binds the bound methods
    # at addAction time.
    monkeypatch.setattr(mw.MainWindow, "_run_batch", lambda self: calls.append("full"))
    monkeypatch.setattr(
        mw.MainWindow, "_run_express_batch", lambda self: calls.append("express")
    )
    win = _make_window()
    try:
        QTest.keyClick(win, Qt.Key_B, Qt.ControlModifier | Qt.ShiftModifier)
        QTest.keyClick(win, Qt.Key_E, Qt.ControlModifier | Qt.ShiftModifier)
        assert calls == ["full", "express"]
        # The menu entries display the keys (rendered right-aligned by Qt).
        texts = {
            a.text(): a.shortcut().toString()
            for a in win._run_button.menu().actions()
        }
        assert texts["Full Batch"] == "Ctrl+Shift+B"
        assert texts["Express batch"] == "Ctrl+Shift+E"
    finally:
        win.close()


def test_selection_panel_click_methods(app):
    """click_select_all / click_clear_selection / click_run press the buttons of
    whichever section is active; click_run is a no-op off Scenes/Screenplays."""
    from starpost.gui.views.selection_panel import SelectionPanel

    panel = SelectionPanel()
    changed = []
    panel.selection_changed.connect(lambda: changed.append("sel"))
    runs = []
    panel.run_scenes_requested.connect(lambda: runs.append("scenes"))
    panel.record_screenplays_requested.connect(lambda: runs.append("screenplays"))

    panel.set_active_section("reports")
    panel.click_select_all()
    panel.click_clear_selection()
    assert changed == ["sel", "sel"]  # empty list, but the buttons still emit
    panel.click_run()
    assert runs == []  # Reports has no Run button

    panel.set_active_section("scenes")
    panel.click_run()
    panel.set_active_section("screenplays")
    panel.click_run()
    assert runs == ["scenes", "screenplays"]
    panel.close()


def test_run_shortcut_contextual(app, monkeypatch):
    """Ctrl+R triggers Run on the Scenes tab, Record on Screenplays, nothing on
    Reports; Ctrl+Shift+A/D reach the active panel's buttons."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    import starpost.gui.main_window as mw

    # The real handlers pop modal "select a scene first" dialogs; patch them
    # out so the signal spies below observe the shortcut without blocking.
    monkeypatch.setattr(mw.MainWindow, "_run_scenes", lambda self: None)
    monkeypatch.setattr(mw.MainWindow, "_record_screenplays", lambda self: None)

    win = _make_window()
    try:
        runs = []
        win.selection.run_scenes_requested.connect(lambda: runs.append("scenes"))
        win.selection.record_screenplays_requested.connect(
            lambda: runs.append("screenplays")
        )
        QTest.keyClick(win, Qt.Key_R, Qt.ControlModifier)  # Reports tab: no-op
        assert runs == []

        win._center_tabs.setCurrentIndex(2)  # Scenes
        QApplication.processEvents()
        QTest.keyClick(win, Qt.Key_R, Qt.ControlModifier)
        win._center_tabs.setCurrentIndex(3)  # Screenplays
        QApplication.processEvents()
        QTest.keyClick(win, Qt.Key_R, Qt.ControlModifier)
        assert runs == ["scenes", "screenplays"]

        changed = []
        win.selection.selection_changed.connect(lambda: changed.append(1))
        win._center_tabs.setCurrentIndex(0)  # Reports
        QApplication.processEvents()
        QTest.keyClick(win, Qt.Key_A, Qt.ControlModifier | Qt.ShiftModifier)
        QTest.keyClick(win, Qt.Key_D, Qt.ControlModifier | Qt.ShiftModifier)
        assert len(changed) == 2
    finally:
        win.close()


def test_selection_tooltips_show_keys(app):
    from starpost.gui.views.selection_panel import SelectionPanel

    panel = SelectionPanel()
    assert "(Ctrl+Shift+A)" in panel._section_buttons["reports"]["select_all"].toolTip()
    assert "(Ctrl+Shift+D)" in panel._section_buttons["reports"]["clear"].toolTip()
    assert "(Ctrl+R)" in panel._section_buttons["scenes"]["run"].toolTip()
    assert "(Ctrl+R)" in panel._section_buttons["screenplays"]["run"].toolTip()
    panel.close()


def test_smooth_shortcut_only_on_plots_tab(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    win = _make_window()
    try:
        pv = win.plot_view  # force the lazy build
        assert not pv._smooth_check.isChecked()
        QTest.keyClick(win, Qt.Key_S, Qt.AltModifier | Qt.ShiftModifier)
        assert not pv._smooth_check.isChecked()  # Reports tab: no-op

        win._center_tabs.setCurrentIndex(1)  # Plots
        QApplication.processEvents()
        QTest.keyClick(win, Qt.Key_S, Qt.AltModifier | Qt.ShiftModifier)
        assert pv._smooth_check.isChecked()
        QTest.keyClick(win, Qt.Key_S, Qt.AltModifier | Qt.ShiftModifier)
        assert not pv._smooth_check.isChecked()
        assert "(Alt+Shift+S)" in pv._smooth_check.toolTip()
    finally:
        win.close()
