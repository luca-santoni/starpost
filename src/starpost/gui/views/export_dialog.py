"""Export dialog: choose what (reports/plots) and format (CSV/JPG/PDF) + folder.

TODO: wire the chosen options to batch.aggregator (CSV) and core.plot_export
(JPG/PDF). This is a scaffold of the option surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


@dataclass
class ExportOptions:
    output_dir: Path
    reports_csv: bool
    plots_format: str          # "none" | "jpg" | "pdf"
    comparison: bool           # wide comparison CSV vs. per-file


class ExportDialog(QDialog):
    def __init__(self, default_dir: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export results")

        self._dir = QLineEdit(default_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self._dir)
        dir_row.addWidget(browse)

        self._reports_csv = QCheckBox("Report values (.csv)")
        self._reports_csv.setChecked(True)
        self._comparison = QCheckBox("Comparison (wide) layout")

        self._plots_format = QComboBox()
        self._plots_format.addItems(["None", "JPG", "PDF"])

        form = QFormLayout()
        form.addRow("Output folder", dir_row)
        form.addRow("Reports", self._reports_csv)
        form.addRow("", self._comparison)
        form.addRow("Plots", self._plots_format)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Output folder", self._dir.text())
        if folder:
            self._dir.setText(folder)

    def options(self) -> ExportOptions:
        return ExportOptions(
            output_dir=Path(self._dir.text()),
            reports_csv=self._reports_csv.isChecked(),
            plots_format=self._plots_format.currentText().lower(),
            comparison=self._comparison.isChecked(),
        )
