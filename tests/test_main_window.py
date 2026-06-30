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
