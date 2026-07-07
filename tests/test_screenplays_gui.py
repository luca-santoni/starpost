"""GUI tests for the Screenplays tab widgets (offscreen)."""
import pytest

import starpost.utils.paths as paths


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    """Point per-user config/cache at a temp dir so tests touch no real files."""
    monkeypatch.setattr(
        paths.platformdirs, "user_config_dir",
        lambda *a, **k: str(tmp_path / "config"),
    )
    monkeypatch.setattr(
        paths.platformdirs, "user_cache_dir",
        lambda *a, **k: str(tmp_path / "cache"),
    )


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_screenplay_tree_reveal_and_accessors(app):
    from PySide6.QtCore import Qt

    from starpost.gui.views.selection_panel import SelectionPanel

    panel = SelectionPanel()
    panel.set_available_screenplays(
        {"Flyby": ["Scalar velocity", "Vector 1"], "Intro": []}
    )
    tree = panel.screenplays
    root = tree.invisibleRootItem()
    flyby = next(
        root.child(i)
        for i in range(root.childCount())
        if root.child(i).text(0) == "Flyby"
    )
    # Checking a screenplay reveals its displayers unchecked.
    flyby.setCheckState(0, Qt.Checked)
    assert panel.selected_screenplays() == {"Flyby"}
    assert panel.selected_screenplay_displayers() == {"Flyby": []}
    flyby.child(0).setCheckState(0, Qt.Checked)
    assert panel.selected_screenplay_displayers() == {
        "Flyby": [flyby.child(0).text(0)]
    }


def test_screenplays_section_visibility(app):
    from starpost.gui.views.selection_panel import SelectionPanel

    panel = SelectionPanel()
    panel.set_active_section("screenplays")
    assert panel._screenplays_group.isVisibleTo(panel)
    assert panel._saved_views_group.isVisibleTo(panel)
    assert not panel._scenes_group.isVisibleTo(panel)
    assert not panel._reports_group.isVisibleTo(panel)
    assert not panel._plots_group.isVisibleTo(panel)
    panel.set_active_section("scenes")
    assert not panel._screenplays_group.isVisibleTo(panel)
    assert panel._scenes_group.isVisibleTo(panel)
    assert panel._saved_views_group.isVisibleTo(panel)


def test_record_and_clear_buttons_emit_signals(app):
    from PySide6.QtWidgets import QPushButton

    from starpost.gui.views.selection_panel import SelectionPanel

    panel = SelectionPanel()
    got = []
    panel.record_screenplays_requested.connect(lambda: got.append("record"))
    panel.clear_screenplays_requested.connect(lambda: got.append("clear"))
    buttons = panel._screenplays_group.findChildren(QPushButton)
    next(b for b in buttons if b.text() == "Record").click()
    next(b for b in buttons if b.text() == "Clear screenplays").click()
    assert got == ["record", "clear"]
