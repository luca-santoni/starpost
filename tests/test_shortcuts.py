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
    assert shortcuts.key("tab_reports") == "1"
    assert shortcuts.hint("Switch to Reports", "tab_reports") == "Switch to Reports (1)"


def test_hotkey_doc_lists_every_binding():
    """docs/starpost_hotkeys.txt is the user-facing hotkey list; it must name
    every key in the table. Each binding appears as the final token of a line
    (e.g. "Reports tab             1"), so a new or changed binding fails here
    until the doc is updated."""
    from pathlib import Path

    doc = Path(__file__).parent.parent / "docs" / "starpost_hotkeys.txt"
    last_tokens = {
        line.split()[-1] for line in doc.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    missing = {
        key_seq for key_seq, _label in shortcuts.SHORTCUTS.values()
        if key_seq not in last_tokens
    }
    assert not missing, f"docs/starpost_hotkeys.txt is missing bindings: {sorted(missing)}"


def test_menu_label_pads_for_shortcut_column():
    padded = shortcuts.menu_label("Load file")
    assert padded.rstrip() == "Load file"
    assert padded != "Load file"  # trailing gap widens the shortcut column


def test_expected_bindings():
    """The bindings agreed in the spec, verbatim."""
    expected = {
        "tab_files": "F1",
        "tab_data": "F2",
        "tab_reports": "1",
        "tab_plots": "2",
        "tab_scenes": "3",
        "tab_screenplays": "4",
        "batch_full": "Ctrl+Shift+B",
        "batch_express": "Ctrl+Shift+E",
        "add_files": "Ctrl+N",
        "add_folder": "Ctrl+Shift+N",
        "import_data": "Alt+Shift+I",
        "export_data": "Alt+Shift+E",
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
    """Every key in the table must be globally unique: a file-list key that
    equalled an app-wide key would be ambiguous (and dead) with the tree
    focused, since both shortcut contexts would match."""
    keys = [k for (k, _label) in shortcuts.SHORTCUTS.values()]
    assert len(keys) == len(set(keys))


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
            (Qt.Key_2, 1), (Qt.Key_3, 2), (Qt.Key_4, 3), (Qt.Key_1, 0),
        ):
            QTest.keyClick(win, qtkey)
            assert win._center_tabs.currentIndex() == index
        QTest.keyClick(win, Qt.Key_F2)
        assert win._left_tabs.currentIndex() == 1
        QTest.keyClick(win, Qt.Key_F1)
        assert win._left_tabs.currentIndex() == 0
    finally:
        win.close()


def test_tab_tooltips_show_keys(app):
    win = _make_window()
    try:
        for i, key_text in enumerate(("(1)", "(2)", "(3)", "(4)")):
            assert key_text in win._center_tabs.tabToolTip(i)
        assert "(F1)" in win._left_tabs.tabToolTip(0)
        assert "(F2)" in win._left_tabs.tabToolTip(1)
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
        # The menu entries display the keys (rendered right-aligned by Qt);
        # labels carry menu_label's gap padding so the columns aren't cramped.
        texts = {
            a.text().rstrip(): a.shortcut().toString()
            for a in win._run_button.menu().actions()
        }
        assert texts["Full Batch"] == "Ctrl+Shift+B"
        assert texts["Express batch"] == "Ctrl+Shift+E"
        assert all(a.text().endswith(" ") for a in win._run_button.menu().actions())
    finally:
        win.close()


def test_add_files_folder_shortcuts_trigger_and_display(app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    import starpost.gui.views.file_list as fl

    calls = []
    # Patch on the class BEFORE construction: the File menu binds the panel's
    # bound methods at addAction time (and the real slots open modal dialogs).
    monkeypatch.setattr(
        fl.FileListPanel, "add_files_dialog", lambda self: calls.append("files")
    )
    monkeypatch.setattr(
        fl.FileListPanel, "add_folder_dialog", lambda self: calls.append("folder")
    )
    win = _make_window()
    try:
        QTest.keyClick(win, Qt.Key_N, Qt.ControlModifier)
        QTest.keyClick(win, Qt.Key_N, Qt.ControlModifier | Qt.ShiftModifier)
        assert calls == ["files", "folder"]
        # The Add submenu (first File-menu entry) displays the keys.
        add_menu = win._file_menu.actions()[0].menu()
        texts = {a.text().rstrip(): a.shortcut().toString() for a in add_menu.actions()}
        assert texts["Files…"] == "Ctrl+N"
        assert texts["Folder…"] == "Ctrl+Shift+N"
    finally:
        win.close()


def test_import_export_shortcuts_trigger_and_display(app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    import starpost.gui.main_window as mw

    calls = []
    # Patch on the class BEFORE construction: the File menu binds the bound
    # methods at addAction time (and the real slots open modal dialogs).
    monkeypatch.setattr(mw.MainWindow, "_import_data", lambda self: calls.append("import"))
    monkeypatch.setattr(mw.MainWindow, "_export_data", lambda self: calls.append("export"))
    win = _make_window()
    try:
        QTest.keyClick(win, Qt.Key_I, Qt.AltModifier | Qt.ShiftModifier)
        QTest.keyClick(win, Qt.Key_E, Qt.AltModifier | Qt.ShiftModifier)
        assert calls == ["import", "export"]
        texts = {
            a.text().rstrip(): a.shortcut().toString()
            for a in win._file_menu.actions()
        }
        assert texts["Import data…"] == "Alt+Shift+I"
        assert texts["Export data…"] == "Alt+Shift+E"
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


@pytest.fixture()
def file_panel(app, tmp_path):
    """A shown FileListPanel holding two fake .sim files, first one selected."""
    from PySide6.QtWidgets import QApplication
    from starpost.gui.views.file_list import FileListPanel

    sims = []
    for name in ("a.sim", "b.sim"):
        p = tmp_path / name
        p.write_bytes(b"")
        sims.append(p)
    panel = FileListPanel()
    panel._add_paths(sims)
    panel.show()
    panel.activateWindow()
    panel._tree.setFocus()
    QApplication.processEvents()
    item = panel._tree.topLevelItem(0)
    panel._tree.setCurrentItem(item)
    item.setSelected(True)
    yield panel
    panel.close()


def test_file_list_ctrl_l_loads_selected(file_panel):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    opened = []
    file_panel.open_requested.connect(opened.extend)
    QTest.keyClick(file_panel._tree, Qt.Key_L, Qt.ControlModifier)
    assert [p.name for p in opened] == ["a.sim"]


def test_file_list_ctrl_p_properties(file_panel):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    props = []
    file_panel.properties_requested.connect(props.append)
    QTest.keyClick(file_panel._tree, Qt.Key_P, Qt.ControlModifier)
    assert len(props) == 1 and str(props[0]).endswith("a.sim")


def test_file_list_delete_confirms_then_removes(file_panel, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    import starpost.gui.views.file_list as fl

    answers = iter([QMessageBox.No, QMessageBox.Yes])
    monkeypatch.setattr(
        fl.QMessageBox, "question", lambda *a, **k: next(answers)
    )
    QTest.keyClick(file_panel._tree, Qt.Key_Delete)  # answered No
    assert len(file_panel.files()) == 2
    QTest.keyClick(file_panel._tree, Qt.Key_Delete)  # answered Yes
    assert [p.name for p in file_panel.files()] == ["b.sim"]
