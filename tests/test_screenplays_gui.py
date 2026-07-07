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


def _png(tmp_path, name="poster.png"):
    """A tiny real PNG on disk (galleries decode from disk)."""
    from PySide6.QtGui import QImage

    p = tmp_path / name
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(0xFF336699)
    img.save(str(p))
    return p


def test_thumbnail_cache_decodes_and_misses(app, tmp_path):
    from starpost.gui.views.thumbnails import ThumbnailCache

    cache = ThumbnailCache(64)
    png = _png(tmp_path)
    assert cache.icon(str(png)) is not None
    assert cache.icon(str(tmp_path / "missing.png")) is None


def test_screenplay_view_shows_movie_tiles(app, tmp_path):
    from starpost.data.models import MediaArtifact
    from starpost.gui.views.screenplay_view import ScreenplayView

    poster = _png(tmp_path)
    movie = tmp_path / "a-Flyby.mp4"
    movie.write_bytes(b"stub")
    view = ScreenplayView()
    view.show_media([
        MediaArtifact(name="Flyby", path=str(movie), source="Flyby",
                      kind="movie", poster=str(poster)),
        MediaArtifact(name="Broken", path="", source="Broken", kind="movie",
                      error="ERROR"),
        MediaArtifact(name="Gone", path=str(tmp_path / "gone.mp4"),
                      source="Gone", kind="movie"),
        # Stills are the Scenes gallery's business — ignored here.
        MediaArtifact(name="Still", path=str(poster), source="S",
                      kind="still"),
    ])
    gallery = view._gallery
    labels = [gallery.item(i).text() for i in range(gallery.count())]
    assert labels == ["Flyby", "Broken\n(record failed)", "Gone\n(file missing)"]
    assert not gallery.item(0).icon().isNull()


def test_screenplay_view_empty_shows_hint(app):
    from starpost.gui.views.screenplay_view import ScreenplayView

    view = ScreenplayView()
    view.show_media([])
    assert view._stack.currentWidget() is view._hint


def test_main_window_has_screenplays_tab(app):
    import starpost.gui.main_window as mw
    from starpost.core.settings import Settings

    win = mw.MainWindow(Settings())
    tabs = win._center_tabs
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert labels == ["Reports", "Plots", "Scenes", "Screenplays"]
    win.close()


def test_clear_scenes_keeps_movies_and_vice_versa(app, monkeypatch, tmp_path):
    import starpost.gui.main_window as mw
    from starpost.core.settings import Settings
    from starpost.data.models import MediaArtifact, SimResult

    win = mw.MainWindow(Settings())
    res = SimResult(sim_path=str(tmp_path / "a.sim"))
    res.media = [
        MediaArtifact(name="s", path="", source="S", kind="still"),
        MediaArtifact(name="m", path="", source="P", kind="movie"),
    ]
    win.store.put(res)
    monkeypatch.setattr(
        mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.Yes
    )
    win._clear_scenes()
    assert [m.kind for m in win.store.get(res.sim_path).media] == ["movie"]
    win._clear_screenplays()
    assert win.store.get(res.sim_path).media == []
    win.close()


def test_record_screenplays_requires_selection(app, monkeypatch):
    import starpost.gui.main_window as mw
    from starpost.core.settings import Settings

    win = mw.MainWindow(Settings(starccm_path="/bin/true"))
    infos = []
    monkeypatch.setattr(
        mw.QMessageBox, "information", lambda *a, **k: infos.append(a[2])
    )
    win._record_screenplays()
    assert infos and "screenplay" in infos[0].lower()
    win.close()
