"""Pick which reports/plots to view & export, with Select All + profile load/save.

Operates on the *union* of names discovered across the loaded batch (homogeneous
batches share one set; heterogeneous batches show everything with a warning).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from starpost.core.settings import Profile, list_profiles


class _CheckList(QListWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Connect once. User-driven check toggles emit `changed`; programmatic
        # updates below block signals to avoid storms and emit explicitly.
        self.itemChanged.connect(lambda _: self.changed.emit())

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # QoL: clicking anywhere on a row toggles its checkbox, not just the
        # small indicator. The indicator still toggles natively, so we only
        # toggle here when the click landed elsewhere on the row.
        pos = event.position().toPoint()
        item = self.itemAt(pos)
        if (
            item is not None
            and event.button() == Qt.LeftButton
            and bool(item.flags() & Qt.ItemIsUserCheckable)
            and not self._on_check_indicator(item, pos)
        ):
            item.setCheckState(
                Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
            )
        super().mousePressEvent(event)

    def _on_check_indicator(self, item: QListWidgetItem, pos) -> bool:
        """Whether `pos` (viewport coords) falls on the item's checkbox indicator."""
        opt = QStyleOptionViewItem()
        opt.initFrom(self)
        opt.rect = self.visualItemRect(item)
        opt.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        rect = self.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, self
        )
        return rect.contains(pos)

    def set_items(self, names: list[str], checked: bool = True) -> None:
        self.blockSignals(True)
        self.clear()
        state = Qt.Checked if checked else Qt.Unchecked
        for n in names:
            item = QListWidgetItem(n)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(state)
            self.addItem(item)
        self.blockSignals(False)

    def set_checked(self, names: set[str]) -> None:
        self.blockSignals(True)
        for i in range(self.count()):
            it = self.item(i)
            it.setCheckState(Qt.Checked if it.text() in names else Qt.Unchecked)
        self.blockSignals(False)

    def checked(self) -> list[str]:
        return [
            self.item(i).text()
            for i in range(self.count())
            if self.item(i).checkState() == Qt.Checked
        ]

    def texts(self) -> list[str]:
        return [self.item(i).text() for i in range(self.count())]

    def set_all(self, state: bool) -> None:
        self.blockSignals(True)
        s = Qt.Checked if state else Qt.Unchecked
        for i in range(self.count()):
            self.item(i).setCheckState(s)
        self.blockSignals(False)


class SelectionPanel(QWidget):
    selection_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.reports = _CheckList()
        self.plots = _CheckList()
        self.reports.changed.connect(self.selection_changed)
        self.plots.changed.connect(self.selection_changed)

        # Profiles
        self._profile_box = QComboBox()
        self._refresh_profiles()
        load_btn = QPushButton("Load")
        save_btn = QPushButton("Save as…")
        load_btn.clicked.connect(self._load_profile)
        save_btn.clicked.connect(self._save_profile)
        prof_row = QHBoxLayout()
        prof_row.addWidget(self._profile_box)
        prof_row.addWidget(load_btn)
        prof_row.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Profile"))
        layout.addLayout(prof_row)
        layout.addWidget(self._group("Reports", self.reports))
        layout.addWidget(self._group("Monitor plots", self.plots))

    def _group(self, title: str, lst: _CheckList) -> QGroupBox:
        box = QGroupBox(title)
        all_on = QPushButton("Select all")
        all_off = QPushButton("Clear")
        all_on.clicked.connect(lambda: (lst.set_all(True), self.selection_changed.emit()))
        all_off.clicked.connect(lambda: (lst.set_all(False), self.selection_changed.emit()))
        row = QHBoxLayout()
        row.addWidget(all_on)
        row.addWidget(all_off)
        v = QVBoxLayout(box)
        v.addLayout(row)
        v.addWidget(lst)
        return box

    # --- data ------------------------------------------------------------
    def populate(self, report_names: list[str], plot_names: list[str]) -> None:
        # Reports default to selected; plots default to *deselected* so the plot
        # view starts blank (rendering every monitor plot is slow with many).
        self.reports.set_items(sorted(report_names), checked=True)
        self.plots.set_items(sorted(plot_names), checked=False)

    def set_available_reports(self, report_names: list[str]) -> None:
        """Replace the available report list while preserving check state.

        Used when a setting (e.g. hide-empty-reports) changes the visible set
        without reloading data — so the user's current selection isn't lost.
        Names appearing for the first time default to checked.
        """
        prev_all = set(self.reports.texts())
        prev_checked = set(self.reports.checked())
        names = sorted(report_names)
        keep = {n for n in names if n in prev_checked or n not in prev_all}
        self.reports.set_items(names, checked=False)
        self.reports.set_checked(keep)

    def selected_reports(self) -> set[str]:
        return set(self.reports.checked())

    def selected_plots(self) -> set[str]:
        return set(self.plots.checked())

    # --- profiles --------------------------------------------------------
    def _refresh_profiles(self) -> None:
        self._profile_box.clear()
        self._profile_box.addItems(list_profiles())

    def _load_profile(self) -> None:
        name = self._profile_box.currentText()
        if not name:
            return
        prof = Profile.load(name)
        self.reports.set_checked(set(prof.reports))
        self.plots.set_checked(set(prof.plots))
        self.selection_changed.emit()

    def _save_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
        if not ok or not name.strip():
            return
        Profile(
            name=name.strip(),
            reports=sorted(self.selected_reports()),
            plots=sorted(self.selected_plots()),
        ).save()
        self._refresh_profiles()
        self._profile_box.setCurrentText(name.strip())
