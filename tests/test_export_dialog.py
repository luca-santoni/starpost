"""Tests for export dialog widgets."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from starpost.gui.views.export_dialog import _MonitorTree


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _checkable_item(label: str) -> QTreeWidgetItem:
    item = QTreeWidgetItem([label])
    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    item.setCheckState(0, Qt.CheckState.Unchecked)
    return item


def _click_name(tree: _MonitorTree, item: QTreeWidgetItem) -> None:
    """Click the row's name area (well right of the checkbox indicator)."""
    rect = tree.visualItemRect(item)
    pos = QPoint(rect.right() - 8, rect.center().y())
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=pos)


def test_clicking_monitor_name_toggles_its_checkbox(app):
    """Clicking a monitor/group name (not just the tiny checkbox) selects it."""
    tree = _MonitorTree()
    tree.setHeaderHidden(True)
    group = _checkable_item("Downforce")
    tree.addTopLevelItem(group)
    monitor = _checkable_item("Front (N)")
    group.addChild(monitor)
    tree.expandAll()
    tree.resize(320, 120)
    tree.show()
    app.processEvents()

    _click_name(tree, group)
    assert group.checkState(0) == Qt.CheckState.Checked  # name click checked it
    _click_name(tree, monitor)
    assert monitor.checkState(0) == Qt.CheckState.Checked

    _click_name(tree, group)
    assert group.checkState(0) == Qt.CheckState.Unchecked  # toggles back off
    tree.deleteLater()


def test_export_dialog_seeds_legend_offset(app):
    """The legend position carried from the main window's plot is applied to the
    export preview once the Plots tab (and its preview) opens."""
    from starpost.core.settings import Settings
    from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, SimResult
    from starpost.gui.views.export_dialog import ExportDialog

    result = SimResult(
        sim_path="/c/caseA.sim",
        plots=[MonitorPlot(
            "G", [PlotSeries("A", [1, 2, 3], [1, 2, 3]),
                  PlotSeries("B", [1, 2, 3], [3, 2, 1])], kind=PlotKind.FORCE,
        )],
    )
    dlg = ExportDialog(
        data_names=["caseA"], checked_names=["caseA"],
        monitor_groups={"G": ["A", "B"]}, checked_groups=["G"],
        checked_monitors={"G": ["A", "B"]}, results=[result], settings=Settings(),
        legend_offset=[0.65, 0.25],
    )
    try:
        dlg.resize(660, 460)
        dlg.show()
        dlg._tabs.setCurrentWidget(dlg._plots_tab)  # shows + renders the preview
        for _ in range(6):
            app.processEvents()
        assert dlg._legend_seeded
        off = dlg._preview.legend_offset()
        assert abs(off[0] - 0.65) < 0.03 and abs(off[1] - 0.25) < 0.03
    finally:
        dlg.deleteLater()
