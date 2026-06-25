"""Run-batch dialog: a sequential, tabbed wizard for configuring a batch run.

Five tabs (Source → Reports → Plots → Scenes → Summary), styled like the Export
dialog's tabs. The user advances with the bottom-right **Continue** button, which
becomes **Batch run** on the final Summary tab. The tab contents and the actual
run wiring are filled in later — this is the navigation scaffold only.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from starpost.core.settings import BatchProfile, list_batch_profiles
from starpost.gui.widgets import UniformTabBar

_TAB_NAMES = ["Source", "Reports", "Plots", "Scenes", "Summary"]


class _LockedTabBar(UniformTabBar):
    """A tab bar the user cannot drive: mouse and keyboard tab changes are
    swallowed, so the active tab moves only programmatically (the Continue
    button). The tabs still render normally."""

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.ignore()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.ignore()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.ignore()


class BatchRunDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run batch")
        self.resize(660, 460)

        self._tabs = QTabWidget()
        bar = _LockedTabBar()
        bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # no keyboard focus either
        self._tabs.setTabBar(bar)
        for name in _TAB_NAMES:
            self._tabs.addTab(QWidget(), name)
        # Keep the button label in step with the active tab, however it changed.
        self._tabs.currentChanged.connect(self._sync_button)

        # Bottom-left Back button (disabled on the first tab) and bottom-right
        # Continue button (becomes "Batch run" on the last tab).
        self._back = QPushButton("Back")
        self._back.clicked.connect(self._retreat)
        self._next = QPushButton()
        self._next.clicked.connect(self._advance)
        row = QHBoxLayout()
        row.addWidget(self._back)
        row.addStretch(1)
        row.addWidget(self._next)

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_profile_bar())
        layout.addWidget(self._tabs)
        layout.addLayout(row)

        self._sync_button()

    # --- batch profiles (separate from the report/plot profiles) ----------
    def _build_profile_bar(self) -> QHBoxLayout:
        """A right-aligned 'Batch profile' selector at the top of the dialog,
        using its own separate set of profiles."""
        self._profile_box = QComboBox()
        self._refresh_profiles()
        load = QPushButton("Load")
        load.setToolTip("Load the selected batch profile")
        load.clicked.connect(self._load_profile)
        save = QPushButton("Save as…")
        save.setToolTip("Save the current batch setup as a new batch profile")
        save.clicked.connect(self._save_profile)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(QLabel("Batch profile"))
        row.addWidget(self._profile_box)
        row.addWidget(load)
        row.addWidget(save)
        return row

    def _refresh_profiles(self) -> None:
        current = self._profile_box.currentText()
        self._profile_box.clear()
        self._profile_box.addItems(list_batch_profiles())
        if current:
            self._profile_box.setCurrentText(current)

    def _load_profile(self) -> None:
        name = self._profile_box.currentText()
        if not name:
            return
        # Nothing to apply yet — the batch settings a profile captures are wired
        # in later; this just resolves the saved profile.
        BatchProfile.load(name)

    def _save_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save batch profile", "Batch profile name:"
        )
        name = name.strip() if ok else ""
        if not name:
            return
        if name in list_batch_profiles() and QMessageBox.question(
            self, "Save batch profile",
            f"A batch profile named “{name}” already exists. Overwrite it?",
        ) != QMessageBox.StandardButton.Yes:
            return
        BatchProfile(name=name).save()
        self._refresh_profiles()
        self._profile_box.setCurrentText(name)

    def _on_summary(self) -> bool:
        return self._tabs.currentIndex() == self._tabs.count() - 1

    def _sync_button(self) -> None:
        self._next.setText("Batch run" if self._on_summary() else "Continue")
        self._back.setEnabled(self._tabs.currentIndex() > 0)

    def _advance(self) -> None:
        """Continue moves to the next tab; on Summary, "Batch run" finishes (the
        run itself is wired in later)."""
        if self._on_summary():
            self.accept()
        else:
            self._tabs.setCurrentIndex(self._tabs.currentIndex() + 1)

    def _retreat(self) -> None:
        """Back moves to the previous tab (disabled on the first)."""
        idx = self._tabs.currentIndex()
        if idx > 0:
            self._tabs.setCurrentIndex(idx - 1)
