"""Run-batch dialog: a sequential, tabbed wizard for configuring a batch run.

Five tabs (Source → Reports → Plots → Scenes → Summary), styled like the Export
dialog's tabs. The user advances with the bottom-right **Continue** button, which
becomes **Batch run** on the final Summary tab. The tab contents and the actual
run wiring are filled in later — this is the navigation scaffold only.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
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
    def __init__(self, parent=None, *, data_sets=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run batch")
        self.resize(660, 460)
        self._data_sets = list(data_sets or [])  # data-set names shown in "data" mode
        self._sim_files: list[Path] = []          # .sim files added via Load File

        self._tabs = QTabWidget()
        bar = _LockedTabBar()
        bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # no keyboard focus either
        self._tabs.setTabBar(bar)
        self._tabs.addTab(self._build_source_tab(), "Source")
        for name in _TAB_NAMES[1:]:
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

    # --- Source tab -------------------------------------------------------
    def _build_source_tab(self) -> QWidget:
        """Options on the left (the source-input dropdown + a 'Has similar format'
        checkbox); on the right a window listing the source entries (checkable),
        with Load / Select All / Clear buttons beneath it."""
        tab = QWidget()

        self._source_input = QComboBox()
        self._source_input.addItem(".sim files", "sim")
        self._source_input.addItem("Loaded data sets", "data")
        self._source_input.currentIndexChanged.connect(self._refresh_source_window)
        self._has_similar_format = QCheckBox("Has similar format")  # no logic yet

        options = QVBoxLayout()
        options.addWidget(QLabel("Source input"))
        options.addWidget(self._source_input)
        options.addWidget(self._has_similar_format)
        options.addStretch(1)

        self._source_window = QListWidget()

        # Load File / Load Data Set are mutually exclusive (one per source mode);
        # Select All / Clear act on the window's checkboxes.
        self._load_file_btn = QPushButton("Load File")
        self._load_file_btn.setToolTip("Add .sim files to the source list")
        self._load_file_btn.clicked.connect(self._load_files)
        self._load_dataset_btn = QPushButton("Load Data Set")
        self._load_dataset_btn.setToolTip("Add StarPost data CSVs to the source list")
        self._load_dataset_btn.clicked.connect(self._load_data_sets)
        select_all = QPushButton("Select All")
        select_all.clicked.connect(lambda: self._set_all_source(True))
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self._set_all_source(False))

        buttons = QHBoxLayout()
        buttons.addWidget(self._load_file_btn)
        buttons.addWidget(self._load_dataset_btn)
        buttons.addStretch(1)
        buttons.addWidget(select_all)
        buttons.addWidget(clear)

        right = QVBoxLayout()
        right.addWidget(self._source_window)
        right.addLayout(buttons)

        row = QHBoxLayout(tab)
        row.addLayout(options, 1)
        row.addLayout(right, 2)

        self._refresh_source_window()
        return tab

    def _refresh_source_window(self) -> None:
        """Rebuild the right-hand window for the selected source — the loaded .sim
        files in '.sim files' mode, the data sets in 'Loaded data sets' mode —
        preserving each entry's check state, and show the matching Load button."""
        mode = self._source_input.currentData()
        self._load_file_btn.setVisible(mode == "sim")
        self._load_dataset_btn.setVisible(mode == "data")

        prev = {
            self._source_window.item(i).text(): self._source_window.item(i).checkState()
            for i in range(self._source_window.count())
        }
        self._source_window.clear()
        names = (
            [p.name for p in self._sim_files] if mode == "sim" else list(self._data_sets)
        )
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(prev.get(name, Qt.CheckState.Checked))
            self._source_window.addItem(item)

    def _set_all_source(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._source_window.count()):
            self._source_window.item(i).setCheckState(state)

    def _load_files(self) -> None:
        """Load File: add .sim files to the source list (visible in '.sim files')."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load .sim files", "", "STAR-CCM+ sim (*.sim)"
        )
        existing = {str(p) for p in self._sim_files}
        for p in paths:
            if p not in existing:
                self._sim_files.append(Path(p))
                existing.add(p)
        self._refresh_source_window()

    def _load_data_sets(self) -> None:
        """Load Data Set: add StarPost data CSVs to the source list (visible in
        'Loaded data sets')."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load StarPost data CSVs", "", "CSV file (*.csv)"
        )
        for p in paths:
            name = Path(p).stem
            if name not in self._data_sets:
                self._data_sets.append(name)
        self._refresh_source_window()

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
