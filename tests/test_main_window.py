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

    dlg = BatchRunDialog()
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
