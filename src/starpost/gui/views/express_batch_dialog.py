"""Express batch: run a saved batch profile with minimal clicks.

For users who already have a batch profile. The profile supplies the reports,
plots, scenes and report-output settings; the user only picks the sources and the
archive options, then runs. Reuses the full dialog's SourcePanel and the shared
execute_batch runner."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from starpost.core.settings import BatchProfile, list_batch_profiles
from starpost.core.starccm_runner import StarRunner
from starpost.gui.views.batch_run_dialog import SourcePanel, execute_batch


class ExpressBatchDialog(QDialog):
    def __init__(self, parent=None, *, data_sets=None, results=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Express batch")
        self.resize(620, 420)
        self._settings = settings

        # Batch profile selector (front and centre).
        self._profile_box = QComboBox()
        self._profile_box.addItems(list_batch_profiles())
        self._profile_box.setCurrentIndex(-1)  # force an explicit choice
        self._profile_box.currentIndexChanged.connect(self._sync_run_enabled)
        empty_note = QLabel(
            "No batch profiles yet — create one in Full Batch first."
        )
        empty_note.setVisible(self._profile_box.count() == 0)

        # Compact, right-aligned selector to match the full window's profile bar.
        profile_row = QHBoxLayout()
        profile_row.addStretch(1)
        profile_row.addWidget(QLabel("Batch profile"))
        profile_row.addWidget(self._profile_box)

        # Sources (no "Has similar format" — the profile already defines outputs).
        self._source_panel = SourcePanel(
            data_sets=data_sets, results=results, show_similar_format=False
        )

        # Export options live in the panel's Options column, beneath the source
        # input, rather than in a separate section.
        self._export_format = QComboBox()
        self._export_format.addItem("ZIP", "zip")
        self._export_format.addItem("7Z", "7z")
        self._include_dataset_csv = QCheckBox("Include dataset .csv")
        self._source_panel.add_option_widget(QLabel("Archive format"))
        self._source_panel.add_option_widget(self._export_format)
        self._source_panel.add_option_widget(self._include_dataset_csv)

        self._run_btn = QPushButton("Batch run")
        self._run_btn.clicked.connect(self._run)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self._run_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(profile_row)
        layout.addWidget(empty_note)
        layout.addWidget(self._source_panel, 1)
        layout.addLayout(button_row)

        self._sync_run_enabled()

    def _sync_run_enabled(self, *_args) -> None:
        """The run button is live only once a profile is chosen."""
        self._run_btn.setEnabled(bool(self._profile_box.currentText()))

    def _run(self) -> None:
        from starpost.batch.run import BatchConfig

        name = self._profile_box.currentText()
        if not name:
            return
        profile = BatchProfile.load(name)

        sources = self._source_panel.sources()
        if not sources:
            QMessageBox.warning(self, "Express batch", "No data selected.")
            return

        reports = set(profile.selected_reports)
        saved_plots = list(profile.saved_plots)
        saved_scenes = list(profile.saved_scenes)
        saved_screenplays = list(profile.saved_screenplays)
        include_dataset_csv = self._include_dataset_csv.isChecked()
        if (not reports and not saved_plots and not saved_scenes
                and not saved_screenplays and not include_dataset_csv):
            QMessageBox.warning(
                self, "Express batch",
                "Nothing to output — the selected profile is empty.",
            )
            return

        needs_exe = any(s.result is None for s in sources) or (
            bool(saved_scenes or saved_screenplays)
            and any(s.sim_file for s in sources)
        )
        if needs_exe and (self._settings is None or not self._settings.starccm_path):
            QMessageBox.warning(
                self, "Express batch",
                "Set the STAR-CCM+ executable path in Settings first.",
            )
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not out_dir:
            return
        fmt = self._export_format.currentData()
        dest = Path(out_dir) / f"starpost_batch_{datetime.now():%Y%m%d_%H%M%S}.{fmt}"
        config = BatchConfig(
            sources=sources,
            reports=reports,
            report_format=profile.report_format.lower(),
            include_units=profile.include_units,
            report_unit_system=profile.report_unit_system,
            saved_plots=saved_plots,
            saved_scenes=saved_scenes,
            saved_screenplays=saved_screenplays,
            include_dataset_csv=include_dataset_csv,
            combined_report=profile.combined_report,
            archive_format=fmt,
        )
        runner = StarRunner(self._settings) if self._settings else None
        error = execute_batch(self, config, self._settings, runner, dest)
        if error is not None:
            QMessageBox.critical(self, "Express batch failed", error)
            return
        QMessageBox.information(self, "Express batch", f"Batch written to:\n{dest}")
        self.accept()
