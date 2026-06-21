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
