"""Data-export window: pick which loaded data sets to dump to portable CSV.

Opened by the Data tab's "Export Data" button. It lists every loaded data set
with a checkbox, pre-ticked to mirror the Data tab's selection when it opens.
Select all / Clear sit at the top; Export at the bottom writes each ticked data
set to a portable StarPost CSV (see starpost.data.portable), prompting for a
save location per data set in turn (defaulting to the output folder, named
after the data set).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
)

from starpost.data.portable import write_sim_csv
from starpost.gui.views.data_list import _CheckList


class DataExportDialog(QDialog):
    def __init__(
        self,
        default_dir: str = "",
        data_names: list[str] | None = None,
        checked_names: list[str] | None = None,
        results=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Data")
        self.resize(360, 420)

        self._default_dir = default_dir
        # Loaded results, keyed by sim name, so a ticked row maps back to its data.
        self._results = {r.sim_name: r for r in (results or [])}

        checked = set(checked_names or [])
        self._list = _CheckList()
        self._list.setSelectionMode(_CheckList.NoSelection)
        for name in sorted(data_names or [], key=str.lower):
            item = QListWidgetItem(name)
            item.setFlags(
                (item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                & ~Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(
                Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)

        # Top: bulk selection controls.
        select_all = QPushButton("Select all")
        select_all.setToolTip("Select every data set")
        select_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        clear = QPushButton("Clear")
        clear.setToolTip("Deselect every data set")
        clear.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        top = QHBoxLayout()
        top.addWidget(select_all)
        top.addWidget(clear)
        top.addStretch(1)

        # Bottom: Cancel on the left, Export on the right. Match the top-bar
        # export dialog's Cancel, which carries the platform's red "x" icon.
        cancel = QPushButton("Cancel")
        cancel.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
        )
        cancel.setToolTip("Close without exporting")
        cancel.clicked.connect(self.reject)
        export = QPushButton("Export")
        export.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOkButton)
        )
        export.setToolTip("Write each selected data set to a CSV file")
        export.clicked.connect(self._on_export)
        bottom = QHBoxLayout()
        bottom.addWidget(cancel)
        bottom.addStretch(1)
        bottom.addWidget(export)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._list)
        layout.addLayout(bottom)

    def _set_all(self, state: Qt.CheckState) -> None:
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)

    def _checked_names(self) -> list[str]:
        return [
            self._list.item(i).text()
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _on_export(self) -> None:
        """Write each ticked data set to a portable CSV, prompting for a save
        path per data set in turn. Cancelling a prompt aborts the export."""
        names = self._checked_names()
        if not names:
            QMessageBox.information(
                self, "Export Data", "Select at least one data set to export."
            )
            return

        for name in names:
            result = self._results.get(name)
            if result is None:
                continue
            path = self._ask_save_path(name)
            if path is None:  # user cancelled — stop the sequential export
                return
            try:
                write_sim_csv(result, path)
            except Exception as exc:  # surface the write error and stop
                QMessageBox.critical(self, "Export failed", f"{name}: {exc}")
                return

        self.accept()

    def _ask_save_path(self, default_name: str):
        """Native save dialog in the output folder, pre-named after the data set
        and filtered to CSV. Returns the chosen Path (with a .csv suffix) or None
        if the user cancelled."""
        start_dir = self._default_dir or str(Path.home())
        # Pre-fill just the data set name; the CSV filter conveys the type and
        # the suffix is enforced below, so showing ".csv" here is redundant.
        start = str(Path(start_dir) / default_name)
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Export Data", start, "CSV file (*.csv)"
        )
        if not chosen:
            return None
        path = Path(chosen)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        return path
