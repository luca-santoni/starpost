"""Main window: wires the panels, batch worker, and views together.

Layout:
  ┌───────────────┬───────────────────────────────┬───────────────┐
  │ FileListPanel │ Reports table / PlotView tabs │ SelectionPanel│
  ├───────────────┴───────────────────────────────┴───────────────┤
  │                      LogConsole + progress                     │
  └───────────────────────────────────────────────────────────────┘

Many handlers are scaffolded (TODOs); the goal is a runnable shell with the real
wiring points in place. No STAR-CCM+ install is needed to open the window.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QToolBar,
    QWidget,
    QVBoxLayout,
)

from starpost.batch.job import Job
from starpost.batch.queue import BatchWorker
from starpost.core.settings import Settings
from starpost.core.starccm_runner import StarRunner
from starpost.data.store import ResultStore
from starpost.gui.views.file_list import FileListPanel
from starpost.gui.views.log_console import LogConsole
from starpost.gui.views.plot_view import PlotView
from starpost.gui.views.report_table import ReportTable
from starpost.gui.views.selection_panel import SelectionPanel
from starpost.utils.logging import get_logger

log = get_logger("ui")


def _drop_zero_report_columns(df, threshold: float = 1e-5):
    """Drop report columns (wide comparison view) that are ~0 across all sims.

    A column is dropped only if every present value is below `threshold` in
    magnitude; all-missing columns and columns with any larger value are kept.
    """
    keep = []
    for col in df.columns:
        present = df[col].dropna()
        if len(present) > 0 and (present.abs() < threshold).all():
            continue
        keep.append(col)
    return df[keep]


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.setWindowTitle("starpost")
        self.resize(1280, 800)

        self.settings = settings
        self.store = ResultStore()
        self.store.load_cache()  # restore after a crash, if any

        self._thread: QThread | None = None
        self._worker: BatchWorker | None = None

        # Panels
        self.file_list = FileListPanel()
        self.selection = SelectionPanel()
        self.report_table = ReportTable(
            decimals=settings.report_decimals,
            zero_threshold=settings.zero_threshold,
        )
        self.plot_view = PlotView()
        self.plot_view.set_filter(
            settings.hide_empty_monitors, settings.monitor_zero_threshold
        )
        self.log_console = LogConsole()

        self._build_layout()
        self._build_toolbar()

        self.selection.selection_changed.connect(self._on_selection_changed)
        self._refresh_from_store()

    # --- layout ----------------------------------------------------------
    def _build_layout(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self.report_table, "Reports")
        tabs.addTab(self.plot_view, "Plots")

        center = QSplitter(Qt.Horizontal)
        center.addWidget(self.file_list)
        center.addWidget(tabs)
        center.addWidget(self.selection)
        center.setStretchFactor(1, 1)
        center.setSizes([260, 720, 300])

        outer = QSplitter(Qt.Vertical)
        outer.addWidget(center)
        outer.addWidget(self.log_console)
        outer.setStretchFactor(0, 1)
        outer.setSizes([620, 180])

        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(outer)
        self.setCentralWidget(container)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        self.addToolBar(tb)

        self._run_action = tb.addAction("Run batch", self._run_batch)
        self._stop_action = tb.addAction("Stop after current", self._stop_batch)
        self._stop_action.setEnabled(False)
        tb.addSeparator()
        tb.addAction("Export…", self._export)
        tb.addAction("Settings…", self._open_settings)
        tb.addSeparator()

        tb.addWidget(QLabel(" View: "))
        self._mode = QComboBox()
        self._mode.addItems(["Per-file", "Comparison"])
        self._mode.currentTextChanged.connect(lambda _: self._refresh_views())
        tb.addWidget(self._mode)

        tb.addWidget(QLabel(" File: "))
        self._sim_picker = QComboBox()
        self._sim_picker.currentTextChanged.connect(lambda _: self._refresh_views())
        tb.addWidget(self._sim_picker)

        tb.addWidget(QLabel(" Plot: "))
        self._plot_picker = QComboBox()
        self._plot_picker.currentTextChanged.connect(lambda _: self._render_plot())
        tb.addWidget(self._plot_picker)

    # --- batch run -------------------------------------------------------
    def _run_batch(self) -> None:
        files = self.file_list.files()
        if not files:
            QMessageBox.information(self, "starpost", "Add at least one .sim file.")
            return
        if not self.settings.starccm_path:
            QMessageBox.warning(
                self, "starpost",
                "Set the STAR-CCM+ executable path in Settings first.",
            )
            return

        out_dir = Path(
            QFileDialog.getExistingDirectory(self, "Folder for extracted data")
            or (self.settings.default_output_dir or str(Path.home()))
        )

        jobs = [Job(sim_file=f) for f in files]
        runner = StarRunner(self.settings)

        self._thread = QThread()
        self._worker = BatchWorker(jobs, runner, out_dir, self.store)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self.log_console.append)
        self._worker.progress.connect(self.log_console.set_progress)
        self._worker.sim_done.connect(lambda _r: self._refresh_from_store())
        self._worker.finished.connect(self._on_batch_finished)
        self._worker.finished.connect(self._thread.quit)

        self.log_console.clear()
        self._run_action.setEnabled(False)
        self._stop_action.setEnabled(True)
        self._thread.start()

    def _stop_batch(self) -> None:
        if self._worker:
            self._worker.request_stop()
            self._stop_action.setEnabled(False)

    def _on_batch_finished(self) -> None:
        self._run_action.setEnabled(True)
        self._stop_action.setEnabled(False)
        self._check_homogeneity()
        self._refresh_from_store()

    def _check_homogeneity(self) -> None:
        if not self.store.is_homogeneous():
            QMessageBox.warning(
                self, "Heterogeneous batch",
                "The loaded .sim files don't all share the same reports/plots. "
                "Comparison views may have gaps; selection lists show the union.",
            )

    # --- view refresh ----------------------------------------------------
    def _refresh_from_store(self) -> None:
        results = [r for r in self.store.all() if r.error is None]
        report_union = sorted({n for r in results for n in r.report_names()})
        plot_union = sorted({n for r in results for n in r.plot_names()})

        # repopulate selection only when the available set changes
        if set(report_union) != self.selection.selected_reports() or True:
            self.selection.populate(report_union, plot_union)

        self._sim_picker.blockSignals(True)
        self._sim_picker.clear()
        self._sim_picker.addItems([r.sim_name for r in results])
        self._sim_picker.blockSignals(False)

        self._sync_plot_picker()
        self._refresh_views()

    def _on_selection_changed(self) -> None:
        # A report/plot checkbox toggled: keep the plot picker in step with the
        # currently selected plots, then redraw.
        self._sync_plot_picker()
        self._refresh_views()

    def _sync_plot_picker(self) -> None:
        """Repopulate the Plot picker from the selected plots, keeping the
        current choice if it's still selected."""
        results = [r for r in self.store.all() if r.error is None]
        plot_union = sorted({n for r in results for n in r.plot_names()})
        available = [p for p in plot_union if p in self.selection.selected_plots()]
        current = self._plot_picker.currentText()
        self._plot_picker.blockSignals(True)
        self._plot_picker.clear()
        self._plot_picker.addItems(available)
        if current in available:
            self._plot_picker.setCurrentText(current)
        self._plot_picker.blockSignals(False)

    def _refresh_views(self) -> None:
        self._render_reports()
        self._render_plot()

    def _render_reports(self) -> None:
        from starpost.batch.aggregator import reports_wide_frame

        results = [r for r in self.store.all() if r.error is None]
        selected = self.selection.selected_reports()
        hide_zero = self.settings.hide_empty_reports
        if self._mode.currentText() == "Comparison":
            df = reports_wide_frame(results, selected)
            if hide_zero:
                df = _drop_zero_report_columns(df, self.settings.zero_threshold)
            self.report_table.show_dataframe(df)
        else:
            name = self._sim_picker.currentText()
            res = next((r for r in results if r.sim_name == name), None)
            if res:
                self.report_table.show_single(res, hide_zero=hide_zero)

    def _render_plot(self) -> None:
        results = [r for r in self.store.all() if r.error is None]
        plot_name = self._plot_picker.currentText()
        if not plot_name:
            # No plot selected (e.g. the last one was just unchecked): blank the
            # view rather than leaving the previously drawn plot on screen.
            self.plot_view.clear()
            return
        if self._mode.currentText() == "Comparison":
            pairs = []
            for r in results:
                p = next((p for p in r.plots if p.name == plot_name), None)
                if p:
                    pairs.append((r.sim_name, p))
            if pairs:
                self.plot_view.show_comparison(plot_name, pairs)
        else:
            name = self._sim_picker.currentText()
            res = next((r for r in results if r.sim_name == name), None)
            if res:
                p = next((p for p in res.plots if p.name == plot_name), None)
                if p:
                    self.plot_view.show_plot(p)

    # --- actions (scaffolded) -------------------------------------------
    def _export(self) -> None:
        from starpost.gui.views.export_dialog import ExportDialog

        dlg = ExportDialog(self.settings.default_output_dir, self)
        if dlg.exec():
            opts = dlg.options()
            # TODO: call batch.aggregator + core.plot_export with opts and the
            # current selection/mode. Stubbed for the scaffold.
            QMessageBox.information(
                self, "Export",
                f"TODO: export to {opts.output_dir}\n"
                f"reports_csv={opts.reports_csv}, plots={opts.plots_format}, "
                f"comparison={opts.comparison}",
            )

    def _open_settings(self) -> None:
        from starpost.gui.views.settings_dialog import SettingsDialog
        from starpost.utils.paths import settings_path

        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            log.info("Settings saved to %s", settings_path())
            self.report_table.set_decimals(self.settings.report_decimals)
            self.report_table.set_zero_threshold(self.settings.zero_threshold)
            self.plot_view.set_filter(
                self.settings.hide_empty_monitors,
                self.settings.monitor_zero_threshold,
            )
            self._refresh_views()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.store.save_cache()
        super().closeEvent(event)
