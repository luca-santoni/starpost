"""Tests for MainWindow behaviours that don't need a real STAR-CCM+ run."""
import pytest

import starpost.gui.main_window as mw
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


def test_run_batch_opens_dialog(app, monkeypatch):
    """Run batch opens the tabbed batch-run dialog (no folder prompt)."""
    import starpost.gui.views.batch_run_dialog as brd

    win = mw.MainWindow(Settings())
    opened = []
    monkeypatch.setattr(
        brd.BatchRunDialog, "exec", lambda self: opened.append(self) or 0
    )
    win._run_batch()
    assert len(opened) == 1 and isinstance(opened[0], brd.BatchRunDialog)
    win.close()


def test_batch_run_dialog_sequential_navigation(app):
    """Five sequential tabs; Continue advances; the button becomes Batch run on
    the Summary tab and accepts there."""
    from PySide6.QtWidgets import QDialog

    from starpost.gui.views.batch_run_dialog import BatchRunDialog

    # Leaving the Source tab requires a selected source; a loaded data set
    # provides one. ("Has similar format" is disabled in data mode, so advancing
    # triggers no extraction.)
    dlg = BatchRunDialog(data_sets=["case"])
    dlg._source_panel._source_input.setCurrentIndex(
        dlg._source_panel._source_input.findData("data")
    )
    tabs = dlg._tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Source", "Reports", "Plots", "Scenes", "Summary"
    ]
    assert dlg._next.text() == "Continue"
    for expected in range(1, tabs.count()):
        dlg._advance()
        assert tabs.currentIndex() == expected
    assert dlg._next.text() == "Batch run"  # on the Summary tab
    # Back steps to the previous tab; it's disabled only on the first tab.
    assert dlg._back.isEnabled()
    dlg._retreat()
    assert tabs.currentIndex() == tabs.count() - 2 and dlg._next.text() == "Continue"
    while tabs.currentIndex() > 0:
        dlg._retreat()
    assert tabs.currentIndex() == 0 and not dlg._back.isEnabled()
    # From Summary, the primary button runs the batch (covered separately); stub
    # it to the dialog's accept so this test just checks Summary's advance fires
    # the terminal action.
    dlg._run_batch = dlg.accept
    tabs.setCurrentIndex(tabs.count() - 1)
    dlg._advance()
    assert dlg.result() == QDialog.DialogCode.Accepted
    dlg.close()


def test_batch_run_dialog_tabs_not_mouse_clickable(app):
    """Clicking a tab with the mouse does not change the active tab — only the
    Continue button advances."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent

    from starpost.gui.views.batch_run_dialog import BatchRunDialog

    dlg = BatchRunDialog()
    bar = dlg._tabs.tabBar()
    target = bar.tabRect(3).center()  # the "Scenes" tab
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, target, bar.mapToGlobal(target),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    bar.mousePressEvent(press)
    assert dlg._tabs.currentIndex() == 0  # unchanged by the click
    dlg.close()


def test_batch_run_dialog_source_window(app):
    """Source tab: '.sim files' leaves the right window blank; 'Loaded data sets'
    fills it with a checkable item per loaded data set."""
    from PySide6.QtCore import Qt

    from starpost.gui.views.batch_run_dialog import BatchRunDialog

    dlg = BatchRunDialog(data_sets=["caseA", "caseB"])
    win = dlg._source_panel._source_window
    assert (
        dlg._source_panel._source_input.currentData() == "sim" and win.count() == 0
    )  # blank

    dlg._source_panel._source_input.setCurrentIndex(
        dlg._source_panel._source_input.findData("data")
    )
    assert [win.item(i).text() for i in range(win.count())] == ["caseA", "caseB"]
    assert all(
        win.item(i).flags() & Qt.ItemFlag.ItemIsUserCheckable
        and win.item(i).checkState() == Qt.CheckState.Checked
        for i in range(win.count())
    )

    dlg._source_panel._source_input.setCurrentIndex(
        dlg._source_panel._source_input.findData("sim")
    )
    assert win.count() == 0  # back to blank
    dlg.close()


def test_batch_run_dialog_source_buttons(app, monkeypatch):
    """Load File/Load Data Set toggle with the source mode and add entries;
    Select All / Clear flip the window's checkboxes."""
    from PySide6.QtCore import Qt

    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog(data_sets=["caseA"])
    panel = dlg._source_panel
    win = panel._source_window
    # .sim mode: Load File shown, Load Data Set hidden
    assert not panel._load_file_btn.isHidden() and panel._load_dataset_btn.isHidden()
    monkeypatch.setattr(
        brd.QFileDialog, "getOpenFileNames",
        lambda *a, **k: (["/cases/a.sim", "/cases/b.sim"], ""),
    )
    panel._load_files()
    assert [win.item(i).text() for i in range(win.count())] == ["a.sim", "b.sim"]

    # data mode: Load Data Set shown, Load File hidden
    panel._source_input.setCurrentIndex(panel._source_input.findData("data"))
    assert panel._load_file_btn.isHidden() and not panel._load_dataset_btn.isHidden()
    monkeypatch.setattr(
        brd.QFileDialog, "getOpenFileNames", lambda *a, **k: (["/x/extra.csv"], "")
    )
    panel._load_data_sets()
    assert "extra" in [win.item(i).text() for i in range(win.count())]

    # Clear unchecks all; Select All re-checks all
    panel._set_all_source(False)
    assert all(
        win.item(i).checkState() == Qt.CheckState.Unchecked for i in range(win.count())
    )
    panel._set_all_source(True)
    assert all(
        win.item(i).checkState() == Qt.CheckState.Checked for i in range(win.count())
    )
    dlg.close()


def test_batch_run_dialog_no_source_warns(app, monkeypatch):
    """Continue on the Source tab with nothing selected warns and stays put."""
    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog(data_sets=["caseA"])
    dlg._source_panel._source_input.setCurrentIndex(
        dlg._source_panel._source_input.findData("data")
    )
    dlg._source_panel._set_all_source(False)  # uncheck the only data set

    warned = []
    monkeypatch.setattr(brd.QMessageBox, "warning", lambda *a, **k: warned.append(a))
    dlg._advance()
    assert warned and dlg._tabs.currentIndex() == 0  # warned, didn't advance
    dlg.close()


def test_batch_run_dialog_similar_format_disabled_in_data_mode(app):
    """'Has similar format' applies only to .sim sources: enabled in '.sim files'
    mode, grayed out in 'Loaded data sets' mode."""
    from starpost.gui.views.batch_run_dialog import BatchRunDialog

    dlg = BatchRunDialog(data_sets=["caseA"])
    panel = dlg._source_panel
    assert panel._has_similar_format.isEnabled()  # .sim mode (default)
    panel._source_input.setCurrentIndex(panel._source_input.findData("data"))
    assert not panel._has_similar_format.isEnabled()  # grayed in data mode
    panel._source_input.setCurrentIndex(panel._source_input.findData("sim"))
    assert panel._has_similar_format.isEnabled()  # re-enabled back in .sim mode
    dlg.close()


def test_batch_run_dialog_similar_format_extracts_first(app, monkeypatch):
    """With 'Has similar format' checked, Continue extracts the first selected
    .sim and repopulates the Reports and Plots tabs from its result."""
    from pathlib import Path

    from PySide6.QtCore import Qt

    import starpost.gui.views.batch_run_dialog as brd
    from starpost.core.settings import Settings
    from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, Report, SimResult

    dlg = brd.BatchRunDialog(settings=Settings(starccm_path="/usr/bin/starccm+"))
    monkeypatch.setattr(
        brd.QFileDialog, "getOpenFileNames",
        lambda *a, **k: (["/cases/a.sim", "/cases/b.sim"], ""),
    )
    dlg._source_panel._load_files()
    dlg._source_panel._has_similar_format.setChecked(True)

    result = SimResult(
        sim_path="/cases/a.sim",
        reports=[Report("Drag", 1.2), Report("Lift", 3.4)],
        plots=[MonitorPlot(
            "Residuals", [PlotSeries("Continuity", [1, 2], [0.1, 0.01])],
            kind=PlotKind.RESIDUAL,
        )],
    )
    extracted = []
    monkeypatch.setattr(
        brd.StarRunner, "extract",
        lambda self, sim, out, *a, **k: extracted.append(sim) or result,
    )
    dlg._advance()

    # The first selected .sim was extracted, the tabs repopulated, and the dialog
    # advanced off Source. Both files stay in the source list (no trimming).
    assert extracted == [Path("/cases/a.sim")]
    assert [p.name for p in dlg._source_panel._sim_files] == ["a.sim", "b.sim"]
    assert dlg._tabs.currentIndex() == 1
    reports = [dlg._reports_window.item(i).text()
               for i in range(dlg._reports_window.count())]
    assert reports == ["Drag", "Lift"]
    groups = [dlg._monitor_tree.topLevelItem(i).text(0)
              for i in range(dlg._monitor_tree.topLevelItemCount())]
    assert groups == ["Residuals"]

    # Going Back to Source and Continue again doesn't re-extract the same file.
    dlg._retreat()
    dlg._advance()
    assert extracted == [Path("/cases/a.sim")]  # still just the one run
    dlg.close()


def test_batch_run_dialog_source_row_click_toggles(app):
    """Clicking anywhere on a source row (not just the checkbox) toggles it."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from starpost.gui.views.batch_run_dialog import BatchRunDialog

    dlg = BatchRunDialog(data_sets=["caseA"])
    dlg._source_panel._source_input.setCurrentIndex(
        dlg._source_panel._source_input.findData("data")
    )
    win = dlg._source_panel._source_window
    item = win.item(0)
    assert item.checkState() == Qt.CheckState.Checked

    rect = win.visualItemRect(item)
    # Click in the row's text area (well right of the checkbox indicator).
    point = QPointF(rect.right() - 4, rect.center().y())
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, point, win.mapToGlobal(point.toPoint()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    win.mousePressEvent(press)
    assert item.checkState() == Qt.CheckState.Unchecked  # toggled by the row click

    # Selecting a row then clicking empty space clears the selection.
    win.setCurrentRow(0)
    assert win.selectedItems()
    off_screen = QPointF(5000, 5000)
    empty = QMouseEvent(
        QEvent.Type.MouseButtonPress, off_screen, win.mapToGlobal(off_screen.toPoint()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    win.mousePressEvent(empty)
    assert not win.selectedItems() and win.currentItem() is None
    dlg.close()


def test_source_panel_resolves_checked_sources(app):
    """SourcePanel resolves its checked rows to BatchSources on its own, without
    a full BatchRunDialog around it (the shape the Express batch dialog needs)."""
    from PySide6.QtCore import Qt

    import starpost.gui.views.batch_run_dialog as brd

    result = _sim_result_with_data()  # sim_name "caseA", existing test helper
    panel = brd.SourcePanel(
        None, data_sets=["caseA"], results=[result], show_similar_format=False
    )
    panel._source_input.setCurrentIndex(panel._source_input.findData("data"))
    assert panel._source_window.count() == 1
    panel._source_window.item(0).setCheckState(Qt.CheckState.Checked)

    srcs = panel.sources()
    assert [s.name for s in srcs] == ["caseA"]
    assert srcs[0].result is result
    assert panel.has_checked() is True


def test_source_panel_hides_similar_format_when_disabled(app):
    """When embedded without the 'Has similar format' option, the checkbox is
    still created (callers may still poke at it) but never shown."""
    import starpost.gui.views.batch_run_dialog as brd

    panel = brd.SourcePanel(None, show_similar_format=False)
    assert panel._has_similar_format.isVisible() is False


def test_batch_run_dialog_reports_tab(app):
    """Reports tab: the window lists every report (all checked); options offer the
    same file formats as export plus Include units."""
    from PySide6.QtCore import Qt

    from starpost.gui.views.batch_run_dialog import BatchRunDialog

    dlg = BatchRunDialog(report_names=["Drag", "Lift", "Downforce"])
    win = dlg._reports_window
    assert [win.item(i).text() for i in range(win.count())] == [
        "Drag", "Lift", "Downforce"
    ]
    assert all(
        win.item(i).checkState() == Qt.CheckState.Checked for i in range(win.count())
    )
    fmts = [dlg._report_format.itemText(i) for i in range(dlg._report_format.count())]
    assert fmts == ["CSV", "TSV", "XLSX", "ODS"]
    assert dlg._report_include_units.isChecked()
    assert not hasattr(dlg, "_report_separate_files")  # removed: archive folders separate them
    assert dlg._report_combined.isChecked()  # Combined report on by default
    # Select All / Clear flip every report's checkbox.
    dlg._set_all_reports(False)
    assert all(
        win.item(i).checkState() == Qt.CheckState.Unchecked for i in range(win.count())
    )
    dlg._set_all_reports(True)
    assert all(
        win.item(i).checkState() == Qt.CheckState.Checked for i in range(win.count())
    )
    dlg.close()


def test_batch_run_dialog_plots_tab(app):
    """Plots tab: a monitor tree (groups -> monitors); checking a group checks its
    monitors. The preview window opens only while the Plots tab is in front."""
    from PySide6.QtCore import Qt

    from starpost.gui.views.batch_run_dialog import BatchRunDialog

    dlg = BatchRunDialog(monitor_groups={"Residuals": ["Continuity", "X-momentum"]})
    tree = dlg._monitor_tree
    root = tree.invisibleRootItem()
    assert [root.child(i).text(0) for i in range(root.childCount())] == ["Residuals"]
    group = root.child(0)
    # Checking the group reveals its monitors but leaves them unchecked.
    group.setCheckState(0, Qt.CheckState.Checked)
    assert group.isExpanded()
    assert dlg._monitor_tree.checked_monitors() == {"Residuals": []}
    # The user then picks individual monitors.
    group.child(0).setCheckState(0, Qt.CheckState.Checked)
    assert dlg._monitor_tree.checked_monitors() == {"Residuals": ["Continuity"]}

    # A residual (auto-select) group instead checks all its monitors at once.
    dlg2 = BatchRunDialog(
        monitor_groups={"Residuals": ["Continuity", "X-momentum"]},
        residual_groups={"Residuals"},
    )
    dlg2._monitor_tree.invisibleRootItem().child(0).setCheckState(
        0, Qt.CheckState.Checked
    )
    assert dlg2._monitor_tree.checked_monitors() == {
        "Residuals": ["Continuity", "X-momentum"]
    }
    dlg2.close()

    # Preview window is hidden on the Source tab, shown on the Plots tab.
    plots_idx = next(
        i for i in range(dlg._tabs.count()) if dlg._tabs.widget(i) is dlg._plots_tab
    )
    dlg._tabs.setCurrentIndex(0)
    dlg._update_preview()
    assert dlg._preview_window.isHidden()
    dlg._tabs.setCurrentIndex(plots_idx)
    assert not dlg._preview_window.isHidden()
    dlg.close()


def test_batch_run_dialog_monitor_color_swatches(app):
    """Checked monitors get a colour swatch matching their drawn line; recolouring
    a monitor updates its swatch; unchecking clears it."""
    from PySide6.QtCore import Qt

    import starpost.gui.views.batch_run_dialog as brd
    from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, SimResult

    result = SimResult(
        sim_path="/c/a.sim",
        plots=[MonitorPlot(
            "Forces", [PlotSeries("Drag", [1, 2], [10.0, 9.0])],
            kind=PlotKind.FORCE,
        )],
    )
    dlg = brd.BatchRunDialog(monitor_groups={"Forces": ["Drag"]}, results=[result])
    g = dlg._monitor_tree.invisibleRootItem().child(0)
    g.setCheckState(0, Qt.CheckState.Checked)
    monitor = g.child(0)
    monitor.setCheckState(0, Qt.CheckState.Checked)
    # Checked → a swatch colour is stored (the drawn cycle colour).
    assert monitor.data(0, brd._SWATCH_ROLE)

    # Recolour the monitor → its swatch follows the new colour.
    dlg._preview.set_series_color("Drag", "#e6194b")
    dlg._refresh_monitor_swatches()
    assert monitor.data(0, brd._SWATCH_ROLE) == ["#e6194b"]

    # The chosen colour is captured into a saved plot.
    g_sel = dlg._monitor_tree.checked_monitors()
    assert g_sel == {"Forces": ["Drag"]}
    assert dlg._capture_plot()["monitor_colors"]["Drag"] == "#e6194b"

    # Unchecking the monitor clears its swatch.
    monitor.setCheckState(0, Qt.CheckState.Unchecked)
    assert monitor.data(0, brd._SWATCH_ROLE) is None
    dlg.close()


def test_batch_run_dialog_legend_scale(app):
    """The legend-scale slider applies to the preview and saves with the plot:
    mid is 1.0×, ends are 0.5×/2.0×, and the factor is captured."""
    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog(monitor_groups={"Residuals": ["Continuity"]})
    assert dlg._legend_scale.value() == 50  # opens at the natural size
    assert dlg._legend_factor(50) == 1.0
    assert dlg._legend_factor(0) == 0.5 and dlg._legend_factor(100) == 2.0

    # Moving the slider scales the preview's legend.
    applied = []
    dlg._preview.set_legend_scale = lambda f: applied.append(f)
    dlg._legend_scale.setValue(100)
    assert applied == [2.0]

    # The factor is captured into a saved plot.
    assert dlg._capture_plot()["legend_scale"] == 2.0
    dlg.close()


def test_batch_run_dialog_plot_option_parity(app):
    """The Plots tab carries the Export dialog's full option set (aspect ratio,
    title/axis-label sizes, line thickness), applied live and captured."""
    import starpost.gui.views.batch_run_dialog as brd
    import starpost.gui.views.export_dialog as exp

    dlg = brd.BatchRunDialog(monitor_groups={"Residuals": ["Continuity"]})

    # Sliders open at the same defaults as the Export dialog (unchanged plot).
    assert dlg._text_size_for(
        dlg._title_size.value(), exp._TITLE_PT_MIN, exp._TITLE_PT_MAX
    ) == exp._TITLE_PT_DEFAULT
    assert dlg._text_size_for(
        dlg._axis_label_size.value(), exp._AXIS_LABEL_PT_MIN, exp._AXIS_LABEL_PT_MAX
    ) == exp._AXIS_LABEL_PT_DEFAULT
    assert dlg._plot_aspect.currentText() == "Custom"

    # Each control applies to the preview / preview window.
    applied = {"title": [], "axis": [], "line": [], "aspect": []}
    dlg._preview.set_title_size = lambda v: applied["title"].append(v)
    dlg._preview.set_axis_label_size = lambda v: applied["axis"].append(v)
    dlg._preview.set_line_width = lambda v: applied["line"].append(v)
    dlg._preview_window.set_aspect = lambda r: applied["aspect"].append(r)
    dlg._title_size.setValue(100)
    dlg._axis_label_size.setValue(0)
    dlg._line_width.setValue(100)
    dlg._plot_aspect.setCurrentText("16:9")
    assert applied["title"] == [exp._TITLE_PT_MAX]
    assert applied["axis"] == [exp._AXIS_LABEL_PT_MIN]
    assert applied["line"] == [exp._LINE_WIDTH_MAX]
    assert applied["aspect"] == [16 / 9]

    # All new options are captured into a saved plot.
    chars = dlg._capture_plot()
    assert chars["title_size"] == exp._TITLE_PT_MAX
    assert chars["axis_label_size"] == exp._AXIS_LABEL_PT_MIN
    assert chars["line_width"] == exp._LINE_WIDTH_MAX
    assert chars["aspect"] == "16:9"
    dlg.close()


def test_batch_run_dialog_scenes_tab(app):
    """Scenes tab: options on the left, a scene tree (checking a scene reveals its
    scalar/vector displayers) in the middle, and a saved-views checklist on the
    right — all populated from the loaded sim."""
    from PySide6.QtCore import Qt

    from starpost.core.settings import Settings
    from starpost.data.models import Displayer, Scene, SimResult
    from starpost.gui.views.batch_run_dialog import BatchRunDialog

    result = SimResult(
        sim_path="/c/a.sim",
        scenes=[
            Scene("Pressure", [Displayer("Static Pressure", "scalar"),
                               Displayer("Velocity", "vector")]),
            Scene("Mesh", [Displayer("Mesh", "scalar")]),
        ],
        views=["Top", "Iso"],
    )
    dlg = BatchRunDialog(results=[result], settings=Settings())

    # Scene tree lists the scenes; checking one reveals its displayers as
    # checkable children, and the checked displayers are reported.
    root = dlg._scene_tree.invisibleRootItem()
    assert {root.child(i).text(0) for i in range(root.childCount())} == {
        "Pressure", "Mesh"
    }
    pressure = next(
        root.child(i) for i in range(root.childCount())
        if root.child(i).text(0) == "Pressure"
    )
    pressure.setCheckState(0, Qt.CheckState.Checked)
    assert pressure.isExpanded()
    assert [pressure.child(j).text(0) for j in range(pressure.childCount())] == [
        "Static Pressure", "Velocity"
    ]
    pressure.child(0).setCheckState(0, Qt.CheckState.Checked)
    assert dlg._scene_tree.checked_displayers() == {"Pressure": ["Static Pressure"]}

    # Saved views: checkable, opt-in (start unchecked).
    vw = dlg._views_window
    assert {vw.item(i).text() for i in range(vw.count())} == {"Top", "Iso"}
    assert all(
        vw.item(i).checkState() == Qt.CheckState.Unchecked for i in range(vw.count())
    )

    # Options exist and are seeded from settings.
    assert dlg._scene_resolution.currentData() == "1080p"
    assert dlg._scene_format.currentData() == "jpg"
    dlg.close()


def test_batch_run_dialog_summary_tab(app):
    """Summary tab: export options plus read-only lists of the selected reports,
    the saved plots and the saved scenes, refreshed when the tab is shown."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    from starpost.core.settings import Settings
    from starpost.gui.views.batch_run_dialog import BatchRunDialog

    dlg = BatchRunDialog(
        report_names=["Drag", "Lift", "Downforce"], settings=Settings()
    )
    # Deselect a report so "selected" differs from "all".
    dlg._reports_window.item(1).setCheckState(Qt.CheckState.Unchecked)  # Lift
    # Saved plots / scenes captured on earlier tabs.
    dlg._saved_plots.addItem(QListWidgetItem("Drag plot"))
    dlg._saved_scenes.addItem(QListWidgetItem("Pressure scene"))

    summary_idx = next(
        i for i in range(dlg._tabs.count()) if dlg._tabs.tabText(i) == "Summary"
    )
    dlg._tabs.setCurrentIndex(summary_idx)

    # Export options offer the archive formats.
    assert [
        dlg._export_format.itemData(i) for i in range(dlg._export_format.count())
    ] == ["zip", "7z"]
    # Reports column lists only the checked reports.
    assert [
        dlg._summary_reports.item(i).text()
        for i in range(dlg._summary_reports.count())
    ] == ["Drag", "Downforce"]
    # Plots / Scenes columns mirror the saved lists.
    assert [
        dlg._summary_plots.item(i).text()
        for i in range(dlg._summary_plots.count())
    ] == ["Drag plot"]
    assert [
        dlg._summary_scenes.item(i).text()
        for i in range(dlg._summary_scenes.count())
    ] == ["Pressure scene"]
    dlg.close()


def test_batch_run_dialog_save_scene(app, monkeypatch):
    """Save Scene (shown only on the Scenes tab) captures the scene setup
    (displayers, views, image options) into the Saved Scenes list."""
    from PySide6.QtCore import Qt

    import starpost.gui.views.batch_run_dialog as brd
    from starpost.core.settings import Settings
    from starpost.data.models import Displayer, Scene, SimResult

    result = SimResult(
        sim_path="/c/a.sim",
        scenes=[Scene("Pressure", [Displayer("Static Pressure", "scalar"),
                                   Displayer("Velocity", "vector")])],
        views=["Top", "Iso"],
    )
    dlg = brd.BatchRunDialog(results=[result], settings=Settings())
    scenes_idx = next(
        i for i in range(dlg._tabs.count()) if dlg._tabs.tabText(i) == "Scenes"
    )

    # Save Scene is hidden off the Scenes tab, shown on it (and Add Plot the
    # reverse).
    dlg._tabs.setCurrentIndex(0)
    dlg._update_preview()
    assert dlg._save_scene.isHidden()
    dlg._tabs.setCurrentIndex(scenes_idx)
    dlg._update_preview()
    assert not dlg._save_scene.isHidden()
    assert dlg._add_plot.isHidden()

    # Configure a scene + displayer + view, then Save Scene.
    g = dlg._scene_tree.invisibleRootItem().child(0)
    g.setCheckState(0, Qt.CheckState.Checked)
    g.child(0).setCheckState(0, Qt.CheckState.Checked)  # Static Pressure
    views = dlg._views_window
    next(views.item(i) for i in range(views.count())
         if views.item(i).text() == "Top").setCheckState(Qt.CheckState.Checked)

    monkeypatch.setattr(brd.QInputDialog, "getText", lambda *a, **k: ("Scene A", True))
    dlg._on_save_scene()

    assert dlg._saved_scenes.count() == 1
    item = dlg._saved_scenes.item(0)
    assert item.text() == "Scene A"
    data = item.data(Qt.ItemDataRole.UserRole)
    assert data["displayers"] == {"Pressure": ["Static Pressure"]}
    assert data["views"] == ["Top"]
    assert data["resolution"] == "1080p" and data["format"] == "jpg"
    dlg.close()


def test_batch_run_dialog_add_plot(app, monkeypatch):
    """Add Plot (shown only on the Plots tab) saves the plot characteristics under
    a prompted name into the Saved Plots list."""
    from PySide6.QtCore import Qt

    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog(monitor_groups={"Residuals": ["Continuity"]})
    plots_idx = next(
        i for i in range(dlg._tabs.count()) if dlg._tabs.widget(i) is dlg._plots_tab
    )
    # Add Plot is hidden off the Plots tab, shown on it.
    dlg._tabs.setCurrentIndex(0)
    dlg._update_preview()
    assert dlg._add_plot.isHidden()
    dlg._tabs.setCurrentIndex(plots_idx)
    assert not dlg._add_plot.isHidden()

    # Pick a monitor and a title, then Add Plot.
    g = dlg._monitor_tree.invisibleRootItem().child(0)
    g.setCheckState(0, Qt.CheckState.Checked)
    g.child(0).setCheckState(0, Qt.CheckState.Checked)
    dlg._plot_title.setText("My Plot")
    monkeypatch.setattr(brd.QInputDialog, "getText", lambda *a, **k: ("Forces", True))
    dlg._on_add_plot()

    assert dlg._saved_plots.count() == 1
    item = dlg._saved_plots.item(0)
    assert item.text() == "Forces"
    chars = item.data(Qt.ItemDataRole.UserRole)
    assert chars["title"] == "My Plot"
    assert chars["monitors"] == {"Residuals": ["Continuity"]}
    assert "Continuity" in chars["monitor_colors"]  # colour captured per monitor
    dlg.close()


def test_batch_run_dialog_add_plot_saves_every_option(app, monkeypatch):
    """Clicking Add Plot saves *every* plot option (and the monitor colours) on
    the saved-plot item, not just a subset."""
    from PySide6.QtCore import Qt

    import starpost.gui.views.batch_run_dialog as brd
    from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, SimResult

    result = SimResult(
        sim_path="/c/a.sim",
        plots=[MonitorPlot(
            "Forces", [PlotSeries("Drag", [1, 2], [10.0, 9.0])],
            kind=PlotKind.FORCE,
        )],
    )
    dlg = brd.BatchRunDialog(monitor_groups={"Forces": ["Drag"]}, results=[result])
    plots_idx = next(
        i for i in range(dlg._tabs.count()) if dlg._tabs.widget(i) is dlg._plots_tab
    )
    dlg._tabs.setCurrentIndex(plots_idx)
    dlg._update_preview()

    # Set every option to a distinct, non-default value.
    dlg._plot_aspect.setCurrentText("16:9")
    dlg._plot_title.setText("My Title")
    dlg._title_size.setValue(100)            # -> max pt
    dlg._plot_xlabel.setText("Iter")
    dlg._plot_ylabel.setText("Force (N)")
    dlg._axis_label_size.setValue(0)         # -> min pt
    dlg._plot_theme.setCurrentIndex(dlg._plot_theme.findData("dark"))
    dlg._legend_scale.setValue(0)            # -> 0.5x
    dlg._line_width.setValue(100)            # -> max px
    dlg._plot_grid.setChecked(False)
    dlg._plot_format.setCurrentText("PDF")

    # Pick a monitor and give it a colour.
    g = dlg._monitor_tree.invisibleRootItem().child(0)
    g.setCheckState(0, Qt.CheckState.Checked)
    g.child(0).setCheckState(0, Qt.CheckState.Checked)
    dlg._preview.set_series_color("Drag", "#e6194b")

    monkeypatch.setattr(brd.QInputDialog, "getText", lambda *a, **k: ("P", True))
    dlg._on_add_plot()

    chars = dlg._saved_plots.item(0).data(Qt.ItemDataRole.UserRole)
    assert chars["aspect"] == "16:9"
    assert chars["title"] == "My Title"
    assert chars["title_size"] == brd._TITLE_PT_MAX
    assert chars["x_label"] == "Iter"
    assert chars["y_label"] == "Force (N)"
    assert chars["axis_label_size"] == brd._AXIS_LABEL_PT_MIN
    assert chars["theme"] == "dark"
    assert chars["legend_scale"] == 0.5
    assert "legend_offset" in chars  # legend position captured (None until drawn)
    assert chars["line_width"] == brd._LINE_WIDTH_MAX
    assert chars["grid"] is False
    assert chars["format"] == "PDF"
    assert chars["monitors"] == {"Forces": ["Drag"]}
    assert chars["monitor_colors"]["Drag"] == "#e6194b"
    assert chars["series_colors"]["Drag"] == "#e6194b"
    dlg.close()


def test_batch_run_dialog_saved_plot_delete(app):
    """The Delete context-menu action removes that plot from Saved Plots."""
    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog()
    dlg._saved_plots.addItem("p1")
    dlg._saved_plots.addItem("p2")
    dlg._delete_saved_plot(dlg._saved_plots.item(0))
    assert [
        dlg._saved_plots.item(i).text() for i in range(dlg._saved_plots.count())
    ] == ["p2"]
    dlg.close()


def test_batch_run_dialog_saved_plot_properties(app, monkeypatch):
    """The Properties context-menu action opens the dialog for that plot."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog()
    data = {
        "title": "T", "x_label": "X", "y_label": "Y", "theme": "dark",
        "format": "PNG", "monitors": {"G": ["m1"]},
        "monitor_colors": {"m1": "#ff0000"},
    }
    item = QListWidgetItem("p1")
    item.setData(Qt.ItemDataRole.UserRole, data)
    dlg._saved_plots.addItem(item)
    # Capture the dialog instead of showing it modally.
    opened = []
    monkeypatch.setattr(
        brd._SavedPlotPropertiesDialog, "exec",
        lambda self: opened.append(self) or 0,
    )
    dlg._show_saved_plot_properties(item)
    assert len(opened) == 1
    dlg.close()


def test_batch_run_dialog_preview_saved_plot(app):
    """The Preview context-menu action loads a saved plot's captured settings
    back into the Plots-tab controls, monitor selection and live preview."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    import starpost.gui.views.batch_run_dialog as brd
    from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, SimResult

    result = SimResult(
        sim_path="/c/a.sim",
        plots=[MonitorPlot(
            "Forces", [PlotSeries("Drag", [1, 2], [10.0, 9.0])],
            kind=PlotKind.FORCE,
        )],
    )
    dlg = brd.BatchRunDialog(monitor_groups={"Forces": ["Drag"]}, results=[result])

    # Configure a plot, capture it, then reset the controls to their defaults.
    dlg._plot_title.setText("Drag vs iteration")
    dlg._plot_xlabel.setText("Iteration")
    dlg._plot_theme.setCurrentIndex(dlg._plot_theme.findData("dark"))
    dlg._monitor_tree.set_selection({"Forces": ["Drag"]})
    dlg._preview.set_series_color("Drag", "#e6194b")
    dlg._refresh_monitor_swatches()
    captured = dlg._capture_plot()

    dlg._plot_title.clear()
    dlg._plot_xlabel.clear()
    dlg._plot_theme.setCurrentIndex(dlg._plot_theme.findData("light"))
    dlg._monitor_tree.set_selection({})
    assert dlg._monitor_tree.checked_monitors() == {}

    # Preview restores everything from the saved plot.
    item = QListWidgetItem("p1")
    item.setData(Qt.ItemDataRole.UserRole, captured)
    dlg._preview_saved_plot(item)
    assert dlg._plot_title.text() == "Drag vs iteration"
    assert dlg._plot_xlabel.text() == "Iteration"
    assert dlg._plot_theme.currentData() == "dark"
    assert dlg._monitor_tree.checked_monitors() == {"Forces": ["Drag"]}
    assert dlg._preview.series_color("Drag") == "#e6194b"
    dlg.close()


def test_saved_plot_properties_dialog_content(app):
    """The properties dialog shows the plot's settings and each monitor's colour."""
    from PySide6.QtWidgets import QLabel

    from starpost.gui.views.batch_run_dialog import _SavedPlotPropertiesDialog

    data = {
        "title": "Drag", "x_label": "Iteration", "y_label": "Drag (N)",
        "theme": "dark", "format": "PNG",
        "monitors": {"Forces": ["Drag Monitor"]},
        "monitor_colors": {"Drag Monitor": "#e6194b"},
    }
    dlg = _SavedPlotPropertiesDialog("Drag", data)
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    assert "Drag" in texts and "Iteration" in texts and "Drag (N)" in texts
    assert "Dark" in texts and "PNG" in texts
    assert any("Drag Monitor" in t and "#e6194b" in t for t in texts)
    dlg.close()


def test_batch_run_dialog_saved_scene_delete(app):
    """The Delete context-menu action removes that scene from Saved Scenes."""
    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog()
    dlg._saved_scenes.addItem("s1")
    dlg._saved_scenes.addItem("s2")
    dlg._delete_saved_scene(dlg._saved_scenes.item(0))
    assert [
        dlg._saved_scenes.item(i).text() for i in range(dlg._saved_scenes.count())
    ] == ["s2"]
    dlg.close()


def test_batch_run_dialog_saved_scene_properties(app, monkeypatch):
    """The Properties context-menu action opens the dialog for that scene."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog()
    data = {
        "displayers": {"Scene 1": ["Pressure"]},
        "views": ["Front"], "resolution": "2160p", "format": "png",
    }
    item = QListWidgetItem("s1")
    item.setData(Qt.ItemDataRole.UserRole, data)
    dlg._saved_scenes.addItem(item)
    # Capture the dialog instead of showing it modally.
    opened = []
    monkeypatch.setattr(
        brd._SavedScenePropertiesDialog, "exec",
        lambda self: opened.append(self) or 0,
    )
    dlg._show_saved_scene_properties(item)
    assert len(opened) == 1
    dlg.close()


def test_saved_scene_properties_dialog_content(app):
    """The properties dialog shows the scene's image options, views and each
    scene's checked displayers."""
    from PySide6.QtWidgets import QLabel

    from starpost.gui.views.batch_run_dialog import _SavedScenePropertiesDialog

    data = {
        "displayers": {"Pressure scene": ["Scalar 1", "Vector 1"]},
        "views": ["Front", "Iso"], "resolution": "1080p", "format": "jpg",
    }
    dlg = _SavedScenePropertiesDialog("Pressure", data)
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    assert "1080p" in texts and "JPG" in texts
    assert any("Front" in t and "Iso" in t for t in texts)
    assert "Pressure scene" in texts
    assert any("Scalar 1" in t for t in texts)
    assert any("Vector 1" in t for t in texts)
    # The field/scene/views value labels wrap so a long list doesn't widen the
    # window.
    field = next(lb for lb in dlg.findChildren(QLabel) if lb.text() == "Scalar 1")
    assert field.wordWrap() and field.maximumWidth() < 16777215
    dlg.close()


def test_summary_mirrors_saved_plots_and_scenes_with_data(app):
    """The Summary tab copies saved plots/scenes with their captured data so
    Properties works and rows map 1:1 to their source."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog()
    plot = QListWidgetItem("Drag plot")
    plot.setData(Qt.ItemDataRole.UserRole, {"title": "T"})
    dlg._saved_plots.addItem(plot)
    scene = QListWidgetItem("Pressure scene")
    scene.setData(Qt.ItemDataRole.UserRole, {"resolution": "2160p"})
    dlg._saved_scenes.addItem(scene)

    dlg._tabs.setCurrentWidget(dlg._summary_tab)
    dlg._refresh_summary()
    assert dlg._summary_plots.item(0).text() == "Drag plot"
    assert dlg._summary_plots.item(0).data(Qt.ItemDataRole.UserRole) == {"title": "T"}
    assert dlg._summary_scenes.item(0).data(
        Qt.ItemDataRole.UserRole
    ) == {"resolution": "2160p"}
    dlg.close()


def test_summary_plot_properties_and_delete(app, monkeypatch):
    """The Summary tab's plot menu opens Properties and deletes from Saved Plots."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog()
    item = QListWidgetItem("p1")
    item.setData(Qt.ItemDataRole.UserRole, {"title": "T", "monitors": {}})
    dlg._saved_plots.addItem(item)
    dlg._tabs.setCurrentWidget(dlg._summary_tab)
    dlg._refresh_summary()

    opened = []
    monkeypatch.setattr(
        brd._SavedPlotPropertiesDialog, "exec",
        lambda self: opened.append(self) or 0,
    )
    dlg._show_saved_plot_properties(dlg._summary_plots.item(0))
    assert len(opened) == 1

    dlg._delete_summary_plot(dlg._summary_plots.item(0))
    assert dlg._saved_plots.count() == 0
    assert dlg._summary_plots.count() == 0
    dlg.close()


def test_summary_scene_properties_and_delete(app, monkeypatch):
    """The Summary tab's scene menu opens Properties and deletes from Saved
    Scenes."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog()
    item = QListWidgetItem("s1")
    item.setData(
        Qt.ItemDataRole.UserRole,
        {"displayers": {"Scene 1": ["Pressure"]}, "views": []},
    )
    dlg._saved_scenes.addItem(item)
    dlg._tabs.setCurrentWidget(dlg._summary_tab)
    dlg._refresh_summary()

    opened = []
    monkeypatch.setattr(
        brd._SavedScenePropertiesDialog, "exec",
        lambda self: opened.append(self) or 0,
    )
    dlg._show_saved_scene_properties(dlg._summary_scenes.item(0))
    assert len(opened) == 1

    dlg._delete_summary_scene(dlg._summary_scenes.item(0))
    assert dlg._saved_scenes.count() == 0
    assert dlg._summary_scenes.count() == 0
    dlg.close()


def test_batch_profiles_are_separate_from_profiles(app, monkeypatch):
    """Saving a batch profile writes to the batch-profiles dir and is independent
    of the regular report/plot profiles."""
    from starpost.core import settings as cfg

    assert cfg.list_batch_profiles() == []
    cfg.BatchProfile(name="Nightly").save()
    assert cfg.list_batch_profiles() == ["Nightly"]
    assert cfg.BatchProfile.load("Nightly").name == "Nightly"
    # It must not leak into the regular profiles, nor vice versa.
    assert cfg.list_profiles() == []
    cfg.delete_batch_profile("Nightly")
    assert cfg.list_batch_profiles() == []


def test_settings_dialog_lists_and_deletes_batch_profiles(app, monkeypatch):
    """The Settings Profiles page lists batch profiles, opens their details, and
    deletes them."""
    from PySide6.QtWidgets import QLabel

    from starpost.core import settings as cfg
    from starpost.gui.views import settings_dialog as sd

    cfg.BatchProfile(
        name="Nightly",
        selected_reports=["Drag"],
        saved_plots=[{"name": "Forces plot", "data": {}}],
        saved_scenes=[{"name": "Pressure", "data": {}}],
    ).save()

    dlg = sd.SettingsDialog(cfg.Settings.from_dict({}))
    try:
        # The batch profile appears in the batch list.
        labels = [
            dlg._batch_profiles_list.itemAt(i).widget().text()
            for i in range(dlg._batch_profiles_list.count())
            if isinstance(dlg._batch_profiles_list.itemAt(i).widget(), QLabel)
        ]
        assert "Nightly" in labels

        # Show Details opens the batch details dialog.
        opened = []
        monkeypatch.setattr(
            sd.BatchProfileDetailsDialog, "exec",
            lambda self: opened.append(self) or 0,
        )
        dlg._show_batch_profile_details("Nightly")
        assert len(opened) == 1

        # Delete (confirmed) removes it from disk and refreshes the list.
        monkeypatch.setattr(
            sd.QMessageBox, "question", lambda *a, **k: sd.QMessageBox.Yes
        )
        dlg._delete_batch_profile("Nightly")
        assert cfg.list_batch_profiles() == []
    finally:
        dlg.deleteLater()


def test_batch_profile_details_dialog_content(app):
    """The batch-profile details dialog lists its reports, saved plots and
    saved scenes."""
    from PySide6.QtWidgets import QLabel

    from starpost.core.settings import BatchProfile
    from starpost.gui.views.settings_dialog import BatchProfileDetailsDialog

    profile = BatchProfile(
        name="Nightly",
        selected_reports=["Drag", "Lift"],
        saved_plots=[{"name": "Forces plot", "data": {}}],
        saved_scenes=[{"name": "Pressure scene", "data": {}}],
    )
    dlg = BatchProfileDetailsDialog(profile)
    try:
        texts = [w.text() for w in dlg.findChildren(QLabel)]
        assert "Reports" in texts and "Saved plots" in texts
        assert "Saved scenes" in texts
    finally:
        dlg.deleteLater()


def test_batch_profile_details_plot_menu(app, monkeypatch):
    """Saved plots in the batch-profile details window offer Properties (and no
    Delete)."""
    from starpost.core.settings import BatchProfile
    from starpost.gui.views import batch_run_dialog as brd
    from starpost.gui.views import settings_dialog as sd

    entry = {"name": "Forces plot", "data": {
        "title": "Drag", "monitors": {"Forces": ["Drag", "Lift"]},
        "series_colors": {"Drag": "#e6194b"}, "theme": "dark",
    }}
    dlg = sd.BatchProfileDetailsDialog(
        BatchProfile(name="N", saved_plots=[entry])
    )
    try:
        # The item carries its captured entry for the menu to read.
        assert dlg._plots.item(0).data(sd.Qt.ItemDataRole.UserRole) == entry

        opened = []
        monkeypatch.setattr(
            brd._SavedPlotPropertiesDialog, "exec",
            lambda self: opened.append("props") or 0,
        )
        dlg._plot_properties(entry)
        assert opened == ["props"]
    finally:
        dlg.deleteLater()


def test_batch_profile_details_scene_menu(app, monkeypatch):
    """Saved scenes in the batch-profile details window offer Properties only."""
    from starpost.core.settings import BatchProfile
    from starpost.gui.views import batch_run_dialog as brd
    from starpost.gui.views import settings_dialog as sd

    entry = {"name": "Pressure", "data": {
        "displayers": {"Scene 1": ["Pressure"]}, "views": [],
        "resolution": "1080p", "format": "png",
    }}
    dlg = sd.BatchProfileDetailsDialog(
        BatchProfile(name="N", saved_scenes=[entry])
    )
    try:
        assert dlg._scenes.item(0).data(sd.Qt.ItemDataRole.UserRole) == entry
        opened = []
        monkeypatch.setattr(
            brd._SavedScenePropertiesDialog, "exec",
            lambda self: opened.append("props") or 0,
        )
        dlg._scene_properties(entry)
        assert opened == ["props"]
    finally:
        dlg.deleteLater()


def test_batch_run_dialog_save_and_load_profile(app, monkeypatch):
    """The dialog's Batch profile bar saves to / lists from the batch profiles."""
    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog()
    assert dlg._profile_box.count() == 0
    monkeypatch.setattr(brd.QInputDialog, "getText", lambda *a, **k: ("Weekly", True))
    dlg._save_profile()
    assert [dlg._profile_box.itemText(i) for i in range(dlg._profile_box.count())] == [
        "Weekly"
    ]
    assert dlg._profile_box.currentText() == "Weekly"
    dlg._load_profile()  # resolves without error
    dlg.close()


def test_batch_profile_saves_reports_plots_scenes(app, monkeypatch):
    """Saving a batch profile captures the ticked reports and the saved plots and
    scenes; loading it into a fresh dialog restores all of them."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog(report_names=["Drag", "Lift", "Downforce"])
    # Deselect a report, and capture a plot + a scene (with full data, including a
    # tuple-keyed pair_colors that must survive the YAML round-trip).
    dlg._reports_window.item(1).setCheckState(Qt.CheckState.Unchecked)  # Lift
    plot_item = QListWidgetItem("Drag plot")
    plot_item.setData(Qt.ItemDataRole.UserRole, {
        "title": "Drag", "monitors": {"Forces": ["Drag"]},
        "series_colors": {"Drag": "#e6194b"},
        "pair_colors": {("caseA", "Drag"): "#123456"},
    })
    dlg._saved_plots.addItem(plot_item)
    scene_item = QListWidgetItem("Pressure scene")
    scene_item.setData(Qt.ItemDataRole.UserRole, {
        "displayers": {"Pressure": ["Static Pressure"]}, "views": ["Top"],
        "resolution": "1080p", "format": "jpg",
    })
    dlg._saved_scenes.addItem(scene_item)

    monkeypatch.setattr(brd.QInputDialog, "getText", lambda *a, **k: ("Full", True))
    dlg._save_profile()
    dlg.close()

    # A fresh dialog with the same reports available, loading the saved profile.
    dlg2 = brd.BatchRunDialog(report_names=["Drag", "Lift", "Downforce"])
    dlg2._profile_box.setCurrentText("Full")
    dlg2._load_profile()

    checked = [
        dlg2._reports_window.item(i).text()
        for i in range(dlg2._reports_window.count())
        if dlg2._reports_window.item(i).checkState() == Qt.CheckState.Checked
    ]
    assert checked == ["Drag", "Downforce"]

    assert dlg2._saved_plots.count() == 1
    p = dlg2._saved_plots.item(0)
    assert p.text() == "Drag plot"
    pdata = p.data(Qt.ItemDataRole.UserRole)
    assert pdata["title"] == "Drag"
    assert pdata["monitors"] == {"Forces": ["Drag"]}
    assert pdata["series_colors"] == {"Drag": "#e6194b"}
    assert pdata["pair_colors"] == {("caseA", "Drag"): "#123456"}  # tuple restored

    assert dlg2._saved_scenes.count() == 1
    s = dlg2._saved_scenes.item(0)
    assert s.text() == "Pressure scene"
    assert s.data(Qt.ItemDataRole.UserRole)["displayers"] == {
        "Pressure": ["Static Pressure"]
    }
    dlg2.close()


def test_batch_run_dialog_profile_captures_report_settings(app):
    import starpost.gui.views.batch_run_dialog as brd
    from starpost.core.settings import BatchProfile

    dlg = brd.BatchRunDialog(None, report_names=["Drag"])
    dlg._report_format.setCurrentText("ODS")
    dlg._report_include_units.setChecked(False)
    dlg._report_combined.setChecked(False)

    prof = dlg._build_profile("P")
    assert prof.report_format == "ODS"
    assert prof.include_units is False
    assert prof.combined_report is False

    dlg._apply_profile(
        BatchProfile(name="Q", report_format="XLSX",
                     include_units=True, combined_report=True)
    )
    assert dlg._report_format.currentText() == "XLSX"
    assert dlg._report_include_units.isChecked() is True
    assert dlg._report_combined.isChecked() is True


def test_batch_run_dialog_save_scene_captures_image_options(app, monkeypatch):
    """Save Scene records the current image resolution and format with the
    scene, so each saved scene carries its own render options."""
    from PySide6.QtCore import Qt

    import starpost.gui.views.batch_run_dialog as brd
    from starpost.core.settings import Settings
    from starpost.data.models import Displayer, Scene, SimResult

    result = SimResult(
        sim_path="/c/a.sim",
        scenes=[Scene("Pressure", [Displayer("Static Pressure", "scalar")])],
    )
    dlg = brd.BatchRunDialog(results=[result], settings=Settings())
    dlg._scene_resolution.setCurrentIndex(dlg._scene_resolution.findData("2160p"))
    dlg._scene_format.setCurrentIndex(dlg._scene_format.findData("png"))

    monkeypatch.setattr(brd.QInputDialog, "getText", lambda *a, **k: ("S", True))
    dlg._on_save_scene()
    data = dlg._saved_scenes.item(0).data(Qt.ItemDataRole.UserRole)
    assert data["resolution"] == "2160p" and data["format"] == "png"
    dlg.close()


def _sim_result_with_data():
    from starpost.data.models import (
        MonitorPlot, PlotKind, PlotSeries, Report, SimResult,
    )

    return SimResult(
        sim_path="/c/caseA.sim",
        reports=[Report("Drag", 1.5, units="N")],
        plots=[MonitorPlot(
            "Forces", [PlotSeries("Drag", [1, 2, 3], [10.0, 9.0, 8.0])],
            kind=PlotKind.FORCE,
        )],
    )


def test_startup_does_not_import_heavy_deferred_libs(tmp_path):
    """Opening the main window with nothing loaded must not pull in pandas (a
    ~400 ms import, deferred to the first comparison table), jinja2 (~40 ms,
    deferred to the first macro render), or pyqtgraph/numpy (~300 ms, deferred
    with the plot view until the post-paint warm-up). Runs in a subprocess so
    imports from other tests can't mask a regression."""
    import subprocess
    import sys

    code = (
        "import os, sys\n"
        "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n"
        "from pathlib import Path\n"
        "import starpost.data.store as store\n"
        f"store.results_cache_path = lambda: Path({str(tmp_path)!r}) / 'none.json'\n"
        "from PySide6.QtWidgets import QApplication\n"
        "from starpost.core.settings import Settings\n"
        "from starpost.gui.main_window import MainWindow\n"
        "app = QApplication([])\n"
        "w = MainWindow(Settings())\n"
        "heavy = ('pandas', 'jinja2', 'pyqtgraph', 'numpy')\n"
        "leaked = [m for m in heavy if m in sys.modules]\n"
        "print(','.join(leaked))\n"
        "sys.exit(1 if leaked else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert proc.returncode == 0, (
        f"imported at startup: {proc.stdout.strip()}\n{proc.stderr}"
    )


def test_cache_load_is_deferred_past_construction(app):
    """The crash-recovery cache loads on the first event-loop pass, not inside
    __init__ — the window can appear before a large cache is parsed."""
    seed = mw.ResultStore()
    seed.put(_sim_result_with_data())
    seed.save_cache()  # the per-user cache path (isolated to tmp by the fixture)

    win = mw.MainWindow(Settings())
    assert win.store.all() == []  # not loaded during construction
    app.processEvents()           # the deferred load runs on the first pass
    names = [r.sim_name for r in win.store.all()]
    assert names == ["caseA"]
    # The views were populated from the loaded data too (the Data tab tree).
    assert "caseA" in [it.text(0) for it in win.data_list._iter_data()]
    win.close()


def test_corrupt_cache_does_not_block_startup(app):
    """A cache that fails to parse is skipped (and logged), not fatal."""
    import starpost.utils.paths as paths_mod

    paths_mod.results_cache_path().write_text("{not json", encoding="utf-8")
    win = mw.MainWindow(Settings())
    app.processEvents()  # the deferred load hits the corrupt file
    assert win.store.all() == []
    win.close()


def test_checkbox_bursts_coalesce_into_one_refresh(app, monkeypatch):
    """A burst of checkbox-change signals (e.g. a Shift+click range tick, one
    signal per item) queues a single refresh, run after the burst — and a
    Data-tab change in the burst re-scopes the choice lists in that one pass."""
    win = mw.MainWindow(Settings())
    refreshes, rescopes = [], []
    monkeypatch.setattr(win, "_refresh_views", lambda: refreshes.append(1))
    monkeypatch.setattr(
        win, "_refresh_report_choices", lambda: rescopes.append(1)
    )

    for _ in range(8):
        win._on_selection_changed()
    win._on_data_selection_changed()
    win._on_data_selection_changed()
    assert refreshes == []  # queued, not run per signal
    app.processEvents()
    assert refreshes == [1] and rescopes == [1]

    # A plain selection change must not re-scope the choice lists.
    win._on_selection_changed()
    app.processEvents()
    assert refreshes == [1, 1] and rescopes == [1]
    win.close()


def test_full_rebuild_drops_queued_refresh(app, monkeypatch):
    """_refresh_from_store covers everything a queued coalesced refresh does,
    so a pending one is dropped instead of running again afterwards."""
    win = mw.MainWindow(Settings())
    refreshes = []
    monkeypatch.setattr(win, "_refresh_views", lambda: refreshes.append(1))
    win._on_selection_changed()
    win._refresh_from_store()  # runs the (stubbed) refresh synchronously
    assert refreshes == [1]
    app.processEvents()  # the queued one must have been cancelled
    assert refreshes == [1]
    win.close()


def test_plot_render_deferred_while_tab_hidden(app, monkeypatch):
    """With the Reports tab in front, refreshes skip the plot redraw entirely;
    switching to the Plots tab then draws the pending state once."""
    win = mw.MainWindow(Settings())
    result = _sim_result_with_data()
    win.store.put(result)
    win._refresh_from_store()
    win.data_list.set_entries([result.sim_name])
    monkeypatch.setattr(win, "_active_results", lambda: [result], raising=False)
    monkeypatch.setattr(
        win, "_selected_plot_names", lambda: ["Forces"], raising=False
    )
    monkeypatch.setattr(
        win.selection, "selected_monitors",
        lambda: {"Forces": ["Drag"]}, raising=False,
    )

    renders = []
    original = win.plot_view._render
    monkeypatch.setattr(
        win.plot_view, "_render", lambda: renders.append(1) or original()
    )

    assert win._center_tabs.currentWidget() is win.report_table  # default tab
    win._refresh_views()
    assert renders == [] and win._plot_stale  # skipped while hidden

    win._center_tabs.setCurrentWidget(win._plot_tab)  # switch draws it once
    assert renders == [1]
    assert not win._plot_stale
    assert win.plot_view.has_content()

    # Once visible (and fresh), further refreshes render normally.
    win._refresh_views()
    assert renders == [1, 1]
    win.close()


def test_render_plot_renders_once(app, monkeypatch):
    """_render_plot draws the plot exactly once: the monitor selection is stored
    before show_plots/show_comparison, not applied with a second render after."""
    win = mw.MainWindow(Settings())
    result = _sim_result_with_data()
    win.store.put(result)
    win._refresh_from_store()
    win.data_list.set_entries([result.sim_name])
    # Renders are skipped while the Plots tab is hidden; bring it to the front
    # (before counting) so _render_plot actually draws.
    win._center_tabs.setCurrentWidget(win._plot_tab)
    monkeypatch.setattr(
        win, "_active_results", lambda: [result], raising=False
    )
    monkeypatch.setattr(
        win, "_selected_plot_names", lambda: ["Forces"], raising=False
    )
    monkeypatch.setattr(
        win.selection, "selected_monitors",
        lambda: {"Forces": ["Drag"]}, raising=False,
    )

    renders = []
    original = win.plot_view._render
    monkeypatch.setattr(
        win.plot_view, "_render", lambda: renders.append(1) or original()
    )

    win._render_plot()  # single (per-file) mode
    assert len(renders) == 1

    renders.clear()
    win._is_comparison = lambda: True
    win._render_plot()  # comparison mode
    assert len(renders) == 1
    assert win.plot_view.has_content()
    win.close()


def test_render_saved_plot(app, tmp_path):
    """A saved plot renders to an image file; an unmatched plot writes nothing."""
    from starpost.batch.run import render_saved_plot

    result = _sim_result_with_data()
    out = tmp_path / "p.png"
    assert render_saved_plot(
        result,
        {"monitors": {"Forces": ["Drag"]}, "title": "Drag", "format": "png"},
        Settings(), out,
    )
    assert out.exists() and out.stat().st_size > 0

    # A plot whose groups aren't in this result writes nothing.
    missing = tmp_path / "none.png"
    assert not render_saved_plot(
        result, {"monitors": {"Nope": ["x"]}, "format": "png"}, Settings(), missing
    )
    assert not missing.exists()


def test_render_saved_plot_honours_legend_offset(app, tmp_path):
    """A saved plot's legend position (a fraction of the plot area) is applied
    when the batch renders it — the legend lands at the saved offset, not back at
    its default corner."""
    from starpost.batch.run import render_saved_plot
    from starpost.gui.views.plot_view import PlotView

    result = _sim_result_with_data()

    # Capture where the legend actually sits (as a fraction of the plot area) at
    # export time, without depending on decoding the written image.
    seen = {}
    original = PlotView.export

    def spy(self, path, fmt, scale=3.0):
        vb = self._vb.sceneBoundingRect()
        lg = self._legend.sceneBoundingRect()
        seen["frac"] = (
            (lg.left() - vb.left()) / vb.width(),
            (lg.top() - vb.top()) / vb.height(),
        )
        return original(self, path, fmt, scale)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(PlotView, "export", spy)
    try:
        assert render_saved_plot(
            result,
            {"monitors": {"Forces": ["Drag"]}, "legend_offset": [0.7, 0.3],
             "format": "png"},
            Settings(), tmp_path / "p.png",
        )
    finally:
        monkeypatch.undo()

    fx, fy = seen["frac"]
    assert abs(fx - 0.7) < 0.02 and abs(fy - 0.3) < 0.02


def test_build_batch_archive(app, tmp_path, monkeypatch):
    """The batch archive holds one folder per data set with its report, saved-plot
    image and saved-scene still."""
    import zipfile
    from pathlib import Path

    import starpost.batch.run as run

    result = _sim_result_with_data()
    config = run.BatchConfig(
        sources=[run.BatchSource(
            name="caseA", result=result, sim_file=Path("/c/caseA.sim")
        )],
        reports={"Drag"}, report_format="csv", include_units=True,
        saved_plots=[{
            "name": "Drag plot",
            "data": {"monitors": {"Forces": ["Drag"]}, "format": "png"},
        }],
        saved_scenes=[{
            "name": "Pressure",
            "data": {"displayers": {"Pressure": ["Static Pressure"]},
                     "views": [], "resolution": "1080p", "format": "png"},
        }],
    )

    # Stub scene rendering (needs STAR-CCM+): drop a still into the folder.
    def fake_render_scenes(self, sim_file, output_dir, scene_show,
                           view_names=None, log_sink=None):
        (Path(output_dir) / "Pressure.png").write_bytes(b"\x89PNG")
        return []
    monkeypatch.setattr(run.StarRunner, "render_scenes", fake_render_scenes)

    progress = []
    dest = tmp_path / "out" / "batch.zip"
    run.build_batch_archive(
        config, Settings(), run.StarRunner(Settings()), dest,
        progress=lambda f, m: progress.append((f, m)),
    )

    assert dest.exists()
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        report_csv = zf.read("caseA/reports.csv").decode().strip().splitlines()
    assert "caseA/reports.csv" in names
    assert "caseA/Drag plot.png" in names
    assert "caseA/Pressure.png" in names
    # Reports are laid out vertically: a header then one row per report.
    assert report_csv[0] == "Report,caseA"
    assert report_csv[1].startswith("Drag [N],")

    # Progress runs 0..1 and names each action.
    fractions = [f for f, _ in progress]
    messages = [m for _, m in progress]
    assert fractions == sorted(fractions)  # monotonic
    assert fractions[0] == 0.0 and fractions[-1] == 1.0
    assert any("Writing reports" in m for m in messages)
    assert any("Rendering plot" in m for m in messages)
    assert any("Rendering scene" in m for m in messages)
    assert any("Packaging" in m for m in messages)


def test_build_batch_archive_includes_dataset_csv(app, tmp_path):
    """With include_dataset_csv, each data-set folder also gets the portable CSV
    (the Data tab's Export Data file), which round-trips through read_sim_csv."""
    import zipfile

    import starpost.batch.run as run
    from starpost.data.portable import read_sim_csv

    result = _sim_result_with_data()
    config = run.BatchConfig(
        sources=[run.BatchSource(name="caseA", result=result)],
        reports={"Drag"}, report_format="csv",
        include_dataset_csv=True,
    )
    dest = tmp_path / "batch.zip"
    run.build_batch_archive(config, Settings(), run.StarRunner(Settings()), dest)

    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        zf.extract("caseA/caseA.csv", tmp_path)
    assert {"caseA/reports.csv", "caseA/caseA.csv"} <= names
    loaded = read_sim_csv(tmp_path / "caseA" / "caseA.csv")
    assert [r.name for r in loaded.reports] == ["Drag"]
    assert [p.name for p in loaded.plots] == ["Forces"]


def test_build_batch_archive_7z(app, tmp_path):
    """archive_format='7z' produces a real .7z with the same per-folder layout."""
    import py7zr

    import starpost.batch.run as run

    result = _sim_result_with_data()
    config = run.BatchConfig(
        sources=[run.BatchSource(name="caseA", result=result)],
        reports={"Drag"}, report_format="csv",
        archive_format="7z",
    )
    dest = tmp_path / "batch.7z"
    run.build_batch_archive(config, Settings(), run.StarRunner(Settings()), dest)

    assert dest.exists()
    with py7zr.SevenZipFile(dest, "r") as z:
        names = set(z.getnames())
    assert "caseA/reports.csv" in names


def test_build_batch_archive_rejects_unknown_format(app, tmp_path):
    """An unsupported archive_format raises rather than silently producing a zip."""
    import starpost.batch.run as run

    result = _sim_result_with_data()
    config = run.BatchConfig(
        sources=[run.BatchSource(name="caseA", result=result)],
        reports={"Drag"}, report_format="csv",
        archive_format="rar",
    )
    dest = tmp_path / "batch.rar"
    with pytest.raises(ValueError):
        run.build_batch_archive(config, Settings(), run.StarRunner(Settings()), dest)


def test_build_batch_archive_combined_report(app, tmp_path):
    """With combined_report (the default), one all-sims report is written at the
    archive root (one column per sim), alongside each data set's own report."""
    import zipfile

    from starpost.data.models import Report, SimResult
    import starpost.batch.run as run

    a = SimResult(sim_path="/c/caseA.sim", reports=[Report("Drag", 1.5, units="N")])
    b = SimResult(sim_path="/c/caseB.sim", reports=[Report("Drag", 2.5, units="N")])
    config = run.BatchConfig(
        sources=[run.BatchSource(name="caseA", result=a),
                 run.BatchSource(name="caseB", result=b)],
        reports={"Drag"}, report_format="csv", include_units=True,
    )
    dest = tmp_path / "batch.zip"
    run.build_batch_archive(config, Settings(), run.StarRunner(Settings()), dest)

    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        combined = zf.read("reports_combined.csv").decode().strip().splitlines()
    # The combined report sits at the root (no folder prefix); the per-data-set
    # reports still live in their own folders.
    assert "reports_combined.csv" in names
    assert {"caseA/reports.csv", "caseB/reports.csv"} <= names
    # One "Report" column then one column per sim; one row per report.
    assert combined[0] == "Report,caseA,caseB"
    assert combined[1] == "Drag [N],1.5,2.5"


def test_build_batch_archive_combined_report_off(app, tmp_path):
    """combined_report=False writes no root report; per-folder ones stay."""
    import zipfile

    import starpost.batch.run as run

    result = _sim_result_with_data()
    config = run.BatchConfig(
        sources=[run.BatchSource(name="caseA", result=result)],
        reports={"Drag"}, report_format="csv", combined_report=False,
    )
    dest = tmp_path / "batch.zip"
    run.build_batch_archive(config, Settings(), run.StarRunner(Settings()), dest)

    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
    assert "caseA/reports.csv" in names
    assert not any(n.startswith("reports_combined") for n in names)


def test_build_batch_archive_extracts_sim_sources(app, tmp_path, monkeypatch):
    """A .sim source (no preloaded result) is extracted during the run."""
    from pathlib import Path

    import starpost.batch.run as run

    extracted = []

    def fake_extract(self, sim_file, output_dir, log_sink=None):
        extracted.append(Path(sim_file))
        return _sim_result_with_data()
    monkeypatch.setattr(run.StarRunner, "extract", fake_extract)

    config = run.BatchConfig(
        sources=[run.BatchSource(name="caseB", sim_file=Path("/c/caseB.sim"))],
        reports={"Drag"}, report_format="csv",
    )
    dest = tmp_path / "batch.zip"
    run.build_batch_archive(config, Settings(), run.StarRunner(Settings()), dest)

    assert extracted == [Path("/c/caseB.sim")]
    import zipfile
    with zipfile.ZipFile(dest) as zf:
        assert "caseB/reports.csv" in set(zf.namelist())


def test_batch_run_dialog_run_batch_wiring(app, tmp_path, monkeypatch):
    """Batch run resolves the checked source + selections into a config, builds the
    archive in the chosen folder, and accepts the dialog."""
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QListWidgetItem

    import starpost.batch.run as run
    import starpost.gui.views.batch_run_dialog as brd

    result = _sim_result_with_data()
    dlg = brd.BatchRunDialog(
        data_sets=["caseA"], report_names=["Drag"], results=[result],
        settings=Settings(starccm_path="/usr/bin/starccm+"),
    )
    # Data mode → caseA is listed and checked.
    dlg._source_panel._source_input.setCurrentIndex(
        dlg._source_panel._source_input.findData("data")
    )
    plot = QListWidgetItem("Drag plot")
    plot.setData(Qt.ItemDataRole.UserRole, {"monitors": {"Forces": ["Drag"]}, "format": "png"})
    dlg._saved_plots.addItem(plot)
    dlg._include_dataset_csv.setChecked(True)
    dlg._report_combined.setChecked(False)  # verify the checkbox is read, not defaulted

    captured = {}

    def fake_build(config, settings, runner, dest, **_kw):
        captured["config"] = config
        captured["dest"] = Path(dest)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"zip")
        return dest

    monkeypatch.setattr(run, "build_batch_archive", fake_build)
    monkeypatch.setattr(
        brd.QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path)
    )
    monkeypatch.setattr(brd.QMessageBox, "information", lambda *a, **k: None)

    dlg._run_batch()

    cfg = captured["config"]
    assert [s.name for s in cfg.sources] == ["caseA"]
    assert cfg.sources[0].result is result
    assert cfg.reports == {"Drag"}
    assert [e["name"] for e in cfg.saved_plots] == ["Drag plot"]
    assert cfg.include_dataset_csv is True
    assert cfg.combined_report is False
    assert captured["dest"].parent == tmp_path and captured["dest"].suffix == ".zip"
    assert dlg.result() == QDialog.DialogCode.Accepted
    dlg.close()


def test_batch_run_dialog_run_batch_threaded(app, tmp_path, monkeypatch):
    """End to end on the worker thread: a data set with a saved plot produces a
    zip, with the plot rendered via the GUI-thread marshalling (no deadlock)."""
    import zipfile
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QListWidgetItem

    import starpost.gui.views.batch_run_dialog as brd

    result = _sim_result_with_data()  # sim_name "caseA", report + a plot
    dlg = brd.BatchRunDialog(
        data_sets=["caseA"], report_names=["Drag"], results=[result],
        settings=Settings(),
    )
    dlg._source_panel._source_input.setCurrentIndex(
        dlg._source_panel._source_input.findData("data")
    )
    plot = QListWidgetItem("Drag plot")
    plot.setData(
        Qt.ItemDataRole.UserRole, {"monitors": {"Forces": ["Drag"]}, "format": "png"}
    )
    dlg._saved_plots.addItem(plot)

    monkeypatch.setattr(
        brd.QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path)
    )
    monkeypatch.setattr(brd.QMessageBox, "information", lambda *a, **k: None)

    dlg._run_batch()  # runs the worker thread + local event loop to completion

    assert dlg.result() == QDialog.DialogCode.Accepted
    zips = list(tmp_path.glob("*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        names = set(zf.namelist())
    assert "caseA/reports.csv" in names
    assert "caseA/Drag plot.png" in names
    dlg.close()


def test_scene_properties_wraps_long_field_list(app):
    """The rendered-scene Properties dialog wraps its (possibly long) Vector/
    Scalar field list instead of stretching the window wide."""
    from starpost.data.models import MediaArtifact
    from starpost.gui.views.properties_dialog import ScenePropertiesDialog

    fields = ", ".join(f"field {i}" for i in range(15))
    art = MediaArtifact(
        name="Scene 1", path="", source="Scene 1",
        sim_path="/c/a.sim", displayers=fields, view="View 1",
    )
    dlg = ScenePropertiesDialog(art)
    try:
        from PySide6.QtWidgets import QLabel

        label = next(
            lb for lb in dlg.findChildren(QLabel) if lb.text() == fields
        )
        assert label.wordWrap()
        assert label.maximumWidth() < 16777215  # bounded, so it wraps
    finally:
        dlg.deleteLater()


def _click(view, rect, shift=False):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    mod = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, mod, rect.center())


def test_shift_click_checks_range_in_data_tab(app):
    """On the Data tab, click one row then Shift+click another ticks every data
    set between them (inclusive)."""
    from starpost.gui.views.data_list import DataListPanel

    dp = DataListPanel()
    dp.set_entries([f"d{i}" for i in range(5)])
    dp.resize(300, 400)
    dp.show()
    tree = dp._tree
    rows = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    _click(tree, tree.visualItemRect(rows[0]))
    _click(tree, tree.visualItemRect(rows[3]), shift=True)
    assert sorted(dp.checked_names()) == ["d0", "d1", "d2", "d3"]
    dp.close()


def test_shift_click_checks_range_in_checklist(app):
    """A report/view checklist ticks the range between a click and a Shift+click."""
    from starpost.gui.views.selection_panel import _CheckList

    lst = _CheckList()
    lst.set_items(["a", "b", "c", "d", "e"], checked=False)
    lst.resize(200, 300)
    lst.show()
    _click(lst, lst.visualItemRect(lst.item(1)))
    _click(lst, lst.visualItemRect(lst.item(4)), shift=True)
    assert sorted(lst.checked()) == ["b", "c", "d", "e"]
    lst.close()


def test_shift_click_range_unchecks_when_anchor_unchecked(app):
    """Shift+click fills the range with the anchor's state, so an unchecked
    anchor clears the range."""
    from starpost.gui.views.selection_panel import _CheckList

    lst = _CheckList()
    lst.set_items(["a", "b", "c", "d"], checked=True)  # all checked
    lst.resize(200, 300)
    lst.show()
    _click(lst, lst.visualItemRect(lst.item(0)))          # uncheck a (anchor)
    _click(lst, lst.visualItemRect(lst.item(2)), shift=True)  # a..c -> unchecked
    assert sorted(lst.checked()) == ["d"]
    lst.close()


def test_shift_click_range_within_monitor_group(app):
    """In the monitor-plot tree, Shift+click ticks a range of monitors within
    the same group (siblings), not across tree levels."""
    from PySide6.QtCore import Qt

    from starpost.gui.views.selection_panel import _MonitorPlotTree

    tree = _MonitorPlotTree()
    tree.set_items({"Forces": ["m0", "m1", "m2", "m3"]})
    group = tree.topLevelItem(0)
    group.setCheckState(0, Qt.CheckState.Checked)
    group.setExpanded(True)
    tree.resize(300, 400)
    tree.show()

    # Clicking m0 checks it (and sets the range anchor); Shift+click m2 fills
    # m0..m2 to match.
    _click(tree, tree.visualItemRect(group.child(0)))
    _click(tree, tree.visualItemRect(group.child(2)), shift=True)
    checked = [
        group.child(i).text(0)
        for i in range(group.childCount())
        if group.child(i).checkState(0) == Qt.CheckState.Checked
    ]
    assert checked == ["m0", "m1", "m2"]
    tree.close()


def test_plots_tab_name_click_toggles_monitor(app):
    """In the Plots-tab monitor tree, clicking a group/monitor name (not just the
    checkbox) toggles it, and it toggles exactly once."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from starpost.gui.views.selection_panel import _MonitorPlotTree

    tree = _MonitorPlotTree()
    tree.set_items({"Forces": ["m0", "m1"]})
    group = tree.topLevelItem(0)
    tree.resize(400, 400)
    tree.show()

    def name_point(item):
        r = tree.visualItemRect(item)
        return QPoint(r.left() + 30, r.center().y())

    # Clicking the group name (not the indicator) checks it and reveals monitors.
    gp = name_point(group)
    assert not tree._on_check_indicator(group, gp)
    QTest.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, gp
    )
    assert group.checkState(0) == Qt.CheckState.Checked

    # Clicking a monitor name toggles it once (on, then off).
    child = group.child(0)
    cp = name_point(child)
    QTest.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, cp
    )
    assert child.checkState(0) == Qt.CheckState.Checked
    QTest.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, cp
    )
    assert child.checkState(0) == Qt.CheckState.Unchecked
    tree.close()


def test_express_dialog_run_disabled_without_profile(app):
    import starpost.gui.views.express_batch_dialog as ebd

    dlg = ebd.ExpressBatchDialog(None, data_sets=[], results=[], settings=None)
    assert dlg._run_btn.isEnabled() is False


def test_express_dialog_builds_config_from_profile(app, monkeypatch, tmp_path):
    from PySide6.QtCore import Qt

    import starpost.gui.views.express_batch_dialog as ebd
    from starpost.core.settings import BatchProfile

    BatchProfile(
        name="Nightly", selected_reports=["Drag"],
        report_format="XLSX", include_units=False, combined_report=False,
    ).save()

    result = _sim_result_with_data()  # sim_name "caseA"
    dlg = ebd.ExpressBatchDialog(
        None, data_sets=["caseA"], results=[result], settings=None
    )
    dlg._profile_box.setCurrentText("Nightly")
    assert dlg._run_btn.isEnabled() is True

    # Check a source.
    panel = dlg._source_panel
    panel._source_input.setCurrentIndex(panel._source_input.findData("data"))
    panel._source_window.item(0).setCheckState(Qt.CheckState.Checked)
    dlg._export_format.setCurrentIndex(dlg._export_format.findData("7z"))
    dlg._include_dataset_csv.setChecked(True)

    captured = {}
    monkeypatch.setattr(ebd, "execute_batch",
                        lambda *a, **k: captured.setdefault("cfg", a[1]) and None)
    monkeypatch.setattr(ebd.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(tmp_path)))
    monkeypatch.setattr(ebd.QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))

    dlg._run()

    cfg = captured["cfg"]
    assert cfg.reports == {"Drag"}
    assert cfg.report_format == "xlsx"
    assert cfg.include_units is False
    assert cfg.combined_report is False
    assert cfg.archive_format == "7z"
    assert cfg.include_dataset_csv is True
    assert [s.name for s in cfg.sources] == ["caseA"]
