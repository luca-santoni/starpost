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
    dlg._source_input.setCurrentIndex(dlg._source_input.findData("data"))
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
    # From Summary, "Batch run" accepts.
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
        QEvent.Type.MouseButtonPress, target, Qt.MouseButton.LeftButton,
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
    win = dlg._source_window
    assert dlg._source_input.currentData() == "sim" and win.count() == 0  # blank

    dlg._source_input.setCurrentIndex(dlg._source_input.findData("data"))
    assert [win.item(i).text() for i in range(win.count())] == ["caseA", "caseB"]
    assert all(
        win.item(i).flags() & Qt.ItemFlag.ItemIsUserCheckable
        and win.item(i).checkState() == Qt.CheckState.Checked
        for i in range(win.count())
    )

    dlg._source_input.setCurrentIndex(dlg._source_input.findData("sim"))
    assert win.count() == 0  # back to blank
    dlg.close()


def test_batch_run_dialog_source_buttons(app, monkeypatch):
    """Load File/Load Data Set toggle with the source mode and add entries;
    Select All / Clear flip the window's checkboxes."""
    from PySide6.QtCore import Qt

    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog(data_sets=["caseA"])
    win = dlg._source_window
    # .sim mode: Load File shown, Load Data Set hidden
    assert not dlg._load_file_btn.isHidden() and dlg._load_dataset_btn.isHidden()
    monkeypatch.setattr(
        brd.QFileDialog, "getOpenFileNames",
        lambda *a, **k: (["/cases/a.sim", "/cases/b.sim"], ""),
    )
    dlg._load_files()
    assert [win.item(i).text() for i in range(win.count())] == ["a.sim", "b.sim"]

    # data mode: Load Data Set shown, Load File hidden
    dlg._source_input.setCurrentIndex(dlg._source_input.findData("data"))
    assert dlg._load_file_btn.isHidden() and not dlg._load_dataset_btn.isHidden()
    monkeypatch.setattr(
        brd.QFileDialog, "getOpenFileNames", lambda *a, **k: (["/x/extra.csv"], "")
    )
    dlg._load_data_sets()
    assert "extra" in [win.item(i).text() for i in range(win.count())]

    # Clear unchecks all; Select All re-checks all
    dlg._set_all_source(False)
    assert all(
        win.item(i).checkState() == Qt.CheckState.Unchecked for i in range(win.count())
    )
    dlg._set_all_source(True)
    assert all(
        win.item(i).checkState() == Qt.CheckState.Checked for i in range(win.count())
    )
    dlg.close()


def test_batch_run_dialog_no_source_warns(app, monkeypatch):
    """Continue on the Source tab with nothing selected warns and stays put."""
    import starpost.gui.views.batch_run_dialog as brd

    dlg = brd.BatchRunDialog(data_sets=["caseA"])
    dlg._source_input.setCurrentIndex(dlg._source_input.findData("data"))
    dlg._set_all_source(False)  # uncheck the only data set

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
    assert dlg._has_similar_format.isEnabled()  # .sim mode (default)
    dlg._source_input.setCurrentIndex(dlg._source_input.findData("data"))
    assert not dlg._has_similar_format.isEnabled()  # grayed in data mode
    dlg._source_input.setCurrentIndex(dlg._source_input.findData("sim"))
    assert dlg._has_similar_format.isEnabled()  # re-enabled back in .sim mode
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
    dlg._load_files()
    dlg._has_similar_format.setChecked(True)

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
    assert [p.name for p in dlg._sim_files] == ["a.sim", "b.sim"]
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
    dlg._source_input.setCurrentIndex(dlg._source_input.findData("data"))
    win = dlg._source_window
    item = win.item(0)
    assert item.checkState() == Qt.CheckState.Checked

    rect = win.visualItemRect(item)
    # Click in the row's text area (well right of the checkbox indicator).
    point = QPointF(rect.right() - 4, rect.center().y())
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, point, Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    win.mousePressEvent(press)
    assert item.checkState() == Qt.CheckState.Unchecked  # toggled by the row click

    # Selecting a row then clicking empty space clears the selection.
    win.setCurrentRow(0)
    assert win.selectedItems()
    empty = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(5000, 5000), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    win.mousePressEvent(empty)
    assert not win.selectedItems() and win.currentItem() is None
    dlg.close()


def test_batch_run_dialog_reports_tab(app):
    """Reports tab: the window lists every report (all checked); options offer the
    same file formats as export plus Include units / Separate files."""
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
    assert not dlg._report_separate_files.isChecked()
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
    ] == ["zip", "7z", "rar"]
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
