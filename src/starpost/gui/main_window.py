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
    QTabBar,
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
from starpost.gui.icons import app_icon
from starpost.gui.views.data_list import DataListPanel
from starpost.gui.views.file_list import FileListPanel
from starpost.gui.views.log_console import LogConsole
from starpost.gui.views.plot_view import PlotView
from starpost.gui.views.report_table import ReportTable
from starpost.gui.views.selection_panel import SelectionPanel
from starpost.utils.logging import get_logger

log = get_logger("ui")


class _UniformTabBar(QTabBar):
    """A tab bar whose tabs all render at one shared width (set externally), so
    the Files/Data/Plots tabs can match the Reports tab exactly."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tab_width = 0  # 0 = use each tab's natural width

    def set_tab_width(self, width: int) -> None:
        self._tab_width = width
        self.updateGeometry()

    def tabSizeHint(self, index):  # noqa: N802 (Qt override)
        size = super().tabSizeHint(index)
        if self._tab_width:
            size.setWidth(self._tab_width)
        return size


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
        self.setWindowTitle("StarPost")
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)

        self.settings = settings
        self.store = ResultStore()
        self.store.load_cache()  # restore after a crash, if any

        self._thread: QThread | None = None
        self._worker: BatchWorker | None = None

        # Panels
        self.file_list = FileListPanel(show_full_names=settings.show_full_file_names)
        self.data_list = DataListPanel()
        self.selection = SelectionPanel()
        self.report_table = ReportTable(
            decimals=settings.report_decimals,
            zero_threshold=settings.zero_threshold,
        )
        self.plot_view = PlotView()
        self.plot_view.set_filter(
            settings.hide_empty_monitors, settings.monitor_zero_threshold
        )
        self.plot_view.set_hover_options(
            settings.hover_show_monitor_name,
            settings.hover_x_decimals,
            settings.hover_y_decimals,
        )
        self.plot_view.apply_theme(settings.appearance.mode)
        # Let profiles persist which monitors are shown per plot.
        self.selection.set_monitor_provider(
            self.plot_view.monitor_selection, self.plot_view.set_monitor_selection
        )
        self.log_console = LogConsole()

        self._build_layout()
        self._build_toolbar()

        self.selection.selection_changed.connect(self._on_selection_changed)
        self.file_list.open_requested.connect(self._open_file)
        self.data_list.selection_changed.connect(self._on_data_selection_changed)
        self.data_list.clear_requested.connect(self._clear_data)
        self._refresh_from_store()

    # --- layout ----------------------------------------------------------
    def _build_layout(self) -> None:
        tabs = QTabWidget()
        tabs.setTabBar(_UniformTabBar())
        tabs.addTab(self.report_table, "Reports")
        tabs.addTab(self.plot_view, "Plots")

        # Left side: Files (the batch list) and Data (loaded results) as tabs.
        left_tabs = QTabWidget()
        left_tabs.setTabBar(_UniformTabBar())
        left_tabs.addTab(self.file_list, "Files")
        left_tabs.addTab(self.data_list, "Data")
        # Preserve right-click-to-sort, now on the Files tab itself.
        left_bar = left_tabs.tabBar()
        left_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        left_bar.customContextMenuRequested.connect(
            lambda pos: self._left_tab_menu(left_tabs, pos)
        )

        # Give every tab the width of the widest center tab (Reports) so the
        # Files/Data/Plots tabs all match it.
        center_bar = tabs.tabBar()
        reports_width = max(
            center_bar.tabSizeHint(i).width() for i in range(tabs.count())
        )
        center_bar.set_tab_width(reports_width)
        left_bar.set_tab_width(reports_width)

        center = QSplitter(Qt.Horizontal)
        center.addWidget(left_tabs)
        center.addWidget(tabs)
        center.addWidget(self.selection)
        center.setStretchFactor(1, 1)
        center.setSizes([320, 660, 300])

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

    def _left_tab_menu(self, tabs: QTabWidget, pos) -> None:
        """Right-clicking the Files or Data tab opens its sort menu."""
        bar = tabs.tabBar()
        widget = tabs.widget(bar.tabAt(pos))
        if widget is self.file_list:
            self.file_list.show_sort_menu(bar.mapToGlobal(pos))
        elif widget is self.data_list:
            self.data_list.show_sort_menu(bar.mapToGlobal(pos))

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        self.addToolBar(tb)

        self._run_action = tb.addAction("Run batch", self._run_batch)
        tb.addSeparator()
        tb.addAction("Export…", self._export)
        tb.addAction("Settings…", self._open_settings)
        tb.addSeparator()

        tb.addWidget(QLabel(" View: "))
        self._mode = QComboBox()
        self._mode.addItems(["Per-file", "Comparison"])
        self._mode.currentTextChanged.connect(lambda _: self._on_view_changed())
        tb.addWidget(self._mode)

        tb.addWidget(QLabel(" File: "))
        self._sim_picker = QComboBox()
        self._sim_picker.currentTextChanged.connect(lambda _: self._on_view_changed())
        tb.addWidget(self._sim_picker)

    # --- batch run -------------------------------------------------------
    def _busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _missing_exe(self) -> bool:
        """Warn (and return True) when the STAR-CCM+ path isn't configured."""
        if self.settings.starccm_path:
            return False
        QMessageBox.warning(
            self, "StarPost",
            "Set the STAR-CCM+ executable path in Settings first.",
        )
        return True

    def _run_batch(self) -> None:
        files = self.file_list.files()
        if not files:
            QMessageBox.information(self, "StarPost", "Add at least one .sim file.")
            return
        if self._missing_exe():
            return

        out_dir = Path(
            QFileDialog.getExistingDirectory(self, "Folder for extracted data")
            or (self.settings.default_output_dir or str(Path.home()))
        )
        self._start_jobs([Job(sim_file=f) for f in files], out_dir)

    def _open_file(self, path: Path) -> None:
        """Extract a single .sim (right-click → Open) and show its data."""
        if self._busy():
            QMessageBox.information(self, "StarPost", "A run is already in progress.")
            return
        if self._missing_exe():
            return
        # Guard against same-named duplicates: the data list is keyed by file
        # name, so loading another .sim with a name already present would shadow
        # it. Offer to overwrite the existing data instead.
        existing = [r for r in self.store.all() if Path(r.sim_path).name == path.name]
        if existing:
            if QMessageBox.question(
                self, "File already loaded",
                f"“{path.name}” has already been loaded. "
                "Would you like to overwrite it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            for r in existing:
                self.store.remove(r.sim_path)
        out_dir = Path(self.settings.default_output_dir or str(Path.home()))
        self._start_jobs([Job(sim_file=path)], out_dir)

    def _start_jobs(self, jobs: list[Job], out_dir: Path) -> None:
        """Run the given jobs on a worker thread, wiring progress to the UI."""
        if self._busy():
            return
        runner = StarRunner(self.settings)

        self._thread = QThread()
        self._worker = BatchWorker(jobs, runner, out_dir, self.store)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self.log_console.append)
        self._worker.progress.connect(self.log_console.set_progress)
        # Bound method (not a lambda) so the cross-thread signal is delivered as
        # a queued connection on the GUI thread; a lambda has no thread affinity
        # and would run the slot on the worker thread, crashing on widget access.
        self._worker.sim_done.connect(self._on_sim_done)
        self._worker.finished.connect(self._on_batch_finished)
        self._worker.finished.connect(self._thread.quit)

        self.log_console.clear()
        # Show the counter (0/N) and a sliver of progress right away, before the
        # first file finishes extracting.
        self.log_console.start_progress(len(jobs))
        self._run_action.setEnabled(False)
        self._thread.start()

    def _on_sim_done(self, _result=None) -> None:
        """A file finished extracting: refresh views on the GUI thread."""
        self._refresh_from_store()

    def _on_batch_finished(self) -> None:
        self._run_action.setEnabled(True)
        self._check_homogeneity()
        self._refresh_from_store()
        self.log_console.finish_progress()  # fade the counter/bar out shortly

    def _check_homogeneity(self) -> None:
        if not self.store.is_homogeneous():
            QMessageBox.warning(
                self, "Heterogeneous batch",
                "The loaded .sim files don't all share the same reports/plots. "
                "Comparison views may have gaps; selection lists show the union.",
            )

    def _clear_data(self) -> None:
        """Wipe all loaded sim data after a confirmation, leaving a blank workspace."""
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(
                self, "Clear data",
                "A batch is still running. Stop it before clearing data.",
            )
            return
        if QMessageBox.question(
            self, "Clear data",
            "Clear all loaded simulation data? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        # Clear extracted results only; keep the loaded .sim files so they can be
        # re-run without re-adding them.
        self.store.clear()
        self.store.save_cache()  # persist the empty state so it survives restart
        self.report_table.clear()
        self.plot_view.clear()
        self.log_console.clear()
        self._refresh_from_store()

    # --- view refresh ----------------------------------------------------
    def _report_is_empty(self, name: str, results) -> bool:
        """True when a report is ~0 in every sim that has a value for it.

        Mirrors the comparison-table column drop: a name is empty only if it has
        at least one value and all of them are below the zero threshold.
        """
        threshold = self.settings.zero_threshold
        present = [
            rep.value
            for r in results
            for rep in r.reports
            if rep.name == name and rep.value is not None
        ]
        return len(present) > 0 and all(abs(v) < threshold for v in present)

    def _emptiness_scope(self, results) -> list:
        """Which sims decide whether a report is empty for the checkbox list.

        Comparison mode judges across all loaded files; per-file mode judges
        against the currently selected file only.
        """
        if self._mode.currentText() == "Comparison":
            return results
        sel = next(
            (r for r in results if r.sim_name == self._sim_picker.currentText()), None
        )
        return [sel] if sel is not None else results

    def _available_report_names(self, results) -> list[str]:
        """Report names to offer in the checkbox list, dropping empty ones when
        Hide empty reports is enabled (scope depends on the current view mode)."""
        names = sorted({n for r in results for n in r.report_names()})
        if self.settings.hide_empty_reports:
            scope = self._emptiness_scope(results)
            names = [n for n in names if not self._report_is_empty(n, scope)]
        return names

    def _refresh_report_choices(self) -> None:
        """Update the report checkbox list for the current mode/file, keeping
        the user's selection."""
        results = [r for r in self.store.all() if r.error is None]
        self.selection.set_available_reports(self._available_report_names(results))

    def _refresh_from_store(self) -> None:
        results = [r for r in self.store.all() if r.error is None]

        # Update the file picker first so per-file emptiness uses the right file.
        self._sim_picker.blockSignals(True)
        self._sim_picker.clear()
        self._sim_picker.addItems([r.sim_name for r in results])
        self._sim_picker.blockSignals(False)

        # The Data tab mirrors the loaded results, named after their .sim files.
        self.data_list.set_entries([r.sim_name for r in results])

        report_union = self._available_report_names(results)
        plot_union = sorted({n for r in results for n in r.plot_names()})
        self.selection.populate(report_union, plot_union)

        self._refresh_views()

    def _active_results(self) -> list:
        """The loaded results whose .sim is checked in the Data tab. This is the
        set fed to the Reports/Plots views."""
        checked = set(self.data_list.checked_names())
        return [
            r for r in self.store.all() if r.error is None and r.sim_name in checked
        ]

    def _on_data_selection_changed(self) -> None:
        """A Data-tab checkbox toggled: checking 2+ files shows a comparison,
        one file shows it per-file. Drives which files the views render."""
        checked = self.data_list.checked_names()
        self._mode.blockSignals(True)
        self._sim_picker.blockSignals(True)
        if len(checked) >= 2:
            self._mode.setCurrentText("Comparison")
        elif len(checked) == 1:
            self._mode.setCurrentText("Per-file")
            self._sim_picker.setCurrentText(checked[0])
        self._mode.blockSignals(False)
        self._sim_picker.blockSignals(False)
        self._refresh_views()

    def _on_view_changed(self) -> None:
        # View mode or selected file changed: which reports count as empty can
        # differ, so refresh the checkbox list (keeping selection) then redraw.
        self._refresh_report_choices()
        self._refresh_views()

    def _on_selection_changed(self) -> None:
        # A report/plot checkbox toggled: redraw.
        self._refresh_views()

    def _selected_plot_names(self) -> list[str]:
        """The monitor plots to display: every checked one (sorted)."""
        results = self._active_results()
        plot_union = sorted({n for r in results for n in r.plot_names()})
        selected = self.selection.selected_plots()
        return [p for p in plot_union if p in selected]

    def _refresh_views(self) -> None:
        self._render_reports()
        self._render_plot()

    def _render_reports(self) -> None:
        from starpost.batch.aggregator import reports_wide_frame

        results = self._active_results()
        if not results:
            self.report_table.clear()
            return
        selected = self.selection.selected_reports()
        hide_zero = self.settings.hide_empty_reports
        if self._mode.currentText() == "Comparison":
            df = reports_wide_frame(results, selected)
            if hide_zero:
                df = _drop_zero_report_columns(df, self.settings.zero_threshold)
            # Display with sims across the top and reports down the side
            # (reports_wide_frame is sims-as-rows; transpose only for the view).
            self.report_table.show_dataframe(df.T)
        else:
            name = self._sim_picker.currentText()
            res = next((r for r in results if r.sim_name == name), results[0])
            self.report_table.show_single(
                res, hide_zero=hide_zero, selected=selected
            )

    def _render_plot(self) -> None:
        results = self._active_results()
        plot_names = self._selected_plot_names()
        if not results or not plot_names:
            # No monitor plot selected (e.g. the last one was just unchecked):
            # blank the view rather than leaving the previous plot on screen.
            self.plot_view.clear()
            return
        if self._mode.currentText() == "Comparison":
            categories = []
            for plot_name in plot_names:
                pairs = []
                for r in results:
                    p = next((p for p in r.plots if p.name == plot_name), None)
                    if p:
                        pairs.append((r.sim_name, p))
                if pairs:
                    categories.append((plot_name, pairs))
            if categories:
                self.plot_view.show_comparison(categories)
            else:
                self.plot_view.clear()
        else:
            name = self._sim_picker.currentText()
            res = next((r for r in results if r.sim_name == name), results[0])
            plots = [p for p in res.plots if p.name in plot_names]
            if plots:
                self.plot_view.show_plots(plots)
            else:
                self.plot_view.clear()

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
        # Live-preview the light/dark switch on the plot too (Cancel reverts it).
        dlg.preview_changed.connect(self.plot_view.apply_theme)
        accepted = dlg.exec()
        # Profile deletions in the dialog take effect immediately (independent of
        # Save/Cancel), so resync the profile dropdown either way.
        self.selection.refresh_profiles()
        if accepted:
            log.info("Settings saved to %s", settings_path())
            self.file_list.set_show_full_names(self.settings.show_full_file_names)
            self.report_table.set_decimals(self.settings.report_decimals)
            self.report_table.set_zero_threshold(self.settings.zero_threshold)
            self.plot_view.set_filter(
                self.settings.hide_empty_monitors,
                self.settings.monitor_zero_threshold,
            )
            self.plot_view.set_hover_options(
                self.settings.hover_show_monitor_name,
                self.settings.hover_x_decimals,
                self.settings.hover_y_decimals,
            )
            self.plot_view.apply_theme(self.settings.appearance.mode)
            # The hide-empty/threshold settings change which reports qualify as
            # empty: refresh the checkbox list (preserving the current selection).
            results = [r for r in self.store.all() if r.error is None]
            self.selection.set_available_reports(self._available_report_names(results))
            self._refresh_views()

    def createPopupMenu(self):  # noqa: N802 (Qt override)
        # Suppress the default toolbar/dock right-click menu: its only entry
        # toggles the toolbar off with no way to restore it without a restart.
        return None

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.store.save_cache()
        super().closeEvent(event)
