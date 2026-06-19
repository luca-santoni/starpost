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
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolBar,
    QWidget,
    QVBoxLayout,
)

from starpost import __version__
from starpost.batch.job import Job
from starpost.batch.queue import BatchWorker
from starpost.core.settings import Settings
from starpost.core.starccm_runner import StarRunner
from starpost.data.store import ResultStore
from starpost.gui.icons import app_icon
from starpost.gui.widgets import UniformTabBar
from starpost.gui.views.data_list import DataListPanel
from starpost.gui.views.file_list import FileListPanel
from starpost.gui.views.log_console import LogConsole
from starpost.gui.views.plot_view import PlotView, _series_is_empty
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
        self.setWindowTitle("StarPost")
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)

        self.settings = settings
        self.store = ResultStore()
        self.store.load_cache()  # restore after a crash, if any

        self._thread: QThread | None = None
        self._worker: BatchWorker | None = None

        # Panels
        self.file_list = FileListPanel(
            show_full_names=settings.show_full_file_names,
            folder_color=settings.appearance.resolved_folder_color(),
        )
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
        self.plot_view.set_region_stats(settings.region_stats)
        self.plot_view.apply_theme(settings.appearance.mode)
        # Let profiles persist which monitors are shown per plot.
        self.selection.set_monitor_provider(
            self.plot_view.monitor_selection, self.plot_view.set_monitor_selection
        )
        # …and which region statistics are shown.
        self.selection.set_region_stats_provider(
            self.plot_view.region_stats, self._apply_region_stats
        )
        self.log_console = LogConsole()

        self._build_layout()
        self._build_toolbar()

        self.selection.selection_changed.connect(self._on_selection_changed)
        self.file_list.open_requested.connect(self._open_files)
        self.file_list.properties_requested.connect(self._show_file_properties)
        self.data_list.selection_changed.connect(self._on_data_selection_changed)
        self.data_list.properties_requested.connect(self._show_data_properties)
        self.data_list.import_requested.connect(self._import_data)
        self.data_list.export_requested.connect(self._export_data)
        self.data_list.delete_requested.connect(self._delete_selected_data)
        self.data_list.clear_requested.connect(self._clear_data)
        self._refresh_from_store()

    # --- layout ----------------------------------------------------------
    def _build_layout(self) -> None:
        tabs = QTabWidget()
        tabs.setTabBar(UniformTabBar())
        tabs.addTab(self.report_table, "Reports")
        tabs.addTab(self.plot_view, "Plots")
        # The selection panel shows only the checklist for the active centre tab:
        # Reports list on the Reports tab, Monitor plots list on the Plots tab.
        self._center_tabs = tabs
        tabs.currentChanged.connect(self._on_center_tab_changed)

        # Left side: Files (the batch list) and Data (loaded results) as tabs.
        left_tabs = QTabWidget()
        left_tabs.setTabBar(UniformTabBar())
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

    def _on_center_tab_changed(self, index: int) -> None:
        """Sync the selection panel to the active centre tab: show the Reports
        checklist for the Reports table, the Monitor plots checklist for Plots."""
        widget = self._center_tabs.widget(index)
        self.selection.set_active_section(
            "reports" if widget is self.report_table else "plots"
        )

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
        self._run_action.setToolTip(
            "Extract reports and plots from every .sim file in the list"
        )
        tb.addSeparator()
        export_action = tb.addAction("Export…", self._export)
        export_action.setToolTip("Export the selected reports and plots to files")
        settings_action = tb.addAction("Settings…", self._open_settings)
        settings_action.setToolTip("Open the application settings")

        # An expanding spacer pushes the version corner to the toolbar's far right.
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        # Right-aligned vertical stack: the version on top, with a "New update
        # available" note beneath it that stays hidden until the startup update
        # check finds a newer release (see show_update_available).
        corner = QWidget()
        corner_layout = QVBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 8, 0)
        corner_layout.setSpacing(0)
        # Grayed-out version, tied to the single version source used by the
        # About settings tab so both always agree. A faint, theme-neutral gray
        # (mid-gray with low alpha reads as muted on both light and dark).
        version_label = QLabel(f"StarPost v{__version__}")
        version_label.setStyleSheet("color: rgba(127, 127, 127, 0.55);")
        version_label.setAlignment(Qt.AlignRight)
        corner_layout.addWidget(version_label)
        # Tinted with the user's accent via the theme (objectName "updateAvailable").
        self._update_label = QLabel("New update available")
        self._update_label.setObjectName("updateAvailable")
        self._update_label.setAlignment(Qt.AlignRight)
        self._update_label.setVisible(False)
        corner_layout.addWidget(self._update_label)
        tb.addWidget(corner)

    def show_update_available(self) -> None:
        """Reveal the toolbar's "New update available" note, shown beneath the
        version. Called when the startup update check finds a newer release."""
        self._update_label.setVisible(True)

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

    def _open_files(self, paths: list[Path]) -> None:
        """Extract one or more .sim files (right-click → Open) and show their
        data. Multiple files are queued and run sequentially as a batch."""
        if not paths:
            return
        if self._busy():
            QMessageBox.information(self, "StarPost", "A run is already in progress.")
            return
        if self._missing_exe():
            return
        # The data list is keyed by file name, so re-loading a .sim whose name is
        # already present would shadow it. Rather than block the whole selection,
        # skip the already-loaded files and load only the new ones — warning first
        # when some (but not all) of the selection is already loaded.
        # Only successfully-loaded sims count as "already loaded": a failed load
        # leaves an errored entry that never shows in the Data tab, so it must
        # not block (or warn about) re-loading that file.
        loaded_names = {
            Path(r.sim_path).name for r in self.store.all() if r.error is None
        }
        new_paths = [p for p in paths if p.name not in loaded_names]
        dup = sorted({p.name for p in paths if p.name in loaded_names})
        load_paths = new_paths  # which files to actually (re)load
        if dup:
            joined = ", ".join(f"“{d}”" for d in dup)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            load_btn = None
            if not new_paths:
                # The whole selection is already loaded: the only useful action is
                # to force a reload, overwriting the existing copies.
                box.setWindowTitle("Already loaded")
                if len(dup) == 1:
                    box.setText(f"“{dup[0]}” is already loaded.")
                else:
                    box.setText(
                        f"All {len(dup)} selected files are already loaded ({joined})."
                    )
            else:
                if len(dup) == 1:
                    box.setWindowTitle("File already loaded")
                    box.setText(
                        f"“{dup[0]}” is already loaded. "
                        "Would you like to load all other new files?"
                    )
                else:
                    box.setWindowTitle("Files already loaded")
                    box.setText(
                        f"{len(dup)} files are already loaded ({joined}). "
                        "Would you like to load all other new files?"
                    )
                load_btn = box.addButton("Load new files", QMessageBox.AcceptRole)
                # Reuse the style's standard Yes-button icon (the green check seen
                # on other Yes/No dialogs) so this affirmative button matches them.
                load_btn.setIcon(
                    self.style().standardIcon(QStyle.SP_DialogYesButton)
                )
            # The force button overwrites the existing copies and loads everything.
            # ResetRole parks it in the dialog's bottom-left cluster, away from the
            # primary action. Opening a single already-loaded file reloads just
            # that one, so drop the "all".
            force_label = "Force load" if len(paths) == 1 else "Force load all"
            force_btn = box.addButton(force_label, QMessageBox.ResetRole)
            cancel_btn = box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(load_btn or force_btn)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel_btn:
                return
            if clicked is force_btn:
                # Drop the already-loaded copies so the reload replaces them.
                for r in [
                    r for r in self.store.all()
                    if Path(r.sim_path).name in set(dup)
                ]:
                    self.store.remove(r.sim_path)
                load_paths = paths
        out_dir = Path(self.settings.default_output_dir or str(Path.home()))
        self._start_jobs([Job(sim_file=p) for p in load_paths], out_dir)

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

    def _delete_selected_data(self) -> None:
        """Delete just the checked data sets from the store, after confirmation."""
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(
                self, "Delete data",
                "A batch is still running. Stop it before deleting data.",
            )
            return
        names = self.data_list.checked_names()
        if not names:
            return
        target = f"“{names[0]}”" if len(names) == 1 else f"{len(names)} data sets"
        if QMessageBox.question(
            self, "Delete data",
            f"Delete {target}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        # Drop only the selected results; the rest of the workspace is rebuilt
        # from what remains in the store.
        selected = set(names)
        for r in [r for r in self.store.all() if r.sim_name in selected]:
            self.store.remove(r.sim_path)
        self.store.save_cache()  # persist so the deletion survives restart
        self._refresh_from_store()

    def _clear_data(self) -> None:
        """Wipe all loaded sim data after a confirmation, leaving a blank workspace."""
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(
                self, "Clear Data",
                "A batch is still running. Stop it before clearing data.",
            )
            return
        if QMessageBox.question(
            self, "Clear Data",
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

    def _is_comparison(self) -> bool:
        """Comparison view when two or more files are checked in the Data tab;
        otherwise a single file is shown per-file."""
        return len(self.data_list.checked_names()) >= 2

    def _current_sim(self) -> str:
        """The single file shown in per-file mode: the first (only) checked one."""
        checked = self.data_list.checked_names()
        return checked[0] if checked else ""

    def _emptiness_scope(self, results) -> list:
        """Which sims decide whether a report is empty for the checkbox list.

        Comparison mode judges across all loaded files; per-file mode judges
        against the currently selected file only.
        """
        if self._is_comparison():
            return results
        sel = next(
            (r for r in results if r.sim_name == self._current_sim()), None
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
        one file shows it per-file. This drives both which files the views
        render and the view mode, so re-scope the report list (which reports
        count as empty depends on the mode) before redrawing."""
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
        if self._is_comparison():
            df = reports_wide_frame(results, selected)
            if hide_zero:
                df = _drop_zero_report_columns(df, self.settings.zero_threshold)
            # Display with sims across the top and reports down the side
            # (reports_wide_frame is sims-as-rows; transpose only for the view).
            self.report_table.show_dataframe(df.T)
        else:
            name = self._current_sim()
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
        if self._is_comparison():
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
            name = self._current_sim()
            res = next((r for r in results if r.sim_name == name), results[0])
            plots = [p for p in res.plots if p.name in plot_names]
            if plots:
                self.plot_view.show_plots(plots)
            else:
                self.plot_view.clear()

    # --- actions (scaffolded) -------------------------------------------
    def _show_file_properties(self, path) -> None:
        """Files tab → right-click → Properties: show the file's size and, if it
        has been extracted, its report/monitor/iteration counts."""
        from starpost.gui.views.properties_dialog import PropertiesDialog

        path = Path(path)
        target = path.resolve()
        # The store is keyed by the .sim path; match on the resolved path so a
        # differently-spelled-but-equal path still finds the extracted data.
        result = next(
            (r for r in self.store.all() if Path(r.sim_path).resolve() == target),
            None,
        )
        PropertiesDialog(path, result, self).exec()

    def _show_data_properties(self, name) -> None:
        """Data tab → right-click → Properties: show the data set's size as its
        portable CSV (what Export Data would write) plus its report/monitor/
        iteration counts."""
        from starpost.data.portable import sim_csv_size
        from starpost.gui.views.properties_dialog import PropertiesDialog

        result = next(
            (r for r in self.store.all() if r.error is None and r.sim_name == name),
            None,
        )
        if result is None:
            return
        PropertiesDialog(
            Path(result.sim_path), result, self, size_bytes=sim_csv_size(result)
        ).exec()

    def _import_data(self) -> None:
        """'Import' (Data tab): load one or more portable StarPost data CSVs
        (as written by Export Data) straight into the workspace — no .sim or
        STAR-CCM+ needed. Files that don't match the format are reported and
        skipped; any valid files in the same selection still import."""
        from starpost.data.portable import read_sim_csv

        start_dir = self.settings.default_output_dir or str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Data", start_dir, "CSV file (*.csv)"
        )
        if not paths:
            return

        # Names already loaded, mapped to their store key (sim_path), so a
        # collision can replace the existing entry even if its path differs.
        loaded: dict[str, str] = {
            r.sim_name: r.sim_path for r in self.store.all() if r.error is None
        }
        overwrite_all: bool | None = None  # None until "to all" is chosen

        imported = 0
        failed: list[str] = []
        for p in paths:
            try:
                result = read_sim_csv(p)
            except Exception:  # wrong format or otherwise unreadable
                log.exception("import failed for %s", p)
                failed.append(Path(p).name)
                continue

            name = result.sim_name
            if name in loaded:
                overwrite = overwrite_all
                if overwrite is None:
                    overwrite, overwrite_all = self._ask_overwrite_import(name)
                if not overwrite:
                    continue  # keep the loaded data set; skip this file
                # Drop the existing entry (its key may differ from the new one).
                if loaded[name] != result.sim_path:
                    self.store.remove(loaded[name])

            self.store.put(result)
            loaded[name] = result.sim_path  # later files collide with this one too
            imported += 1

        if imported:
            self.store.save_cache()  # persist so the import survives restart
            self._refresh_from_store()
            self._check_homogeneity()

        if failed:
            listed = "\n".join(f"  • {n}" for n in failed)
            if len(failed) == 1:
                msg = (
                    "The selected file failed to import because it does not "
                    f"match the format:\n\n{listed}"
                )
            else:
                msg = (
                    f"{len(failed)} files failed to import because they do not "
                    f"match the format:\n\n{listed}"
                )
            if imported:
                msg += f"\n\nThe remaining {imported} file(s) were imported."
            QMessageBox.warning(self, "Import", msg)

    def _ask_overwrite_import(self, name: str) -> tuple[bool, bool | None]:
        """Warn that ``name`` is already loaded and ask whether to overwrite it.

        Returns ``(overwrite_this, apply_to_all)`` where apply_to_all is True
        (overwrite all), False (skip all) or None (decide each one)."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Import")
        box.setText(
            f"A data set named “{name}” is already loaded.\n\n"
            "Overwrite it with the imported file?"
        )
        box.setStandardButtons(
            QMessageBox.Yes
            | QMessageBox.No
            | QMessageBox.YesToAll
            | QMessageBox.NoToAll
        )
        box.setDefaultButton(QMessageBox.No)  # the safe choice: keep what's loaded
        choice = box.exec()
        if choice == QMessageBox.YesToAll:
            return True, True
        if choice == QMessageBox.NoToAll:
            return False, False
        return choice == QMessageBox.Yes, None

    def _export_data(self) -> None:
        """'Export Data' (Data tab): open a window listing the loaded data sets
        (pre-ticked to mirror the Data tab selection) where the user picks which
        to dump to portable StarPost CSV — one re-importable file per data set."""
        from starpost.gui.views.data_export_dialog import DataExportDialog

        results = [r for r in self.store.all() if r.error is None]
        if not results:
            QMessageBox.information(self, "Export Data", "No data is loaded to export.")
            return

        dlg = DataExportDialog(
            self.settings.default_output_dir,
            [r.sim_name for r in results],
            self.data_list.checked_names(),
            results,
            self,
        )
        dlg.exec()

    def _export(self) -> None:
        from starpost.gui.views.export_dialog import ExportDialog

        # The dialog mirrors the main window: the loaded data sets (Data tab),
        # the available reports (selection panel), and the monitor groups/monitors
        # (plot view), each pre-ticked to match what is selected here; the rest of
        # the export wiring is built out in later steps.
        results = [r for r in self.store.all() if r.error is None]
        data_names = [r.sim_name for r in results]
        checked_names = self.data_list.checked_names()
        # Offer the same reports the main UI does, i.e. dropping empty ones when
        # "Hide empty reports" is on.
        report_names = self._available_report_names(results)
        checked_reports = sorted(self.selection.selected_reports())

        # Monitor groups are plots; their monitors are the plot's series. Build
        # the union of series per plot across the loaded results, dropping empty
        # monitors when "Hide empty monitors" is on (mirroring the plot view).
        hide_monitors = self.settings.hide_empty_monitors
        mon_threshold = self.settings.monitor_zero_threshold
        monitor_groups: dict[str, list[str]] = {}
        for r in results:
            for p in r.plots:
                names = monitor_groups.setdefault(p.name, [])
                for s in p.series:
                    if hide_monitors and _series_is_empty(s, mon_threshold):
                        continue
                    if s.name not in names:
                        names.append(s.name)
        checked_groups = sorted(self.selection.selected_plots())
        checked_monitors = self.plot_view.monitor_selection()

        dlg = ExportDialog(
            self.settings.default_output_dir,
            data_names,
            checked_names,
            report_names,
            checked_reports,
            monitor_groups,
            checked_groups,
            checked_monitors,
            results,
            self.settings,
            self,
        )
        dlg.exec()

    def _apply_region_stats(self, labels) -> None:
        """Apply a profile's saved region statistics. A profile that specifies
        them becomes the active selection, mirrored into settings so the
        Settings dialog reflects what the plot is actually showing; labels=None
        (the Default profile) keeps the current selection."""
        if labels is not None:
            self.settings.region_stats = list(labels)
        self.plot_view.set_region_stats(self.settings.region_stats)

    def _open_settings(self) -> None:
        from starpost.gui.views.settings_dialog import SettingsDialog
        from starpost.utils.paths import settings_path

        dlg = SettingsDialog(self.settings, self)
        # Live-preview the light/dark switch on the plot too (Cancel reverts it).
        dlg.preview_changed.connect(self.plot_view.apply_theme)
        # Live-preview the folder colour on the Files tab (Cancel reverts it).
        dlg.folder_color_changed.connect(self.file_list.set_folder_color)
        # Resetting settings is applied + saved immediately (independent of
        # Save/Cancel): push it to the views and reload the Default profile.
        dlg.defaults_reset.connect(self._on_settings_reset)
        accepted = dlg.exec()
        # Profile deletions in the dialog take effect immediately (independent of
        # Save/Cancel), so resync the profile dropdown either way.
        self.selection.refresh_profiles()
        if accepted:
            log.info("Settings saved to %s", settings_path())
            self._apply_settings_to_views()

    def _apply_settings_to_views(self) -> None:
        """Push the current settings onto every view that mirrors them. Used when
        the Settings dialog is saved and when settings are reset to defaults."""
        self.file_list.set_show_full_names(self.settings.show_full_file_names)
        self.file_list.set_folder_color(self.settings.appearance.resolved_folder_color())
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
        self.plot_view.set_region_stats(self.settings.region_stats)
        self.plot_view.apply_theme(self.settings.appearance.mode)
        # The hide-empty/threshold settings change which reports qualify as
        # empty: refresh the checkbox list (preserving the current selection).
        results = [r for r in self.store.all() if r.error is None]
        self.selection.set_available_reports(self._available_report_names(results))
        self._refresh_views()

    def _on_settings_reset(self) -> None:
        """The Settings dialog reset to defaults and saved immediately: apply the
        new settings to the views, then reload the Default profile selection."""
        self._apply_settings_to_views()
        self.selection.load_default_profile()

    def createPopupMenu(self):  # noqa: N802 (Qt override)
        # Suppress the default toolbar/dock right-click menu: its only entry
        # toggles the toolbar off with no way to restore it without a restart.
        return None

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.store.save_cache()
        super().closeEvent(event)
