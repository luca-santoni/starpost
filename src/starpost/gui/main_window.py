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

from PySide6.QtCore import QEvent, Qt, QThread, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolButton,
    QWidget,
    QVBoxLayout,
)

from starpost import __version__
from starpost.batch.job import Job
from starpost.batch.queue import BatchWorker, SceneRenderWorker, ScreenplayRecordWorker
from starpost.core.settings import Settings
from starpost.core.starccm_runner import StarRunner
from starpost.data.models import PlotKind
from starpost.data.store import ResultStore
from starpost.gui import theme
from starpost.gui.icons import app_icon, logo_pixmap, menu_icon
from starpost.gui.widgets import BarMenu, BarMenuButton, UniformTabBar
from starpost.gui import shortcuts
from starpost.gui.views.data_list import DataListPanel
from starpost.gui.views.file_list import FileListPanel
from starpost.gui.views.log_console import LogConsole
from starpost.gui.views.report_table import ReportTable
from starpost.gui.views.scene_view import SceneView
from starpost.gui.views.screenplay_view import ScreenplayView
from starpost.gui.views.selection_panel import SelectionPanel
from starpost.gui.views.title_bar import (
    CaptionButton,
    FramelessResizeFilter,
    TitleToolBar,
)
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
        # Frameless: the window controls live in a custom title bar (see
        # _build_toolbar / TitleBar), STAR-CCM+ style.
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.resize(1280, 800)

        self.settings = settings
        self.store = ResultStore()
        # Restoring the crash-recovery cache can take a few hundred ms for a
        # large workspace; deferred to the first event-loop pass (which runs
        # before any user input) so it doesn't delay the window appearing.
        QTimer.singleShot(0, self._load_cached_results)

        self._thread: QThread | None = None
        self._worker: BatchWorker | None = None
        # Separate thread/worker for on-demand scene rendering (Scenes tab → Run).
        self._render_thread: QThread | None = None
        self._render_worker: SceneRenderWorker | None = None
        # Whether the Scenes "rendering is expensive" warning has shown this
        # session (shown at most once per run, unless permanently dismissed).
        self._scenes_warning_shown = False
        # The media paths last drawn in the scene gallery, so it is only rebuilt
        # when the set of stills actually changes (None = stale, force a rebuild).
        self._scene_gallery_paths: list[str] | None = None
        # Separate thread/worker for on-demand screenplay recording
        # (Screenplays tab → Record). Mirrors the scene render pair above.
        self._record_thread: QThread | None = None
        self._record_worker: ScreenplayRecordWorker | None = None
        # Job/frame counters for the recording progress bar (frames advance
        # the bar fractionally between per-checkout job ticks).
        self._record_jobs_done = 0
        self._record_jobs_total = 0
        # Whether the Screenplays "recording is expensive" warning has shown
        # this session, and the movie paths last drawn in its gallery.
        self._screenplays_warning_shown = False
        self._screenplay_gallery_paths: list[str] | None = None
        # Whether the plot must redraw when the Plots tab is next shown (its
        # render is skipped while the tab is hidden — see _render_plot).
        self._plot_stale = False
        # Coalesces bursts of checkbox changes (e.g. a Shift+click range tick,
        # which fires one change per item) into a single view refresh, run once
        # the burst's events have been processed (see _schedule_refresh).
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self._run_scheduled_refresh)
        self._rescope_pending = False

        # Panels
        self.file_list = FileListPanel(
            show_full_names=settings.show_full_file_names,
            folder_color=settings.appearance.resolved_folder_color(),
            node_color=settings.appearance.resolved_node(),
            accent=settings.appearance.accent,
        )
        self.data_list = DataListPanel(
            folder_color=settings.appearance.resolved_folder_color()
        )
        self.selection = SelectionPanel()
        # Restore the remembered Scenes/Screenplays "Saved views" divider splits.
        self.selection.set_saved_view_splits(settings.saved_view_splits)
        self.report_table = ReportTable(
            decimals=settings.report_decimals,
            zero_threshold=settings.zero_threshold,
        )
        self.scene_view = SceneView()
        self.screenplay_view = ScreenplayView()
        # The plot view is built lazily (see the plot_view property): it drags
        # in pyqtgraph + numpy (~0.3 s of imports), which shouldn't sit between
        # launch and the window appearing. Until then its tab holds a bare
        # placeholder; the warm-up timer below builds the real view right after
        # the window first paints, long before a human can reach the Plots tab.
        self._plot_view = None
        # The Settings dialog is built lazily on first open and then reused (its
        # ~12 pages are costly to construct); see _open_settings.
        self._settings_dialog = None
        # Let profiles persist which region statistics are shown. (A lambda, so
        # merely wiring the provider doesn't build the plot view.)
        self.selection.set_region_stats_provider(
            lambda: self.plot_view.region_stats(), self._apply_region_stats
        )
        # Let the panel's monitor swatches reflect/edit the plot's line colours.
        self.selection.set_plot_color_provider(
            lambda: sorted(r.sim_name for r in self._active_results()),
            self._plot_color_getter,
            self._plot_color_setter,
        )
        self.log_console = LogConsole()

        self._build_layout()
        self._build_toolbar()
        self._init_shortcuts()

        # Resize the frameless window by pressing near an edge (app-wide filter,
        # since child widgets otherwise swallow the edge mouse events).
        self._resize_filter = FramelessResizeFilter(self)
        QApplication.instance().installEventFilter(self._resize_filter)

        self.selection.selection_changed.connect(self._on_selection_changed)
        self.selection.run_scenes_requested.connect(self._run_scenes)
        self.selection.clear_scenes_requested.connect(self._clear_scenes)
        self.selection.record_screenplays_requested.connect(
            self._record_screenplays
        )
        self.selection.clear_screenplays_requested.connect(
            self._clear_screenplays
        )
        self.file_list.open_requested.connect(self._open_files)
        self.file_list.properties_requested.connect(self._show_file_properties)
        self.data_list.selection_changed.connect(self._on_data_selection_changed)
        self.data_list.properties_requested.connect(self._show_data_properties)
        self.data_list.folder_properties_requested.connect(
            self._show_data_folder_properties
        )
        self.data_list.remove_requested.connect(self._delete_data_names)
        self.data_list.clear_requested.connect(self._clear_data)
        self._refresh_from_store()
        # Warm up the plot view during the first idle moment after the window
        # paints (and after the deferred cache load above, scheduled earlier),
        # so its heavy imports never show up as a hitch on first use.
        QTimer.singleShot(0, lambda: self.plot_view)

    @property
    def plot_view(self):
        """The monitor-plot view, created on first use (see __init__) and slotted
        into the Plots tab's placeholder. Configured from the current settings at
        build time, exactly as the eager construction used to."""
        if self._plot_view is None:
            from starpost.gui.views.plot_view import PlotView

            s = self.settings
            pv = PlotView()
            pv.set_filter(s.hide_empty_monitors, s.monitor_zero_threshold)
            pv.set_hover_options(
                s.hover_show_monitor_name, s.hover_x_decimals, s.hover_y_decimals
            )
            pv.set_region_stats(s.region_stats)
            pv.set_smooth_width(s.moving_average_width)
            pv.set_text_scale(s.appearance.text_scale)
            pv.apply_theme(s.appearance.mode)
            # The per-monitor selection lives in the selection panel's plot
            # tree, so the plot view's own under-plot category dropdowns are
            # hidden; the panel drives what's drawn (applied in _render_plot).
            pv.set_category_controls_visible(False)
            self._plot_view = pv
            self._plot_tab_layout.addWidget(pv)
        return self._plot_view

    def _load_cached_results(self) -> None:
        """Restore results from the crash-recovery cache (deferred from
        __init__, see there) and populate the views when it held anything. A
        cache that fails to parse is logged and skipped rather than blocking
        the launch — it's only recovery data; the .sim files still exist."""
        try:
            self.store.load_cache()
        except Exception:
            log.exception("failed to load the results cache; starting empty")
            return
        if self.store.all():
            self._refresh_from_store()

    # --- layout ----------------------------------------------------------
    def _build_layout(self) -> None:
        tabs = QTabWidget()
        tabs.setTabBar(UniformTabBar())
        tabs.addTab(self.report_table, "Reports")
        # The Plots page is a bare container the lazily-built plot view lands
        # in (see the plot_view property) — tab checks compare against this.
        self._plot_tab = QWidget()
        self._plot_tab_layout = QVBoxLayout(self._plot_tab)
        self._plot_tab_layout.setContentsMargins(0, 0, 0, 0)
        tabs.addTab(self._plot_tab, "Plots")
        tabs.addTab(self.scene_view, "Scenes")
        tabs.addTab(self.screenplay_view, "Screenplays")
        tabs.setTabToolTip(0, shortcuts.hint("Switch to Reports", "tab_reports"))
        tabs.setTabToolTip(1, shortcuts.hint("Switch to Plots", "tab_plots"))
        tabs.setTabToolTip(2, shortcuts.hint("Switch to Scenes", "tab_scenes"))
        tabs.setTabToolTip(3, shortcuts.hint("Switch to Screenplays", "tab_screenplays"))
        # The selection panel shows only the checklist for the active centre tab:
        # Reports list on Reports, Monitor plots on Plots, Scenes on Scenes.
        self._center_tabs = tabs
        tabs.currentChanged.connect(self._on_center_tab_changed)

        # Left side: Files (the batch list) and Data (loaded results) as tabs.
        left_tabs = QTabWidget()
        left_tabs.setTabBar(UniformTabBar())
        left_tabs.addTab(self.file_list, "Files")
        left_tabs.addTab(self.data_list, "Data")
        left_tabs.setTabToolTip(0, shortcuts.hint("Switch to Files", "tab_files"))
        left_tabs.setTabToolTip(1, shortcuts.hint("Switch to Data", "tab_data"))
        self._left_tabs = left_tabs
        # Preserve right-click-to-sort, now on the Files tab itself.
        left_bar = left_tabs.tabBar()
        left_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        left_bar.customContextMenuRequested.connect(
            lambda pos: self._left_tab_menu(left_tabs, pos)
        )

        # Give every tab the width of the widest tab (Reports) so the
        # Files/Data/Plots tabs all match it. Linked so the shared width tracks
        # the font (it grows with the Appearance text-size setting, not clips).
        center_bar = tabs.tabBar()
        center_bar.link(left_bar)

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

    def _init_shortcuts(self) -> None:
        """App-wide keyboard shortcuts. Tab keys always fire; the contextual
        keys act on the active centre tab. The Run-batch menu actions carry
        their own shortcuts (see _build_toolbar), so they are not bound here."""
        def bind(shortcut_id: str, slot) -> None:
            sc = QShortcut(QKeySequence(shortcuts.key(shortcut_id)), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)

        bind("tab_files", lambda: self._left_tabs.setCurrentIndex(0))
        bind("tab_data", lambda: self._left_tabs.setCurrentIndex(1))
        bind("tab_reports", lambda: self._center_tabs.setCurrentIndex(0))
        bind("tab_plots", lambda: self._center_tabs.setCurrentIndex(1))
        bind("tab_scenes", lambda: self._center_tabs.setCurrentIndex(2))
        bind("tab_screenplays", lambda: self._center_tabs.setCurrentIndex(3))
        bind("select_all", self.selection.click_select_all)
        bind("clear_selection", self.selection.click_clear_selection)
        bind("run_render", self.selection.click_run)
        bind("smooth", self._shortcut_smooth)

    def _shortcut_smooth(self) -> None:
        """Alt+Shift+S: toggle Smooth data, only while the Plots tab shows."""
        if self._center_tabs.currentWidget() is self._plot_tab:
            self.plot_view.toggle_smooth()

    def _on_center_tab_changed(self, index: int) -> None:
        """Sync the selection panel to the active centre tab: the Reports
        checklist for the Reports table, the Scenes checklist for the Scenes
        gallery, the Monitor plots checklist otherwise."""
        widget = self._center_tabs.widget(index)
        if widget is self.report_table:
            section = "reports"
        elif widget is self.scene_view:
            section = "scenes"
        elif widget is self.screenplay_view:
            section = "screenplays"
        else:
            section = "plots"
        self.selection.set_active_section(section)
        if section == "scenes":
            # Build the gallery now that it's visible (deferred while hidden).
            self._render_scenes_view()
            self._maybe_warn_scenes()
        elif section == "screenplays":
            # Build the gallery now that it's visible (deferred while hidden).
            self._render_screenplays_view()
            self._maybe_warn_screenplays()
        elif widget is self._plot_tab and self._plot_stale:
            # Redraw now that it's visible (renders are skipped while hidden),
            # and bring the panel's monitor swatches back in step with it.
            self._render_plot()
            self.selection.refresh_monitor_swatches()

    def _maybe_warn_scenes(self) -> None:
        """First time the Scenes tab is opened this session, warn that rendering
        is heavy. A "Do not show this again" tick suppresses it for good."""
        if self._scenes_warning_shown or not self.settings.show_scenes_warning:
            return
        self._scenes_warning_shown = True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Scenes")
        box.setText(
            "Rendering scenes is very computationally expensive.\n\n"
            "It is not recommended on systems with less than 16 GB of system "
            "memory. Closing other programs on your computer first is recommended "
            "to prevent memory related errors."
        )
        box.setStandardButtons(QMessageBox.Ok)
        # Use the style's green circled checkmark (the Yes-button icon) on OK,
        # matching the affirmative buttons elsewhere in the app.
        box.button(QMessageBox.Ok).setIcon(
            self.style().standardIcon(QStyle.SP_DialogYesButton)
        )
        dont_show = QCheckBox("Do not show this again")
        box.setCheckBox(dont_show)
        box.exec()
        if dont_show.isChecked():
            self.settings.show_scenes_warning = False
            self.settings.save()

    def _maybe_warn_screenplays(self) -> None:
        """First time the Screenplays tab is opened this session, warn that
        recording is heavy. Shares the scenes warning's "do not show again"
        setting — both gate the same expensive rendering path."""
        if (
            self._screenplays_warning_shown
            or not self.settings.show_scenes_warning
        ):
            return
        self._screenplays_warning_shown = True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Screenplays")
        box.setText(
            "Recording screenplays is very computationally expensive. A "
            "movie can take several minutes to fully render.\n\n"
            "It is not recommended on systems with less than 32 GB of system "
            "memory. Closing other programs on your computer first is "
            "recommended to prevent memory related errors."
        )
        box.setStandardButtons(QMessageBox.Ok)
        box.button(QMessageBox.Ok).setIcon(
            self.style().standardIcon(QStyle.SP_DialogYesButton)
        )
        dont_show = QCheckBox("Do not show this again")
        box.setCheckBox(dont_show)
        box.exec()
        if dont_show.isChecked():
            self.settings.show_scenes_warning = False
            self.settings.save()

    def _left_tab_menu(self, tabs: QTabWidget, pos) -> None:
        """Right-clicking the Files or Data tab opens its sort menu."""
        bar = tabs.tabBar()
        widget = tabs.widget(bar.tabAt(pos))
        if widget is self.file_list:
            self.file_list.show_sort_menu(bar.mapToGlobal(pos))
        elif widget is self.data_list:
            self.data_list.show_sort_menu(bar.mapToGlobal(pos))

    def _build_toolbar(self) -> None:
        # A single fixed top bar (STAR-CCM+ style): the badge + menu items on the
        # left, then the version and the window buttons on the right, all in one
        # line. The bar is also the frameless window's drag handle (TitleToolBar).
        tb = TitleToolBar(self, "Main")
        tb.setObjectName("mainToolBar")
        self._toolbar = tb
        self.addToolBar(tb)

        # StarPost badge in the corner, echoing STAR-CCM+'s menu-bar logo. Scaled
        # to the menu-item height so it sits flush with the row.
        self._toolbar_logo = QLabel()
        self._toolbar_logo.setObjectName("toolbarLogo")
        self._toolbar_logo.setPixmap(
            logo_pixmap().scaledToHeight(32, Qt.TransformationMode.SmoothTransformation)
        )
        self._toolbar_logo.setContentsMargins(4, 0, 10, 0)
        tb.addWidget(self._toolbar_logo)

        # File menu: toolbar-level access to the Files tab's add dialogs and
        # the Data tab's portable-CSV import/export — same slots, second entry
        # point. Click-opens like Run batch.
        self._file_button = BarMenuButton()
        self._file_button.setObjectName("fileMenuButton")
        self._file_button.setText("File")
        self._file_button.setAutoRaise(True)
        self._file_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._file_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._file_button.setToolTip(
            "Add .sim files or folders, import or export portable data CSVs"
        )
        file_menu = BarMenu(self._file_button, owner=self._file_button, sibling_bar=tb)
        # Built with an explicit QMenu(parent) + addMenu(menu) rather than the
        # addMenu(title) factory: the factory's returned QMenu has no Python
        # reference of its own, and PySide6 deletes its C++ object once the
        # local variable here goes out of scope, despite the QObject parent
        # link — leaving a dangling "Add" submenu.
        add_menu = QMenu("Add", file_menu)
        add_files_act = add_menu.addAction(
            shortcuts.menu_label("Files…"), self.file_list.add_files_dialog
        )
        add_files_act.setShortcut(QKeySequence(shortcuts.key("add_files")))
        add_folder_act = add_menu.addAction(
            shortcuts.menu_label("Folder…"), self.file_list.add_folder_dialog
        )
        add_folder_act.setShortcut(QKeySequence(shortcuts.key("add_folder")))
        # Same rule as the Run batch actions below: an action that lives only
        # in a hidden popup menu never matches its shortcut, so add both to
        # the window to keep the keys active app-wide.
        self.addAction(add_files_act)
        self.addAction(add_folder_act)
        file_menu.addMenu(add_menu)
        import_act = file_menu.addAction(
            shortcuts.menu_label("Import data…"), self._import_data
        )
        import_act.setShortcut(QKeySequence(shortcuts.key("import_data")))
        export_act = file_menu.addAction(
            shortcuts.menu_label("Export data…"), self._export_data
        )
        export_act.setShortcut(QKeySequence(shortcuts.key("export_data")))
        self.addAction(import_act)
        self.addAction(export_act)
        self._file_button.setMenu(file_menu)
        self._file_menu = file_menu
        tb.addWidget(self._file_button)

        self._run_button = BarMenuButton()
        self._run_button.setObjectName("runBatchButton")
        self._run_button.setText("Run batch")
        self._run_button.setAutoRaise(True)
        self._run_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._run_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._run_button.setToolTip(
            "Run a batch export: Full Batch (full wizard) or Express batch "
            "(run a saved profile)"
        )
        run_menu = BarMenu(self._run_button, owner=self._run_button, sibling_bar=tb)
        full_act = run_menu.addAction(shortcuts.menu_label("Full Batch"), self._run_batch)
        full_act.setShortcut(QKeySequence(shortcuts.key("batch_full")))
        express_act = run_menu.addAction(
            shortcuts.menu_label("Express batch"), self._run_express_batch
        )
        express_act.setShortcut(QKeySequence(shortcuts.key("batch_express")))
        # An action that lives only in a hidden popup menu never matches its
        # shortcut; adding it to the window keeps the keys active app-wide.
        self.addAction(full_act)
        self.addAction(express_act)
        self._run_button.setMenu(run_menu)
        tb.addWidget(self._run_button)

        # Glyph icons beside the dropdown entries (STAR-CCM+ menu style), tinted
        # to the theme; re-tinted on theme change (_apply_settings_to_views).
        self._menu_icon_actions = [
            (add_menu.menuAction(), "add"),
            (add_files_act, "add-files"),
            (add_folder_act, "add-folder"),
            (import_act, "import"),
            (export_act, "export"),
            (full_act, "batch-full"),
            (express_act, "batch-express"),
        ]
        self._refresh_menu_icons()
        export_action = tb.addAction("Export…", self._export)
        export_action.setToolTip("Export the selected reports and plots to files")
        settings_action = tb.addAction("Settings…", self._open_settings)
        settings_action.setToolTip("Open the application settings")

        # An expanding spacer pushes the right-hand cluster (update note, version,
        # window buttons) to the far end of the bar. Transparent so it shows the
        # bar colour, not the (slightly lighter) global window background.
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setStyleSheet("background: transparent;")
        tb.addWidget(spacer)

        # "New update available" note (accent-tinted via the theme), hidden until
        # the startup update check finds a newer release (see show_update_available).
        self._update_label = QLabel("New update available")
        self._update_label.setObjectName("updateAvailable")
        self._update_label.setVisible(False)
        tb.addWidget(self._update_label)

        # Version, just left of the window buttons so the cluster lines up above
        # the right-hand panel.
        self._version_label = QLabel(f"StarPost v{__version__}")
        self._version_label.setObjectName("titleVersion")
        self._version_label.setContentsMargins(12, 0, 12, 0)
        tb.addWidget(self._version_label)

        # Integrated minimise / maximise / close, flush to the right edge.
        self._btn_min = CaptionButton("min")
        self._btn_min.setObjectName("winMin")
        self._btn_min.setToolTip("Minimise")
        self._btn_max = CaptionButton("max")
        self._btn_max.setObjectName("winMax")
        self._btn_max.setToolTip("Maximise")
        self._btn_close = CaptionButton("close")
        self._btn_close.setObjectName("winClose")
        self._btn_close.setToolTip("Close")
        for b in (self._btn_min, self._btn_max, self._btn_close):
            tb.addWidget(b)
        self._btn_min.clicked.connect(self.showMinimized)
        self._btn_max.clicked.connect(self._toggle_maximized)
        self._btn_close.clicked.connect(self.close)

    def _refresh_menu_icons(self) -> None:
        """(Re)tint the dropdown menu glyphs to the current theme: the palette's
        subtle colour normally, the accent's contrast colour on the highlighted
        row (whose background is the accent), the disabled grey when greyed."""
        colors = theme.palette(self.settings.appearance.mode)
        on_accent = theme.contrast_color(
            theme.normalize_accent(self.settings.appearance.accent)
        )
        for act, kind in self._menu_icon_actions:
            act.setIcon(menu_icon(kind, colors["subtle"], on_accent, colors["dis_text"]))

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event) -> None:
        """Keep the maximise button's glyph in sync with the window state."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(
            self, "_btn_max"
        ):
            self._btn_max.set_kind("restore" if self.isMaximized() else "max")

    def show_update_available(self) -> None:
        """Reveal the toolbar's "New update available" note. Called when the
        startup update check finds a newer release."""
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
        """Open the run-batch dialog (a sequential, tabbed wizard). The run itself
        is wired in later."""
        from starpost.gui.views.batch_run_dialog import BatchRunDialog

        results = [r for r in self.store.all() if r.error is None]
        data_sets = [r.sim_name for r in results]
        report_names = sorted({n for r in results for n in r.report_names()})
        monitor_groups = self._monitor_groups_union(results)
        residual_groups = self._residual_group_names(results)
        BatchRunDialog(
            self, data_sets=data_sets, report_names=report_names,
            monitor_groups=monitor_groups, residual_groups=residual_groups,
            results=results, settings=self.settings,
        ).exec()

    def _run_express_batch(self) -> None:
        """Open the Express batch dialog — run a saved batch profile quickly."""
        from starpost.gui.views.express_batch_dialog import ExpressBatchDialog

        results = [r for r in self.store.all() if r.error is None]
        data_sets = [r.sim_name for r in results]
        ExpressBatchDialog(
            self, data_sets=data_sets, results=results, settings=self.settings,
        ).exec()

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
        self._run_button.setEnabled(False)
        self._thread.start()

    def _on_sim_done(self, _result=None) -> None:
        """A file finished extracting: refresh views on the GUI thread."""
        self._refresh_from_store()

    def _on_batch_finished(self) -> None:
        self._run_button.setEnabled(True)
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

    # --- scene rendering -------------------------------------------------
    def _render_busy(self) -> bool:
        return (
            self._render_thread is not None and self._render_thread.isRunning()
        )

    def _record_busy(self) -> bool:
        return self._record_thread is not None and self._record_thread.isRunning()

    def _run_scenes(self) -> None:
        """Scenes tab → Run: render the ticked scenes of the ticked data sets to
        stills. Independent of the numeric batch and of Run batch."""
        if self._busy() or self._render_busy() or self._record_busy():
            QMessageBox.information(self, "StarPost", "A run is already in progress.")
            return
        if self._missing_exe():
            return
        scenes = self.selection.selected_scenes()
        if not scenes:
            QMessageBox.information(
                self, "Scenes", "Select at least one scene to render."
            )
            return
        # Render renders one data set at a time: require exactly one ticked in the
        # Data tab (rendering is heavy and the output is per-.sim).
        results = self._active_results()
        if not results:
            QMessageBox.information(
                self, "Scenes", "Tick a data set in the Data tab first."
            )
            return
        if len(results) > 1:
            QMessageBox.warning(
                self, "Scenes",
                "Select only one data set to render. Untick the others in the "
                "Data tab, then press Run.",
            )
            return

        result = results[0]
        sim_file = Path(result.sim_path)
        if not sim_file.exists():
            QMessageBox.warning(
                self, "Scenes",
                f"The .sim file for “{result.sim_name}” could not be found:\n"
                f"{result.sim_path}",
            )
            return
        available = result.scene_names()
        wanted = sorted(s for s in scenes if s in available)
        if not wanted:
            QMessageBox.information(
                self, "Scenes",
                "None of the selected scenes are available in the ticked data set.",
            )
            return
        # Each scene maps to the displayers to keep visible (its checked ones).
        show_sel = self.selection.selected_displayers()
        scene_show = {s: list(show_sel.get(s, [])) for s in wanted}
        # Group the scenes into checkouts of the configured size: each chunk is
        # one starccm+ session (one license, sim loaded once).
        per = max(1, self.settings.media.scenes_per_checkout)
        items = list(scene_show.items())
        jobs: list[tuple[Path, dict[str, list[str]]]] = [
            (sim_file, dict(items[i:i + per])) for i in range(0, len(items), per)
        ]

        # Saved views to render each scene from (empty == the current view).
        views = sorted(self.selection.selected_views())

        # No folder prompt: render into the configured output folder, or
        # alongside the .sim file when none is set.
        out_dir = (
            Path(self.settings.default_output_dir)
            if self.settings.default_output_dir
            else sim_file.parent
        )
        self._start_render(jobs, out_dir, views)

    def _start_render(
        self,
        jobs: list[tuple[Path, dict[str, list[str]]]],
        out_dir: Path,
        views: list[str],
    ) -> None:
        runner = StarRunner(self.settings)
        self._render_thread = QThread()
        self._render_worker = SceneRenderWorker(jobs, runner, out_dir, views)
        self._render_worker.moveToThread(self._render_thread)

        self._render_thread.started.connect(self._render_worker.run)
        self._render_worker.log.connect(self.log_console.append)
        self._render_worker.progress.connect(self.log_console.set_progress)
        self._render_worker.rendered.connect(self._on_scenes_rendered)
        self._render_worker.finished.connect(self._on_render_finished)
        self._render_worker.finished.connect(self._render_thread.quit)

        self.log_console.clear()
        # All of a data set's scenes render in one checkout, so progress is per
        # data set (the macro streams per-scene progress to the log).
        self.log_console.start_progress(len(jobs))
        # Switch to the Scenes tab so the gallery is in view when stills land.
        self._center_tabs.setCurrentWidget(self.scene_view)
        self._render_thread.start()

    def _on_scenes_rendered(self, sim_path, artifacts) -> None:
        """A file's stills finished: attach them to its result (replacing any
        prior stills of the same scenes) and persist."""
        target = Path(sim_path).resolve()
        res = next(
            (r for r in self.store.all() if Path(r.sim_path).resolve() == target),
            None,
        )
        if res is None:
            return
        rendered_sources = {a.source for a in artifacts}
        res.media = [
            m for m in res.media
            if not (m.kind == "still" and m.source in rendered_sources)
        ] + list(artifacts)
        self.store.put(res)
        self.store.save_cache_async()  # off the GUI thread; runs on it here

    def _on_render_finished(self) -> None:
        self.log_console.finish_progress()
        # New stills may reuse existing file names (same paths), so force the
        # gallery to rebuild — the thumbnail cache reloads any changed images.
        self._scene_gallery_paths = None
        self._refresh_from_store()

    def _record_screenplays(self) -> None:
        """Screenplays tab → Record: record the ticked screenplays of the
        ticked data set to movies. Independent of the numeric batch, of Run
        batch, and of scene rendering."""
        if self._busy() or self._render_busy() or self._record_busy():
            QMessageBox.information(
                self, "StarPost", "A run is already in progress."
            )
            return
        if self._missing_exe():
            return
        screenplays = self.selection.selected_screenplays()
        if not screenplays:
            QMessageBox.information(
                self, "Screenplays",
                "Select at least one screenplay to record.",
            )
            return
        # Record one data set at a time: recording is heavy and the output is
        # per-.sim (same rule as scene rendering).
        results = self._active_results()
        if not results:
            QMessageBox.information(
                self, "Screenplays", "Tick a data set in the Data tab first."
            )
            return
        if len(results) > 1:
            QMessageBox.warning(
                self, "Screenplays",
                "Select only one data set to record. Untick the others in "
                "the Data tab, then press Record.",
            )
            return

        result = results[0]
        sim_file = Path(result.sim_path)
        if not sim_file.exists():
            QMessageBox.warning(
                self, "Screenplays",
                f"The .sim file for “{result.sim_name}” could not be found:\n"
                f"{result.sim_path}",
            )
            return
        available = result.screenplay_names()
        wanted = sorted(s for s in screenplays if s in available)
        if not wanted:
            QMessageBox.information(
                self, "Screenplays",
                "None of the selected screenplays are available in the "
                "ticked data set.",
            )
            return
        # Each screenplay maps to the displayers to keep visible.
        show_sel = self.selection.selected_screenplay_displayers()
        screenplay_show = {s: list(show_sel.get(s, [])) for s in wanted}
        # Chunk into checkouts of the configured size: each chunk is one
        # starccm+ session (one license, sim loaded once).
        per = max(1, self.settings.media.screenplays_per_checkout)
        items = list(screenplay_show.items())
        jobs: list[tuple[Path, dict[str, list[str]]]] = [
            (sim_file, dict(items[i:i + per]))
            for i in range(0, len(items), per)
        ]
        # Saved views: one movie per screenplay × view (empty == its camera).
        views = sorted(self.selection.selected_views())
        out_dir = (
            Path(self.settings.default_output_dir)
            if self.settings.default_output_dir
            else sim_file.parent
        )
        self._start_record(jobs, out_dir, views)

    def _start_record(
        self,
        jobs: list[tuple[Path, dict[str, list[str]]]],
        out_dir: Path,
        views: list[str],
    ) -> None:
        runner = StarRunner(self.settings)
        self._record_thread = QThread()
        self._record_worker = ScreenplayRecordWorker(
            jobs, runner, out_dir, views
        )
        self._record_worker.moveToThread(self._record_thread)

        self._record_thread.started.connect(self._record_worker.run)
        self._record_worker.log.connect(self.log_console.append)
        self._record_worker.progress.connect(self._on_record_job_progress)
        self._record_worker.frame_progress.connect(self._on_record_frame_progress)
        self._record_worker.recording.connect(self._on_record_started)
        self._record_worker.recorded.connect(self._on_screenplays_recorded)
        self._record_worker.finished.connect(self._on_record_finished)
        self._record_worker.finished.connect(self._record_thread.quit)

        self.log_console.clear()
        # All of a chunk's screenplays record in one checkout, so progress is
        # per chunk (the macro streams per-screenplay progress to the log).
        self.log_console.start_progress(len(jobs))
        self._record_jobs_done = 0
        self._record_jobs_total = len(jobs)
        # Switch to the Screenplays tab so the gallery is in view when the
        # movies land.
        self._center_tabs.setCurrentWidget(self.screenplay_view)
        self._record_thread.start()

    def _on_screenplays_recorded(self, sim_path, artifacts) -> None:
        """A file's movies finished: attach them to its result (replacing any
        prior movies of the same screenplays; stills untouched) and persist."""
        target = Path(sim_path).resolve()
        res = next(
            (
                r for r in self.store.all()
                if Path(r.sim_path).resolve() == target
            ),
            None,
        )
        if res is None:
            return
        recorded_sources = {a.source for a in artifacts}
        res.media = [
            m for m in res.media
            if not (m.kind == "movie" and m.source in recorded_sources)
        ] + list(artifacts)
        self.store.put(res)
        self.store.save_cache_async()  # off the GUI thread; runs on it here

    def _on_record_finished(self) -> None:
        self.log_console.finish_progress()
        # New movies may reuse existing file names (same paths), so force the
        # gallery to rebuild — the poster cache reloads any changed images.
        self._screenplay_gallery_paths = None
        self._refresh_from_store()

    def _on_record_job_progress(self, done: int, total: int) -> None:
        """A recording job (one license checkout) finished: tick the coarse
        bar and remember the counts for the per-frame interpolation."""
        self._record_jobs_done = done
        self._record_jobs_total = total
        self.log_console.set_progress(done, total)

    def _on_record_started(self, label: str) -> None:
        """A screenplay's record just began. Show a busy indicator: STAR's fast
        native record() renders silently in -batch, so no per-frame markers may
        follow. If the frame-loop path runs instead, its frame_progress restores
        the determinate bar automatically."""
        self.log_console.busy(f"Recording {label}…")

    def _on_record_frame_progress(self, frame: int, frames: int) -> None:
        """A frame rendered inside the current job: advance the bar
        fractionally between job ticks (jobs_done + frame/frames, in
        per-mille units so set_progress's integer API keeps the detail)."""
        total = max(self._record_jobs_total, 1)
        done_units = self._record_jobs_done * 1000 + round(
            1000 * frame / max(frames, 1)
        )
        self.log_console.set_progress(done_units, total * 1000)

    def _clear_screenplays(self) -> None:
        """Screenplays tab → "Clear screenplays": drop every recorded movie
        from the workspace after confirming. The movie/poster files on disk
        are left in place (matching "Clear scenes")."""
        if self._record_busy():
            QMessageBox.information(
                self, "Clear screenplays",
                "Screenplays are still recording. Wait for the run to finish "
                "first.",
            )
            return
        if not any(
            m.kind == "movie" for r in self.store.all() for m in r.media
        ):
            QMessageBox.information(
                self, "Clear screenplays",
                "There are no recorded screenplays to clear.",
            )
            return
        if QMessageBox.question(
            self, "Clear screenplays",
            "Clear all recorded screenplays? This removes every recorded "
            "movie from the workspace (the files already saved on disk are "
            "kept).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        for r in self.store.all():
            if any(m.kind == "movie" for m in r.media):
                r.media = [m for m in r.media if m.kind != "movie"]
                self.store.put(r)
        # Persist so the cleared state survives restart (async: no GUI freeze).
        self.store.save_cache_async()
        self._refresh_from_store()

    def _clear_scenes(self) -> None:
        """Scenes tab → "Clear scenes": drop every rendered still from the
        workspace after confirming. The image files on disk are left in place
        (matching how "Clear data" keeps the .sim files)."""
        if self._render_busy():
            QMessageBox.information(
                self, "Clear scenes",
                "Scenes are still rendering. Wait for the run to finish first.",
            )
            return
        if not any(m.kind == "still" for r in self.store.all() for m in r.media):
            QMessageBox.information(
                self, "Clear scenes", "There are no rendered scenes to clear."
            )
            return
        if QMessageBox.question(
            self, "Clear scenes",
            "Clear all rendered scenes? This removes every rendered still from "
            "the workspace (the image files already saved on disk are kept).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        for r in self.store.all():
            if any(m.kind == "still" for m in r.media):
                r.media = [m for m in r.media if m.kind != "still"]
                self.store.put(r)
        # Persist so the cleared state survives restart (async: no GUI freeze).
        self.store.save_cache_async()
        self._refresh_from_store()

    def _delete_data_names(self, names: list) -> None:
        """Delete the named data sets from the store, after confirmation — the
        Data tab's selection-based remove (context menu / Delete key)."""
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(
                self, "Delete data",
                "A batch is still running. Stop it before deleting data.",
            )
            return
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
        # Persist so the deletion survives restart (async: no GUI freeze).
        self.store.save_cache_async()
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
        # Persist the empty state so it survives restart (async: no GUI freeze).
        self.store.save_cache_async()
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

    def _monitor_groups_union(self, results) -> dict[str, list[str]]:
        """Build ``{plot group: [monitor series, ...]}`` as the union across
        ``results``, dropping empty monitors when "Hide empty monitors" is on
        (mirroring the plot view). Drives the selection panel's plot tree and the
        export menu's Monitors column."""
        hide = self.settings.hide_empty_monitors
        threshold = self.settings.monitor_zero_threshold
        groups: dict[str, list[str]] = {}
        for r in results:
            for p in r.plots:
                names = groups.setdefault(p.name, [])
                for s in p.series:
                    if hide and s.is_empty(threshold):
                        continue
                    if s.name not in names:
                        names.append(s.name)
        return groups

    def _residual_group_names(self, results) -> set[str]:
        """Plot groups classified as residuals (any result marks them
        ``PlotKind.RESIDUAL``). These plot all their monitors at once when ticked."""
        return {
            p.name for r in results for p in r.plots if p.kind == PlotKind.RESIDUAL
        }

    def _refresh_report_choices(self) -> None:
        """Update the report checkbox list for the current mode/file, keeping
        the user's selection."""
        results = [r for r in self.store.all() if r.error is None]
        self.selection.set_available_reports(self._available_report_names(results))

    def _refresh_from_store(self) -> None:
        # This full rebuild covers everything a queued coalesced refresh would
        # do (and more), so drop any pending one rather than refreshing twice.
        self._refresh_timer.stop()
        self._rescope_pending = False
        results = [r for r in self.store.all() if r.error is None]

        # The Data tab mirrors the loaded results, named after their .sim files.
        self.data_list.set_entries([r.sim_name for r in results])

        report_union = self._available_report_names(results)
        plot_groups = self._monitor_groups_union(results)
        self.selection.populate(report_union, plot_groups)
        # Residual groups plot all their monitors at once when ticked.
        self.selection.set_residual_groups(self._residual_group_names(results))
        self._refresh_scene_choices()

        self._refresh_views()

    def _refresh_scene_choices(self) -> None:
        """Populate the Scenes tree and Saved views list from the checked data
        sets, so both reflect the selected sim(s). Scoped to the active selection
        (not the whole batch) because a render targets the chosen sim."""
        results = self._active_results()
        scene_groups: dict[str, list[str]] = {}
        for r in results:
            for sc in r.scenes:
                names = scene_groups.setdefault(sc.name, [])
                for d in sc.displayers:
                    if d.name not in names:
                        names.append(d.name)
        screenplay_groups: dict[str, list[str]] = {}
        for r in results:
            for sp in r.screenplays:
                names = screenplay_groups.setdefault(sp.name, [])
                for d in sp.displayers:
                    if d.name not in names:
                        names.append(d.name)
        self.selection.set_available_scenes(scene_groups)
        self.selection.set_available_screenplays(screenplay_groups)
        self.selection.set_available_views(
            sorted({v for r in results for v in r.views})
        )

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
        render and the view mode, so the report list is re-scoped (which reports
        count as empty depends on the mode) before the redraw."""
        self._schedule_refresh(rescope=True)

    def _on_selection_changed(self) -> None:
        # A report/plot checkbox toggled: redraw.
        self._schedule_refresh()

    def _schedule_refresh(self, *, rescope: bool = False) -> None:
        """Queue one view refresh for after the current burst of events.

        Checkbox changes arrive one signal per item (a Shift+click range tick
        fires dozens), and a full refresh is the most expensive thing the UI
        does — so instead of refreshing per signal, a zero-delay single-shot
        timer collapses the whole burst into a single refresh. ``rescope`` also
        re-derives the report/scene choice lists (needed when the checked data
        sets — and so the view mode — changed, not for plain redraws)."""
        self._rescope_pending = self._rescope_pending or rescope
        self._refresh_timer.start()

    def _run_scheduled_refresh(self) -> None:
        if self._rescope_pending:
            self._rescope_pending = False
            self._refresh_report_choices()
            # Scenes/views are scoped to the checked sim(s): refresh them too.
            self._refresh_scene_choices()
        self._refresh_views()

    def _selected_plot_names(self) -> list[str]:
        """The monitor plots to display: every checked one (sorted)."""
        results = self._active_results()
        plot_union = sorted({n for r in results for n in r.plot_names()})
        selected = self.selection.selected_plots()
        return [p for p in plot_union if p in selected]

    def _plot_color_getter(self, sim, name: str):
        """The colour a monitor's line is drawn in: per data set in comparison
        mode (``sim`` given), or the single series colour (``sim`` None)."""
        if sim is None:
            return self.plot_view.series_color(name)
        return self.plot_view.pair_color(sim, name)

    def _plot_color_setter(self, sim, name: str, color: str) -> None:
        """Recolour a monitor's line (redraw happens inside the plot view)."""
        if sim is None:
            self.plot_view.set_series_color(name, color)
        else:
            self.plot_view.set_pair_color(sim, name, color)

    def _refresh_views(self) -> None:
        self._render_reports()
        self._render_plot()
        self._render_scenes_view()
        self._render_screenplays_view()
        # The plot just (re)drew, so sync the panel's monitor colour swatches to
        # the colours actually used (and to the current data-set count). The
        # swatches are only visible alongside the Plots tab; when its render was
        # deferred above, the tab switch refreshes them with the redraw instead.
        if self._center_tabs.currentWidget() is self._plot_tab:
            self.selection.refresh_monitor_swatches()

    def _render_scenes_view(self) -> None:
        """Rebuild the rendered-stills gallery — but only when the Scenes tab is
        showing and the set of stills actually changed. Decoding the images is
        costly, so we skip it on unrelated refreshes (report/plot toggles, other
        tabs) and defer to when the Scenes tab is next selected."""
        if self._center_tabs.currentWidget() is not self.scene_view:
            self._scene_gallery_paths = None  # stale; a switch to Scenes rebuilds
            return
        media = []
        for r in self._active_results():
            for m in r.media:
                if m.kind != "still":
                    continue
                m.sim_path = r.sim_path  # provenance for the Properties window
                media.append(m)
        paths = [m.path for m in media]
        if paths == self._scene_gallery_paths:
            return  # unchanged — keep the gallery (and its decoded thumbnails)
        self._scene_gallery_paths = paths
        if media:
            self.scene_view.show_media(media)
        else:
            self.scene_view.clear()

    def _render_screenplays_view(self) -> None:
        """Rebuild the recorded-movies gallery — but only when the Screenplays
        tab is showing and the set of movies actually changed (same deferral
        pattern as the scene gallery)."""
        if self._center_tabs.currentWidget() is not self.screenplay_view:
            self._screenplay_gallery_paths = None  # stale; rebuilt on switch
            return
        media = []
        for r in self._active_results():
            for m in r.media:
                if m.kind != "movie":
                    continue
                m.sim_path = r.sim_path  # provenance for Properties
                media.append(m)
        paths = [m.path for m in media]
        if paths == self._screenplay_gallery_paths:
            return  # unchanged — keep the gallery (and its poster thumbnails)
        self._screenplay_gallery_paths = paths
        if media:
            self.screenplay_view.show_media(media)
        else:
            self.screenplay_view.clear()

    def _render_reports(self) -> None:
        results = self._active_results()
        if not results:
            self.report_table.clear()
            return
        selected = self.selection.selected_reports()
        hide_zero = self.settings.hide_empty_reports
        if self._is_comparison():
            # Imported here, not at the top of the function: the aggregator
            # pulls in pandas (~400 ms), which must not load during startup's
            # empty-store call — only when a comparison is actually drawn.
            from starpost.batch.aggregator import reports_wide_frame

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
        # Redrawing the plot is the most expensive refresh, so skip it while the
        # Plots tab is hidden (report/data toggles on the other tabs would pay
        # for an invisible redraw) and defer to when the tab is next selected —
        # the same pattern the scene gallery uses (_render_scenes_view).
        if self._center_tabs.currentWidget() is not self._plot_tab:
            self._plot_stale = True
            return
        self._plot_stale = False
        results = self._active_results()
        plot_names = self._selected_plot_names()
        if not results or not plot_names:
            # No monitor plot selected (e.g. the last one was just unchecked):
            # blank the view rather than leaving the previous plot on screen.
            self.plot_view.clear()
            return
        # Store the panel's monitor selection first (without rendering), so the
        # show_* below draws it directly — one render, not a draw-then-redraw.
        self.plot_view.set_monitor_selection(
            self.selection.selected_monitors(), render=False
        )
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

    def _show_data_folder_properties(self, name, data_names) -> None:
        """Data tab → folder right-click → Properties: the data sets it holds and
        their combined size as portable CSVs."""
        from starpost.data.portable import sim_csv_size
        from starpost.gui.views.properties_dialog import DataFolderPropertiesDialog

        wanted = set(data_names)
        results = [
            r for r in self.store.all() if r.error is None and r.sim_name in wanted
        ]
        total = sum(sim_csv_size(r) for r in results)
        DataFolderPropertiesDialog(name, total, len(data_names), self).exec()

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
            # Persist so the import survives restart (async: no GUI freeze).
            self.store.save_cache_async()
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

        # Monitor groups are plots; their monitors are the plot's series. The
        # union of series per plot mirrors the plot view (empties dropped when
        # "Hide empty monitors" is on); the ticked monitors come from the panel.
        monitor_groups = self._monitor_groups_union(results)
        checked_groups = sorted(self.selection.selected_plots())
        checked_monitors = self.selection.selected_monitors()
        # Mirror the colours and legend position chosen in the main UI's plot onto
        # the export preview.
        series_colors, pair_colors = self.plot_view.color_overrides()

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
            series_colors=series_colors,
            pair_colors=pair_colors,
            legend_offset=self.plot_view.legend_offset(),
            residual_groups=sorted(self._residual_group_names(results)),
            parent=self,
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
        from starpost.utils.paths import settings_path

        # The dialog is built once and reused: its ~12 pages are expensive to
        # construct, so reopening re-syncs the existing instance (see reload)
        # instead of rebuilding it, keeping every open after the first instant.
        dlg = self._settings_dialog
        if dlg is None:
            from starpost.gui.views.settings_dialog import SettingsDialog

            dlg = SettingsDialog(self.settings, self)
            # Live-preview the light/dark switch on the plot (Cancel reverts it).
            dlg.preview_changed.connect(self.plot_view.apply_theme)
            # Live-preview the folder colour on the Files/Data tabs (Cancel reverts).
            dlg.folder_color_changed.connect(self.file_list.set_folder_color)
            dlg.folder_color_changed.connect(self.data_list.set_folder_color)
            # Live-preview the leaf node-dot colour on the Files tab (Cancel reverts).
            dlg.node_color_changed.connect(self.file_list.set_node_color)
            # Resetting settings is applied + saved immediately (independent of
            # Save/Cancel): push it to the views and reload the Default profile.
            dlg.defaults_reset.connect(self._on_settings_reset)
            self._settings_dialog = dlg
        else:
            dlg.reload()
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
        self._refresh_menu_icons()  # theme mode/accent may have changed
        self.file_list.set_show_full_names(self.settings.show_full_file_names)
        folder_color = self.settings.appearance.resolved_folder_color()
        self.file_list.set_folder_color(folder_color)
        self.data_list.set_folder_color(folder_color)
        self.file_list.set_node_color(self.settings.appearance.resolved_node())
        self.file_list.set_accent(self.settings.appearance.accent)
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
        self.plot_view.set_smooth_width(self.settings.moving_average_width)
        self.plot_view.set_text_scale(self.settings.appearance.text_scale)
        self.plot_view.apply_theme(self.settings.appearance.mode)
        # The hide-empty/threshold settings change which reports and monitors
        # qualify as empty: refresh both lists (preserving the current selection).
        results = [r for r in self.store.all() if r.error is None]
        self.selection.set_available_reports(self._available_report_names(results))
        self.selection.set_available_plots(self._monitor_groups_union(results))
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
        # Save the crash-recovery cache off the GUI thread so a large workspace
        # doesn't freeze the window on close. The snapshot is taken synchronously
        # (so it reflects the final state) and the write runs on a non-daemon
        # thread that the interpreter joins before the process exits.
        self.store.save_cache_async()
        # Persist the Scenes/Screenplays divider positions across restarts.
        self.settings.saved_view_splits = self.selection.saved_view_splits()
        self.settings.save()
        super().closeEvent(event)
