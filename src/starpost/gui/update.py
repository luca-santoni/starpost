"""Qt glue for the self-updater.

Wraps the UI-free backend in :mod:`starpost.core.updater` with background
threads (so the network never blocks the UI) and user prompts. The public entry
point is :func:`check_for_updates`.

Flow:
  1. Check GitHub for a newer release on a worker thread.
  2. If none: stay silent on startup, or say "up to date" for a manual check.
  3. If newer: ask the user. On yes, either download + run the installer
     (frozen Windows build) or open the releases page (source/other platforms).
  4. Download runs on a worker thread with a cancellable progress dialog; on
     success the installer is launched and the app quits so it can update.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from starpost.core import updater
from starpost.core.updater import UpdateError, UpdateInfo


class _Worker(QThread):
    """Runs a no-arg callable on a thread, emitting its result or error string."""

    ok = Signal(object)
    err = Signal(str)

    def __init__(self, fn: Callable[[], object], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D401 (QThread override)
        try:
            self.ok.emit(self._fn())
        except UpdateError as exc:
            self.err.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 (surface anything unexpected as text)
            self.err.emit(str(exc))


class _DownloadWorker(QThread):
    """Downloads the installer, emitting progress and the final path/error."""

    progress = Signal(int, int)  # bytes_done, total_bytes
    ok = Signal(object)          # Path to the downloaded installer
    err = Signal(str)

    def __init__(self, info: UpdateInfo, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._info = info
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D401 (QThread override)
        try:
            path = updater.download_asset(
                self._info,
                updater.default_download_dir(),
                progress=lambda done, total: (
                    self.progress.emit(done, total) or (not self._cancelled)
                ),
            )
            self.ok.emit(path)
        except updater.UpdateCancelled:
            self.err.emit("")  # empty == user cancelled, no error to report
        except UpdateError as exc:
            self.err.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.err.emit(str(exc))


class _UpdateFlow(QObject):
    """Owns one check→prompt→download→launch sequence and its worker threads.

    A reference is held on the parent widget (see :func:`check_for_updates`) so
    the flow and its threads are not garbage-collected mid-run.
    """

    def __init__(self, parent: QWidget, *, silent_if_current: bool) -> None:
        super().__init__(parent)
        self._parent = parent
        self._silent = silent_if_current
        self._check: Optional[_Worker] = None
        self._download: Optional[_DownloadWorker] = None
        self._progress: Optional[QProgressDialog] = None

    # --- step 1: check ---------------------------------------------------
    def start(self) -> None:
        self._check = _Worker(updater.check_for_update, self)
        self._check.ok.connect(self._on_checked)
        self._check.err.connect(self._on_check_error)
        self._check.finished.connect(self._dispose)
        self._check.start()

    def _on_check_error(self, message: str) -> None:
        if not self._silent:
            QMessageBox.warning(self._parent, "Check for updates", message)

    def _on_checked(self, info: Optional[UpdateInfo]) -> None:
        if info is None:
            if not self._silent:
                QMessageBox.information(
                    self._parent,
                    "Check for updates",
                    f"You're up to date.\n\nStarPost {updater.current_version()} "
                    "is the latest version.",
                )
            return
        self._prompt_and_apply(info)

    # --- step 2: prompt --------------------------------------------------
    def _prompt_and_apply(self, info: UpdateInfo) -> None:
        text = (
            f"StarPost {info.latest} is available "
            f"(you have {info.current}).\n\nUpdate now?"
        )
        box = QMessageBox(self._parent)
        box.setWindowTitle("Update available")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(text)
        if info.notes:
            box.setDetailedText(info.notes)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        if not updater.can_self_update():
            # Source checkout or non-Windows: send the user to the download page.
            QDesktopServices.openUrl(QUrl(info.release_url))
            return
        self._begin_download(info)

    # --- step 3: download ------------------------------------------------
    def _begin_download(self, info: UpdateInfo) -> None:
        self._progress = QProgressDialog(
            f"Downloading StarPost {info.latest}…", "Cancel", 0, 100, self._parent
        )
        self._progress.setWindowTitle("Downloading update")
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)

        self._download = _DownloadWorker(info, self)
        self._download.progress.connect(self._on_progress)
        self._download.ok.connect(self._on_downloaded)
        self._download.err.connect(self._on_download_error)
        self._progress.canceled.connect(self._download.cancel)
        self._download.start()

    def _on_progress(self, done: int, total: int) -> None:
        if self._progress is None:
            return
        if total > 0:
            self._progress.setMaximum(total)
            self._progress.setValue(done)
        else:
            self._progress.setMaximum(0)  # indeterminate when size unknown

    def _on_download_error(self, message: str) -> None:
        if self._progress is not None:
            self._progress.close()
        if message:  # empty == cancelled by the user; stay quiet
            QMessageBox.warning(self._parent, "Download failed", message)
        _detach(self._parent, self)  # nothing more pending; allow GC

    # --- step 4: apply ---------------------------------------------------
    def _on_downloaded(self, installer) -> None:
        if self._progress is not None:
            self._progress.close()
        try:
            updater.launch_installer(installer)
        except UpdateError as exc:
            QMessageBox.warning(self._parent, "Update", str(exc))
            return
        QMessageBox.information(
            self._parent,
            "Updating",
            "The installer will now update StarPost. The application will close.",
        )
        QApplication.quit()

    def _dispose(self) -> None:
        # Drop our self-reference once the check thread is done and nothing is
        # pending, allowing the flow to be garbage-collected.
        if self._download is None:
            _detach(self._parent, self)


# Active flows are pinned on their parent widget so they outlive this function.
_ATTR = "_starpost_update_flows"


def _attach(parent: QWidget, flow: _UpdateFlow) -> None:
    flows = getattr(parent, _ATTR, None)
    if flows is None:
        flows = []
        setattr(parent, _ATTR, flows)
    flows.append(flow)


def _detach(parent: QWidget, flow: _UpdateFlow) -> None:
    flows = getattr(parent, _ATTR, None)
    if flows and flow in flows:
        flows.remove(flow)


def check_for_updates(parent: QWidget, *, silent_if_current: bool) -> None:
    """Check for updates and, if one is available, offer to install it.

    ``silent_if_current=True`` (used for the automatic startup check) suppresses
    the "you're up to date" and unreachable-server messages, so it only ever
    speaks up when an update is actually available. Set it to ``False`` for the
    manual "Check for updates" button.
    """
    flow = _UpdateFlow(parent, silent_if_current=silent_if_current)
    _attach(parent, flow)
    flow.start()
