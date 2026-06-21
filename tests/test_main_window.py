"""Tests for MainWindow behaviours that don't need a real STAR-CCM+ run."""
from pathlib import Path

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


def _window(monkeypatch):
    win = mw.MainWindow(Settings())
    # Pretend a file is queued and the exe is configured, so _run_batch reaches
    # the output-folder dialog.
    monkeypatch.setattr(win.file_list, "files", lambda: [Path("sim_a.sim")])
    monkeypatch.setattr(win, "_missing_exe", lambda: False)
    started = []
    monkeypatch.setattr(win, "_start_jobs", lambda jobs, out_dir: started.append(out_dir))
    return win, started


def test_run_batch_cancelled_folder_dialog_does_not_run(app, monkeypatch):
    """Cancelling the output-folder dialog (empty return) must not start a run."""
    win, started = _window(monkeypatch)
    monkeypatch.setattr(mw.QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    win._run_batch()
    assert started == []  # nothing was launched
    win.close()


def test_run_batch_chosen_folder_starts_run(app, monkeypatch, tmp_path):
    """Choosing a folder starts the run with that folder."""
    win, started = _window(monkeypatch)
    chosen = str(tmp_path / "out")
    monkeypatch.setattr(mw.QFileDialog, "getExistingDirectory", lambda *a, **k: chosen)
    win._run_batch()
    assert started == [Path(chosen)]
    win.close()
