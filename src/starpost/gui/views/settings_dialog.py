"""Settings dialog: edit every application setting from the YAML file.

Layout: a left-hand nav lists the setting *groups*; the right-hand stack shows
that group's individual settings. On Save, the values are written back into the
Settings object and persisted via Settings.save().

Covers everything in settings.yaml:
  - STAR-CCM+:  starccm_path, default_output_dir, extra_args
  - License:    mode, podkey, licpath, license_file
  - Reports:    report_decimals, hide_empty_reports, zero_threshold
  - Plots:      hide_empty_monitors, monitor_zero_threshold, moving_average_width,
                hover_show_monitor_name, hover_x_decimals, hover_y_decimals,
                classification keywords

Plus a Profiles page that lists saved selection profiles and lets the user
delete them (these live as separate YAML files, not in settings.yaml).
"""
from __future__ import annotations

import shlex

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDoubleValidator
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from starpost import __version__
from starpost.core.settings import (
    DEFAULT_PROFILE_NAME,
    MAX_TEXT_SCALE,
    MIN_TEXT_SCALE,
    LicenseConfig,
    Profile,
    Settings,
    delete_profile,
    list_profiles,
)
from starpost.core.starccm_runner import exe_dialog_filter, exe_placeholder
from starpost.gui.icons import logo_pixmap
from starpost.gui.widgets import SecretLineEdit
from starpost.gui.theme import (
    ACCENT_PRESETS,
    apply_theme,
    contrast_color,
    normalize_accent,
)
from starpost.gui.views.plot_view import REGION_STAT_LABELS


def _csv(text: str) -> list[str]:
    """Parse a comma-separated field into a list of trimmed, non-empty tokens."""
    return [t.strip() for t in text.split(",") if t.strip()]


def _path_row(
    line: QLineEdit, on_browse, tooltip: str = "Browse for a file or folder"
) -> QHBoxLayout:
    """A line edit followed by a Browse… button (with a descriptive tooltip)."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(line)
    btn = QPushButton("Browse…")
    btn.setToolTip(tooltip)
    btn.clicked.connect(on_browse)
    row.addWidget(btn)
    return row


class ProfileDetailsDialog(QDialog):
    """Read-only view of one profile's selected reports and plots/monitors."""

    def __init__(self, profile: Profile, parent=None, *, all_reports: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Profile: {profile.name}")
        self.resize(720, 420)

        reports = QListWidget()
        if all_reports:
            # Built-in Default: reports are resolved from the loaded data, so
            # there are no concrete names to list here.
            reports.addItem("(all reports)")
        else:
            for name in sorted(profile.reports):
                reports.addItem(name)
            if reports.count() == 0:
                reports.addItem("(none selected)")

        # Each selected plot (monitor group), with its shown monitors listed
        # beneath it. A group with no recorded monitors shows all of them.
        plots = QListWidget()
        for plot in sorted(profile.plots):
            plots.addItem(plot)
            monitors = profile.monitors.get(plot)
            if monitors:
                for m in sorted(monitors):
                    plots.addItem(f"    • {m}")
            else:
                plots.addItem("    • (all monitors)")
        if plots.count() == 0:
            plots.addItem("(none selected)")

        # Statistical measures saved with the profile. None means the profile
        # predates this feature, so it falls back to the current settings.
        stats = QListWidget()
        if profile.region_stats is None:
            stats.addItem("(default statistics)")
        else:
            for name in profile.region_stats:
                stats.addItem(name)
            if stats.count() == 0:
                stats.addItem("(none selected)")

        cols = QHBoxLayout()
        cols.addLayout(self._column("Reports", reports), 1)
        cols.addLayout(self._column("Plots", plots), 1)
        cols.addLayout(self._column("Statistics", stats), 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "Close this window"
        )
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addLayout(cols, 1)
        layout.addWidget(buttons)

    @staticmethod
    def _column(title: str, lst: QListWidget) -> QVBoxLayout:
        col = QVBoxLayout()
        label = QLabel(title)
        label.setStyleSheet("font-weight: bold;")
        col.addWidget(label)
        col.addWidget(lst, 1)
        return col


class SettingsDialog(QDialog):
    # Emitted while previewing with the current "dark"/"light" mode whenever it
    # changes, so non-QSS widgets (e.g. the plot) can follow the live preview.
    preview_changed = Signal(str)
    # Emitted while previewing the Files-tab folder colour ("" == default icon),
    # so the file list can follow the live preview.
    folder_color_changed = Signal(str)
    # Emitted when the user resets settings to defaults, so the main view can
    # reload the Default profile.
    defaults_reset = Signal()

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(660, 460)
        self._settings = settings
        # While populating the controls from the current settings, suppress the
        # live theme preview: it would re-apply the already-active stylesheet to
        # the whole app several times (slow, and a visual no-op). Real user edits
        # after construction still preview live.
        self._loading = True

        # Remember the live appearance so Cancel can revert the preview.
        self._orig_mode = settings.appearance.mode
        self._orig_accent = settings.appearance.accent
        self._accent = normalize_accent(settings.appearance.accent)
        self._last_preview_mode = self._orig_mode
        # Checkmark colour (live + revert state).
        self._checkmark_color = normalize_accent(settings.appearance.checkmark_color)
        self._checkmark_match = settings.appearance.checkmark_match_theme
        self._orig_checkmark = settings.appearance.resolved_checkmark()
        # Folder colour (live + revert state).
        self._folder_color = normalize_accent(settings.appearance.folder_color)
        self._folder_default = settings.appearance.folder_use_default
        self._orig_folder_color = settings.appearance.resolved_folder_color()
        # Text-size multiplier (live + revert state).
        self._text_scale = settings.appearance.text_scale
        self._orig_text_scale = settings.appearance.text_scale

        # Left nav (groups) drives the right stack (individual settings).
        self._nav = QListWidget()
        self._nav.setObjectName("settingsNav")
        self._nav.setMaximumWidth(180)
        self._stack = QStackedWidget()

        self._add_page("STAR-CCM+", self._build_starccm_page())
        self._add_page("License", self._build_license_page())
        self._add_page("Appearance", self._build_appearance_page())
        self._add_page("Files", self._build_files_page())
        self._add_page("Reports", self._build_reports_page())
        self._add_page("Plots", self._build_plots_page())
        self._add_page("Export", self._build_export_page())
        self._add_page("Profiles", self._build_profiles_page())
        self._add_page("Misc", self._build_misc_page())
        self._add_page("About", self._build_about_page())

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        body = QHBoxLayout()
        body.addWidget(self._nav)
        body.addWidget(self._stack, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setToolTip(
            "Save the settings and close"
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
            "Discard changes and close"
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)

        self._load_from_settings()
        self._sync_license_mode()
        self._loading = False

    # --- page construction ----------------------------------------------
    def _add_page(self, name: str, widget: QWidget) -> None:
        # Wrap every page in a scroll area so tall pages (e.g. Plots) stay fully
        # reachable instead of being clipped by the dialog height.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(widget)
        self._nav.addItem(name)
        self._stack.addWidget(scroll)

    @staticmethod
    def _wrap(form: QFormLayout) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.addLayout(form)
        outer.addStretch(1)
        return w

    def _build_starccm_page(self) -> QWidget:
        self._exe = QLineEdit()
        self._exe.setPlaceholderText(exe_placeholder())
        self._out = QLineEdit()
        self._out.setPlaceholderText("Empty = your home folder")
        self._extra = QLineEdit()
        self._extra.setPlaceholderText("e.g.  -np 4 -mpi openmpi")

        form = QFormLayout()
        form.addRow(
            "Executable path",
            _path_row(
                self._exe, self._browse_exe,
                "Browse for the STAR-CCM+ executable",
            ),
        )
        form.addRow(
            "Default output folder",
            _path_row(
                self._out, self._browse_out,
                "Browse for the default output folder",
            ),
        )
        form.addRow("Extra arguments", self._extra)
        hint = QLabel("Appended verbatim to every starccm+ call (space-separated).")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return self._wrap(form)

    def _build_license_page(self) -> QWidget:
        self._mode = QComboBox()
        self._mode.addItem("POD key + license server", "podkey_server")
        self._mode.addItem("License file", "license_file")
        self._mode.currentIndexChanged.connect(self._sync_license_mode)

        # Masked by default (••••) with a Show/Hide toggle, so the key isn't
        # shown on screen until the user asks.
        self._podkey = SecretLineEdit()
        self._podkey.setPlaceholderText("Power-on-Demand key")
        self._licpath = QLineEdit()
        self._licpath.setPlaceholderText("<port>@<server>   e.g. 1999@licsrv")
        self._licfile = QLineEdit()
        self._licfile.setPlaceholderText("/path/to/license.dat")

        form = QFormLayout()
        form.addRow("Mode", self._mode)
        self._podkey_label = QLabel("POD key")
        form.addRow(self._podkey_label, self._podkey)
        self._licpath_label = QLabel("License server")
        form.addRow(self._licpath_label, self._licpath)
        self._licfile_label = QLabel("License file")
        form.addRow(
            self._licfile_label,
            _path_row(
                self._licfile, self._browse_licfile,
                "Browse for the license file",
            ),
        )
        return self._wrap(form)

    def _build_files_page(self) -> QWidget:
        self._show_full_paths = QCheckBox("Show file path")

        form = QFormLayout()
        form.addRow("", self._show_full_paths)
        hint = QLabel(
            "When selected, the Files window lists the full file path for each "
            ".sim file instead of just the file name."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return self._wrap(form)

    def _build_reports_page(self) -> QWidget:
        self._decimals = QSpinBox()
        self._decimals.setRange(0, 15)
        self._decimals.setValue(4)

        self._hide_empty = QCheckBox("Hide empty reports")

        self._zero_threshold = QLineEdit()
        self._zero_threshold.setFixedWidth(110)
        validator = QDoubleValidator(0.0, 1e12, 15)
        validator.setNotation(QDoubleValidator.ScientificNotation)
        self._zero_threshold.setValidator(validator)
        self._zero_threshold.setPlaceholderText("1e-05")

        form = QFormLayout()
        form.addRow("Decimal places", self._decimals)
        dec_hint = QLabel("Number of decimals shown for report values in the table.")
        dec_hint.setObjectName("hint")
        dec_hint.setWordWrap(True)
        form.addRow("", dec_hint)
        form.addRow("", self._hide_empty)
        hide_hint = QLabel("Hide reports whose value is ~0 (see Zero threshold).")
        hide_hint.setObjectName("hint")
        hide_hint.setWordWrap(True)
        form.addRow("", hide_hint)
        form.addRow("Zero threshold", self._zero_threshold)
        zt_hint = QLabel(
            "Values with magnitude below this are shown as 0 (and hidden when "
            "Hide empty reports is on)."
        )
        zt_hint.setObjectName("hint")
        zt_hint.setWordWrap(True)
        form.addRow("", zt_hint)
        return self._wrap(form)

    def _build_plots_page(self) -> QWidget:
        self._hide_empty_monitors = QCheckBox("Hide empty monitors")

        self._monitor_zero_threshold = QLineEdit()
        self._monitor_zero_threshold.setFixedWidth(110)
        validator = QDoubleValidator(0.0, 1e12, 15)
        validator.setNotation(QDoubleValidator.ScientificNotation)
        self._monitor_zero_threshold.setValidator(validator)
        self._monitor_zero_threshold.setPlaceholderText("1e-05")

        self._moving_average_width = QSpinBox()
        self._moving_average_width.setRange(1, 999)
        self._moving_average_width.setValue(10)

        self._hover_show_name = QCheckBox("Show name when hovering")

        self._hover_x_decimals = QSpinBox()
        self._hover_x_decimals.setRange(0, 15)
        self._hover_x_decimals.setValue(0)
        self._hover_y_decimals = QSpinBox()
        self._hover_y_decimals.setRange(0, 15)
        self._hover_y_decimals.setValue(4)

        # Statistics shown in the Shift+drag region table — a checkable list of
        # the available statistics.
        self._region_stats = QListWidget()
        self._region_stats.setMaximumHeight(160)
        for label in REGION_STAT_LABELS:
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self._region_stats.addItem(item)

        self._residual = QLineEdit()
        self._residual.setPlaceholderText("residual, residuals")
        self._force = QLineEdit()
        self._force.setPlaceholderText("force, drag, lift, moment, cd, cl")

        form = QFormLayout()
        form.addRow("", self._hide_empty_monitors)
        hide_hint = QLabel("Hide monitors whose values are all ~0 (see Zero threshold).")
        hide_hint.setObjectName("hint")
        hide_hint.setWordWrap(True)
        form.addRow("", hide_hint)
        form.addRow("Zero threshold", self._monitor_zero_threshold)
        zt_hint = QLabel(
            "Monitors whose values are all below this magnitude are treated as 0 "
            "(and hidden when Hide empty monitors is on)."
        )
        zt_hint.setObjectName("hint")
        zt_hint.setWordWrap(True)
        form.addRow("", zt_hint)
        form.addRow("Moving average width", self._moving_average_width)
        ma_hint = QLabel(
            "Window size (in points) of the moving average applied when "
            "“Smooth data” is enabled under the plot. 1 leaves the data unchanged."
        )
        ma_hint.setObjectName("hint")
        ma_hint.setWordWrap(True)
        form.addRow("", ma_hint)
        form.addRow("", self._hover_show_name)
        hover_hint = QLabel(
            "When selected, monitor names are shown when hovering over a monitor."
        )
        hover_hint.setObjectName("hint")
        hover_hint.setWordWrap(True)
        form.addRow("", hover_hint)
        form.addRow("Hover X decimals", self._hover_x_decimals)
        form.addRow("Hover Y decimals", self._hover_y_decimals)
        dec_hint = QLabel(
            "Decimal places shown for X and Y coordinates when hovering over a monitor."
        )
        dec_hint.setObjectName("hint")
        dec_hint.setWordWrap(True)
        form.addRow("", dec_hint)
        form.addRow("Statistics", self._region_stats)
        stats_hint = QLabel(
            "Statistics listed in the table shown when you Shift+drag a region "
            "over the plot. Checked ones are displayed."
        )
        stats_hint.setObjectName("hint")
        stats_hint.setWordWrap(True)
        form.addRow("", stats_hint)
        form.addRow("Residual keywords", self._residual)
        form.addRow("Force keywords", self._force)
        hint = QLabel(
            "Comma-separated. A monitor plot whose name matches a residual keyword "
            "gets a log Y axis; force keywords get a linear axis."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return self._wrap(form)

    def _build_export_page(self) -> QWidget:
        # Defaults that pre-fill the Export dialog's controls. Choices mirror the
        # dialog's own combos (see ExportDialog._build_options / _build_plot_options).
        self._export_report_format = QComboBox()
        self._export_report_format.addItems(["CSV", "TSV", "XLSX", "ODS"])

        self._export_plot_format = QComboBox()
        self._export_plot_format.addItems(["PNG", "JPG", "TIFF", "PDF"])

        self._export_plot_theme = QComboBox()
        self._export_plot_theme.addItem("Light", "light")
        self._export_plot_theme.addItem("Dark", "dark")

        form = QFormLayout()
        form.addRow("Default report format", self._export_report_format)
        rep_hint = QLabel("Default file format for exported report tables.")
        rep_hint.setObjectName("hint")
        rep_hint.setWordWrap(True)
        form.addRow("", rep_hint)
        form.addRow("Default plot format", self._export_plot_format)
        plot_hint = QLabel("Default image format for exported plots.")
        plot_hint.setObjectName("hint")
        plot_hint.setWordWrap(True)
        form.addRow("", plot_hint)
        form.addRow("Default plot theme", self._export_plot_theme)
        theme_hint = QLabel(
            "Default light/dark theme the plot is rendered with when exported."
        )
        theme_hint.setObjectName("hint")
        theme_hint.setWordWrap(True)
        form.addRow("", theme_hint)
        return self._wrap(form)

    def _build_profiles_page(self) -> QWidget:
        # A header row plus one row per saved profile, rebuilt on delete.
        page = QWidget()
        outer = QVBoxLayout(page)
        intro = QLabel("Deleting a profile removes it permanently")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        # A grid so the per-profile buttons line up in columns regardless of
        # which rows have a Delete button (the built-in Default doesn't).
        self._profiles_list = QGridLayout()
        self._profiles_list.setContentsMargins(0, 4, 0, 0)
        self._profiles_list.setHorizontalSpacing(8)
        self._profiles_list.setVerticalSpacing(4)
        self._profiles_list.setColumnStretch(0, 1)  # name column absorbs slack
        outer.addLayout(self._profiles_list)
        outer.addStretch(1)

        self._rebuild_profiles_list()
        return page

    def _rebuild_profiles_list(self) -> None:
        # Clear existing rows.
        while self._profiles_list.count():
            item = self._profiles_list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        # The built-in Default profile always leads the list and can't be deleted.
        names = [DEFAULT_PROFILE_NAME] + [
            n for n in list_profiles() if n != DEFAULT_PROFILE_NAME
        ]
        for r, name in enumerate(names):
            self._profiles_list.addWidget(QLabel(name), r, 0)
            details = QPushButton("Show Details")
            details.setToolTip("View this profile's selected reports and plots")
            details.clicked.connect(lambda _=False, n=name: self._show_profile_details(n))
            self._profiles_list.addWidget(details, r, 1)
            if name != DEFAULT_PROFILE_NAME:
                btn = QPushButton("Delete")
                btn.setObjectName("dangerButton")
                btn.setToolTip("Delete this profile permanently")
                btn.clicked.connect(lambda _=False, n=name: self._delete_profile(n))
                self._profiles_list.addWidget(btn, r, 2)

    def _show_profile_details(self, name: str) -> None:
        if name == DEFAULT_PROFILE_NAME:
            ProfileDetailsDialog(Profile(name=name), self, all_reports=True).exec()
        else:
            ProfileDetailsDialog(Profile.load(name), self).exec()

    def _delete_profile(self, name: str) -> None:
        confirm = QMessageBox.question(
            self,
            "Delete profile",
            f"Delete the profile “{name}”? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            delete_profile(name)
            self._rebuild_profiles_list()

    def _build_appearance_page(self) -> QWidget:
        # Theme mode
        self._theme = QComboBox()
        self._theme.addItem("Dark", "dark")
        self._theme.addItem("Light", "light")
        self._theme.currentIndexChanged.connect(self._apply_preview)

        # Accent preset swatches
        swatch_box, self._swatches = self._build_swatches(self._set_accent)

        # Custom hex + colour picker + live preview chip
        self._hex = QLineEdit()
        self._hex.setMaxLength(7)
        self._hex.setPlaceholderText("#rrggbb")
        self._hex.setFixedWidth(110)
        self._hex.textEdited.connect(self._on_hex_edited)
        pick = QPushButton("Pick…")
        pick.setToolTip("Choose a custom accent colour")
        pick.clicked.connect(self._on_pick_color)
        self._preview = QLabel()
        self._preview.setFixedSize(30, 30)
        custom_row = QHBoxLayout()
        custom_row.setContentsMargins(0, 0, 0, 0)
        custom_row.addWidget(self._hex)
        custom_row.addWidget(pick)
        custom_row.addWidget(self._preview)
        custom_row.addStretch(1)
        custom_box = QWidget()
        custom_box.setLayout(custom_row)

        # Checkmark colour: a "match theme" toggle plus a hex + picker + chip,
        # mirroring the accent controls.
        self._cm_match = QCheckBox("Match with theme")
        self._cm_match.toggled.connect(self._on_cm_match_toggled)
        self._cm_hex = QLineEdit()
        self._cm_hex.setMaxLength(7)
        self._cm_hex.setPlaceholderText("#rrggbb")
        self._cm_hex.setFixedWidth(110)
        self._cm_hex.textEdited.connect(self._on_cm_hex_edited)
        self._cm_pick = QPushButton("Pick…")
        self._cm_pick.setToolTip("Choose a custom checkmark colour")
        self._cm_pick.clicked.connect(self._on_cm_pick_color)
        self._cm_preview = QLabel()
        self._cm_preview.setFixedSize(30, 30)
        cm_row = QHBoxLayout()
        cm_row.setContentsMargins(0, 0, 0, 0)
        cm_row.addWidget(self._cm_hex)
        cm_row.addWidget(self._cm_pick)
        cm_row.addWidget(self._cm_preview)
        cm_row.addStretch(1)
        cm_box = QWidget()
        cm_box.setLayout(cm_row)

        # Folder colour: a "use default" toggle plus preset swatches and a custom
        # hex + picker + preview, mirroring the accent controls.
        self._folder_default_cb = QCheckBox("Use default colour")
        self._folder_default_cb.toggled.connect(self._on_folder_default_toggled)
        self._folder_hex = QLineEdit()
        self._folder_hex.setMaxLength(7)
        self._folder_hex.setPlaceholderText("#rrggbb")
        self._folder_hex.setFixedWidth(110)
        self._folder_hex.textEdited.connect(self._on_folder_hex_edited)
        self._folder_pick = QPushButton("Pick…")
        self._folder_pick.setToolTip("Choose a custom folder colour")
        self._folder_pick.clicked.connect(self._on_folder_pick_color)
        self._folder_preview = QLabel()
        self._folder_preview.setFixedSize(30, 30)
        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.addWidget(self._folder_hex)
        folder_row.addWidget(self._folder_pick)
        folder_row.addWidget(self._folder_preview)
        folder_row.addStretch(1)
        folder_box = QWidget()
        folder_box.setLayout(folder_row)

        # Text size: a multiplier applied to every button/label program-wide.
        # 1.0 is the original size (the default); larger values enlarge the text.
        self._text_scale_spin = QDoubleSpinBox()
        self._text_scale_spin.setDecimals(2)
        self._text_scale_spin.setSingleStep(0.1)
        self._text_scale_spin.setRange(MIN_TEXT_SCALE, MAX_TEXT_SCALE)
        self._text_scale_spin.setValue(1.0)
        self._text_scale_spin.setSuffix("×")
        self._text_scale_spin.setFixedWidth(80)
        self._text_scale_spin.valueChanged.connect(self._on_text_scale_changed)

        form = QFormLayout()
        form.addRow("Theme", self._theme)
        form.addRow("Accent presets", swatch_box)
        form.addRow("Custom accent", custom_box)
        form.addRow("Checkmarks", self._cm_match)
        form.addRow("Checkmark colour", cm_box)
        form.addRow("Folders", self._folder_default_cb)
        form.addRow("Folder colour", folder_box)
        form.addRow("Text size", self._text_scale_spin)
        ts_hint = QLabel(
            "Scales the size of all buttons and labels in the app. 1.0× is the "
            "default size; increase it to make the text bigger."
        )
        ts_hint.setObjectName("hint")
        ts_hint.setWordWrap(True)
        form.addRow("", ts_hint)
        hint = QLabel("Changes preview instantly; click Save to keep them.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return self._wrap(form)

    def _build_misc_page(self) -> QWidget:
        self._show_setup = QCheckBox("Show setup menu on startup")

        form = QFormLayout()
        form.addRow("", self._show_setup)
        hint = QLabel(
            "When selected, the welcome/setup wizard opens each time the "
            "application starts"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)

        self._check_updates_startup = QCheckBox(
            "Check for updates on application startup"
        )
        form.addRow("", self._check_updates_startup)
        upd_hint = QLabel(
            "When selected, StarPost checks for a newer release each time it "
            "starts and offers to update if one is available."
        )
        upd_hint.setObjectName("hint")
        upd_hint.setWordWrap(True)
        form.addRow("", upd_hint)

        check_now = QPushButton("Check for updates")
        check_now.setToolTip("Check GitHub now for a newer version")
        check_now.clicked.connect(self._check_for_updates_now)
        form.addRow("", check_now)
        check_hint = QLabel(
            "Check now for a newer version. If one is available, you'll be "
            "asked whether you want to update."
        )
        check_hint.setObjectName("hint")
        check_hint.setWordWrap(True)
        form.addRow("", check_hint)

        reset = QPushButton("Reset settings")
        reset.setToolTip("Restore most settings to their defaults")
        reset.clicked.connect(self._reset_settings)
        form.addRow("", reset)
        reset_hint = QLabel(
            "Restore Files, Reports, Plots, Export, Appearance and Misc settings to "
            "their defaults and reload the Default profile. STAR-CCM+, License and "
            "saved Profiles are left unchanged. Takes effect immediately."
        )
        reset_hint.setObjectName("hint")
        reset_hint.setWordWrap(True)
        form.addRow("", reset_hint)

        clear_temp = QPushButton("Clear all temp files")
        clear_temp.setToolTip("Delete cached logs, generated icons and other temporary files")
        clear_temp.clicked.connect(self._clear_temp_files)
        form.addRow("", clear_temp)
        temp_hint = QLabel(
            "Delete StarPost's temporary and cache files (logs, the crash-recovery "
            "data cache, generated theme icons and downloaded updates). Your "
            "settings and saved profiles are not affected."
        )
        temp_hint.setObjectName("hint")
        temp_hint.setWordWrap(True)
        form.addRow("", temp_hint)
        return self._wrap(form)

    def _clear_temp_files(self) -> None:
        """Warn (listing what will go), then delete every temporary/cache file
        on Yes. Settings and profiles live elsewhere and are left untouched."""
        from starpost.utils.paths import (
            clear_temp_files,
            describe_temp_paths,
            temp_paths,
        )

        paths = temp_paths()
        if not paths:
            QMessageBox.information(
                self, "Clear all temp files", "There are no temporary files to clear."
            )
            return

        listed = "\n".join(f"  • {d}" for d in describe_temp_paths(paths))
        if QMessageBox.question(
            self, "Clear all temp files",
            "This will permanently delete the following temporary files:\n\n"
            f"{listed}\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        removed, failed = clear_temp_files()
        if failed:
            names = "\n".join(f"  • {p.name}" for p in failed)
            QMessageBox.warning(
                self, "Clear all temp files",
                f"Removed {removed} item(s). These could not be removed (they may "
                f"be in use):\n\n{names}",
            )
        else:
            QMessageBox.information(
                self, "Clear all temp files",
                f"Removed {removed} temporary item(s).",
            )

    def _check_for_updates_now(self) -> None:
        """Manual update check from the Misc page. Always reports the outcome
        (including 'up to date'), unlike the quieter automatic startup check."""
        from starpost.gui.update import check_for_updates

        check_for_updates(self, silent_if_current=False)

    def _build_about_page(self) -> QWidget:
        logo = QLabel()
        logo.setPixmap(
            logo_pixmap().scaledToHeight(96, Qt.TransformationMode.SmoothTransformation)
        )

        about = QLabel(
            "StarPost is a standalone desktop tool to automate STAR-CCM+ "
            "post-processing. It extracts report values and monitor plots for "
            "comparison and exports them for spreadsheet manipulation."
        )
        about.setWordWrap(True)

        author = QLabel("Made by Luca Santoni.")
        author.setWordWrap(True)

        repo = QLabel(
            '<a href="https://github.com/luca-santoni/starpost">'
            "github.com/luca-santoni/starpost</a>"
        )
        repo.setOpenExternalLinks(True)
        repo.setTextFormat(Qt.TextFormat.RichText)

        version = QLabel(f"Version {__version__}")
        version.setObjectName("hint")

        form = QFormLayout()
        # Roomier gap between each block of text on this (sparse) page.
        form.setVerticalSpacing(18)
        form.addRow(logo)
        form.addRow(about)
        form.addRow(author)
        form.addRow("GitHub", repo)
        form.addRow(version)
        return self._wrap(form)

    def _reset_settings(self) -> None:
        """Immediately reset every settings group except STAR-CCM+, License and
        saved Profiles back to its default, persist it, and reload the Default
        profile in the main view. The reset is applied and saved on click (not
        deferred to Save), so it stands even if the dialog is then cancelled."""
        if QMessageBox.warning(
            self, "Reset settings",
            "Reset Files, Reports, Plots, Export, Appearance and Misc settings to "
            "their defaults now? This takes effect immediately and cannot be "
            "undone. STAR-CCM+, License and saved profiles are left unchanged.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        d = Settings()  # the defaults
        s = self._settings

        # Overwrite only the resettable groups; STAR-CCM+, License and profiles
        # (separate files) are deliberately left as they are.
        s.show_full_file_names = d.show_full_file_names
        s.report_decimals = d.report_decimals
        s.hide_empty_reports = d.hide_empty_reports
        s.zero_threshold = d.zero_threshold
        s.hide_empty_monitors = d.hide_empty_monitors
        s.monitor_zero_threshold = d.monitor_zero_threshold
        s.moving_average_width = d.moving_average_width
        s.hover_show_monitor_name = d.hover_show_monitor_name
        s.hover_x_decimals = d.hover_x_decimals
        s.hover_y_decimals = d.hover_y_decimals
        s.region_stats = list(d.region_stats)
        s.plot_classification = {
            k: list(v) for k, v in d.plot_classification.items()
        }
        s.appearance.mode = d.appearance.mode
        s.appearance.accent = d.appearance.accent
        s.appearance.checkmark_color = d.appearance.checkmark_color
        s.appearance.checkmark_match_theme = d.appearance.checkmark_match_theme
        s.appearance.folder_color = d.appearance.folder_color
        s.appearance.folder_use_default = d.appearance.folder_use_default
        s.appearance.text_scale = d.appearance.text_scale
        s.show_setup_on_startup = d.show_setup_on_startup
        s.check_updates_on_startup = d.check_updates_on_startup
        s.export_report_format = d.export_report_format
        s.export_plot_format = d.export_plot_format
        s.export_plot_theme = d.export_plot_theme
        s.save()

        # Mirror the reset into the form; the appearance setters live-preview it.
        self._show_full_paths.setChecked(d.show_full_file_names)
        self._decimals.setValue(d.report_decimals)
        self._hide_empty.setChecked(d.hide_empty_reports)
        self._zero_threshold.setText(f"{d.zero_threshold:g}")
        self._hide_empty_monitors.setChecked(d.hide_empty_monitors)
        self._monitor_zero_threshold.setText(f"{d.monitor_zero_threshold:g}")
        self._moving_average_width.setValue(d.moving_average_width)
        self._hover_show_name.setChecked(d.hover_show_monitor_name)
        self._hover_x_decimals.setValue(d.hover_x_decimals)
        self._hover_y_decimals.setValue(d.hover_y_decimals)
        enabled_stats = set(d.region_stats)
        for i in range(self._region_stats.count()):
            item = self._region_stats.item(i)
            item.setCheckState(
                Qt.Checked if item.text() in enabled_stats else Qt.Unchecked
            )
        self._residual.setText(", ".join(d.plot_classification["residual_keywords"]))
        self._force.setText(", ".join(d.plot_classification["force_keywords"]))
        idx = self._theme.findData(d.appearance.mode)
        self._theme.setCurrentIndex(idx if idx >= 0 else 0)
        self._set_accent(d.appearance.accent)
        self._set_checkmark_color(d.appearance.checkmark_color)
        self._cm_match.setChecked(d.appearance.checkmark_match_theme)
        self._on_cm_match_toggled(d.appearance.checkmark_match_theme)
        self._set_folder_color(d.appearance.folder_color)
        self._folder_default_cb.setChecked(d.appearance.folder_use_default)
        self._on_folder_default_toggled(d.appearance.folder_use_default)
        self._text_scale = d.appearance.text_scale
        self._text_scale_spin.setValue(d.appearance.text_scale)
        self._show_setup.setChecked(d.show_setup_on_startup)
        self._check_updates_startup.setChecked(d.check_updates_on_startup)
        ri = self._export_report_format.findText(
            d.export_report_format, Qt.MatchFlag.MatchFixedString
        )
        self._export_report_format.setCurrentIndex(ri if ri >= 0 else 0)
        pi = self._export_plot_format.findText(
            d.export_plot_format, Qt.MatchFlag.MatchFixedString
        )
        self._export_plot_format.setCurrentIndex(pi if pi >= 0 else 0)
        ti = self._export_plot_theme.findData(d.export_plot_theme)
        self._export_plot_theme.setCurrentIndex(ti if ti >= 0 else 0)

        # The reset is committed, so a later Cancel must not revert the new theme.
        self._orig_mode = s.appearance.mode
        self._orig_accent = normalize_accent(s.appearance.accent)
        self._orig_checkmark = s.appearance.resolved_checkmark()
        self._orig_folder_color = s.appearance.resolved_folder_color()
        self._orig_text_scale = s.appearance.text_scale

        self.defaults_reset.emit()

    # --- appearance helpers ---------------------------------------------
    def _current_mode(self) -> str:
        return self._theme.currentData()

    def _on_text_scale_changed(self, value: float) -> None:
        """Remember the new text-size multiplier and live-preview it app-wide."""
        self._text_scale = value
        self._apply_preview()

    def _set_accent(self, accent: str, *, update_field: bool = True) -> None:
        """Set the active accent, refresh swatch/preview/field, live-preview it."""
        self._accent = normalize_accent(accent)
        if update_field:
            self._hex.setText(self._accent)
        self._refresh_swatches()
        self._preview.setStyleSheet(
            f"background-color: {self._accent};"
            f" border: 1px solid {contrast_color(self._accent)}; border-radius: 4px;"
        )
        self._update_checkmark_preview()  # follows the accent when matching
        self._apply_preview()

    def _build_swatches(self, on_pick):
        """A grid of preset-colour swatch buttons; clicking one calls ``on_pick``
        with its hex. Returns ``(widget, buttons)``."""
        swatches: list[QPushButton] = []
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (name, color) in enumerate(ACCENT_PRESETS):
            btn = QPushButton()
            btn.setToolTip(f"{name}  {color}")
            btn.setFixedSize(30, 30)
            btn.setProperty("accent_hex", color)
            btn.clicked.connect(lambda _=False, c=color: on_pick(c))
            swatches.append(btn)
            grid.addWidget(btn, i // 4, i % 4)
        box = QWidget()
        box.setLayout(grid)
        return box, swatches

    @staticmethod
    def _refresh_swatch_grid(swatches: list[QPushButton], active: str) -> None:
        for btn in swatches:
            color = btn.property("accent_hex")
            selected = normalize_accent(color) == active
            ring = (
                f"3px solid {contrast_color(color)}"
                if selected
                else "1px solid rgba(127, 127, 127, 0.6)"
            )
            btn.setStyleSheet(
                f"background-color: {color}; border: {ring};"
                " border-radius: 4px; padding: 0;"
            )

    def _refresh_swatches(self) -> None:
        self._refresh_swatch_grid(self._swatches, self._accent)

    def _on_hex_edited(self, text: str) -> None:
        h = text.lstrip("#")
        if len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h):
            self._set_accent(text, update_field=False)

    def _on_pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._accent), self, "Accent colour")
        if chosen.isValid():
            self._set_accent(chosen.name())

    # --- checkmark colour ------------------------------------------------
    def _effective_checkmark(self) -> str:
        """The checkmark colour in effect: the accent when matching, else the
        explicit checkmark colour."""
        return self._accent if self._checkmark_match else self._checkmark_color

    def _update_checkmark_preview(self) -> None:
        color = self._effective_checkmark()
        self._cm_preview.setStyleSheet(
            f"background-color: {color};"
            f" border: 1px solid {contrast_color(color)}; border-radius: 4px;"
        )

    def _on_cm_match_toggled(self, checked: bool) -> None:
        self._checkmark_match = checked
        # The explicit-colour controls are irrelevant while matching the theme.
        self._cm_hex.setEnabled(not checked)
        self._cm_pick.setEnabled(not checked)
        self._update_checkmark_preview()
        self._apply_preview()

    def _set_checkmark_color(self, color: str, *, update_field: bool = True) -> None:
        self._checkmark_color = normalize_accent(color)
        if update_field:
            self._cm_hex.setText(self._checkmark_color)
        self._update_checkmark_preview()
        self._apply_preview()

    def _on_cm_hex_edited(self, text: str) -> None:
        h = text.lstrip("#")
        if len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h):
            self._set_checkmark_color(text, update_field=False)

    def _on_cm_pick_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(self._checkmark_color), self, "Checkmark colour"
        )
        if chosen.isValid():
            self._set_checkmark_color(chosen.name())

    # --- folder colour ---------------------------------------------------
    def _effective_folder_color(self) -> str:
        """The folder tint in effect: empty (default icon) when "use default" is
        ticked, otherwise the chosen colour."""
        return "" if self._folder_default else self._folder_color

    def _update_folder_preview(self) -> None:
        color = self._folder_color
        self._folder_preview.setStyleSheet(
            f"background-color: {color};"
            f" border: 1px solid {contrast_color(color)}; border-radius: 4px;"
        )

    def _emit_folder_preview(self) -> None:
        if self._loading:
            return
        self.folder_color_changed.emit(self._effective_folder_color())

    def _on_folder_default_toggled(self, checked: bool) -> None:
        self._folder_default = checked
        # The colour controls are irrelevant while using the default icon.
        self._folder_hex.setEnabled(not checked)
        self._folder_pick.setEnabled(not checked)
        self._emit_folder_preview()

    def _set_folder_color(self, color: str, *, update_field: bool = True) -> None:
        self._folder_color = normalize_accent(color)
        if update_field:
            self._folder_hex.setText(self._folder_color)
        self._update_folder_preview()
        self._emit_folder_preview()

    def _on_folder_hex_edited(self, text: str) -> None:
        h = text.lstrip("#")
        if len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h):
            self._set_folder_color(text, update_field=False)

    def _on_folder_pick_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(self._folder_color), self, "Folder colour"
        )
        if chosen.isValid():
            self._set_folder_color(chosen.name())

    def _apply_preview(self) -> None:
        # During initial population the active stylesheet already matches; skip
        # the costly whole-app reapply (and the redundant preview_changed emit).
        if self._loading:
            return
        mode = self._current_mode()
        apply_theme(
            QApplication.instance(),
            mode,
            self._accent,
            self._effective_checkmark(),
            self._text_scale,
        )
        # Only the mode (not accent) affects non-QSS widgets; notify on change.
        if mode != self._last_preview_mode:
            self._last_preview_mode = mode
            self.preview_changed.emit(mode)

    # --- browse helpers -------------------------------------------------
    def _browse_exe(self) -> None:
        f, _ = QFileDialog.getOpenFileName(
            self, "STAR-CCM+ executable", self._exe.text(), exe_dialog_filter()
        )
        if f:
            self._exe.setText(f)

    def _browse_out(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Default output folder", self._out.text()
        )
        if d:
            self._out.setText(d)

    def _browse_licfile(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "License file", self._licfile.text())
        if f:
            self._licfile.setText(f)

    # --- license mode toggling ------------------------------------------
    def _sync_license_mode(self) -> None:
        server = self._mode.currentData() == "podkey_server"
        for w in (self._podkey, self._podkey_label,
                  self._licpath, self._licpath_label):
            w.setEnabled(server)
        for w in (self._licfile, self._licfile_label):
            w.setEnabled(not server)

    # --- load / save ----------------------------------------------------
    def _load_from_settings(self) -> None:
        s = self._settings
        self._exe.setText(s.starccm_path)
        self._out.setText(s.default_output_dir)
        self._extra.setText(" ".join(s.extra_args))

        idx = self._mode.findData(s.license.mode)
        self._mode.setCurrentIndex(idx if idx >= 0 else 0)
        self._podkey.setText(s.license.podkey)
        self._licpath.setText(s.license.licpath)
        self._licfile.setText(s.license.license_file)

        self._show_full_paths.setChecked(s.show_full_file_names)
        self._show_setup.setChecked(s.show_setup_on_startup)
        self._check_updates_startup.setChecked(s.check_updates_on_startup)

        self._decimals.setValue(s.report_decimals)
        self._hide_empty.setChecked(s.hide_empty_reports)
        self._zero_threshold.setText(f"{s.zero_threshold:g}")

        self._hide_empty_monitors.setChecked(s.hide_empty_monitors)
        self._monitor_zero_threshold.setText(f"{s.monitor_zero_threshold:g}")
        self._moving_average_width.setValue(s.moving_average_width)
        self._hover_show_name.setChecked(s.hover_show_monitor_name)
        self._hover_x_decimals.setValue(s.hover_x_decimals)
        self._hover_y_decimals.setValue(s.hover_y_decimals)

        enabled_stats = set(s.region_stats)
        for i in range(self._region_stats.count()):
            item = self._region_stats.item(i)
            item.setCheckState(
                Qt.Checked if item.text() in enabled_stats else Qt.Unchecked
            )

        pc = s.plot_classification or {}
        self._residual.setText(", ".join(pc.get("residual_keywords", [])))
        self._force.setText(", ".join(pc.get("force_keywords", [])))

        # Export defaults: formats match by display text; the theme combo carries
        # the "light"/"dark" mode as item data.
        ri = self._export_report_format.findText(
            s.export_report_format, Qt.MatchFlag.MatchFixedString
        )
        self._export_report_format.setCurrentIndex(ri if ri >= 0 else 0)
        pi = self._export_plot_format.findText(
            s.export_plot_format, Qt.MatchFlag.MatchFixedString
        )
        self._export_plot_format.setCurrentIndex(pi if pi >= 0 else 0)
        ti = self._export_plot_theme.findData(s.export_plot_theme)
        self._export_plot_theme.setCurrentIndex(ti if ti >= 0 else 0)

        idx = self._theme.findData(s.appearance.mode)
        self._theme.setCurrentIndex(idx if idx >= 0 else 0)
        self._set_accent(s.appearance.accent)

        # Checkmark colour: set the explicit colour first, then the match toggle
        # (its handler decides whether that colour or the accent is in effect).
        self._set_checkmark_color(s.appearance.checkmark_color)
        self._cm_match.setChecked(s.appearance.checkmark_match_theme)
        self._on_cm_match_toggled(s.appearance.checkmark_match_theme)

        # Folder colour: set the explicit colour, then the "use default" toggle.
        self._set_folder_color(s.appearance.folder_color)
        self._folder_default_cb.setChecked(s.appearance.folder_use_default)
        self._on_folder_default_toggled(s.appearance.folder_use_default)

        # Text size multiplier.
        self._text_scale = s.appearance.text_scale
        self._text_scale_spin.setValue(s.appearance.text_scale)

    def _on_accept(self) -> None:
        s = self._settings
        s.appearance.mode = self._current_mode()
        s.appearance.accent = self._accent
        s.appearance.checkmark_color = self._checkmark_color
        s.appearance.checkmark_match_theme = self._checkmark_match
        s.appearance.folder_color = self._folder_color
        s.appearance.folder_use_default = self._folder_default
        s.appearance.text_scale = self._text_scale
        s.show_full_file_names = self._show_full_paths.isChecked()
        s.show_setup_on_startup = self._show_setup.isChecked()
        s.check_updates_on_startup = self._check_updates_startup.isChecked()
        s.report_decimals = self._decimals.value()
        s.hide_empty_reports = self._hide_empty.isChecked()
        try:
            s.zero_threshold = abs(float(self._zero_threshold.text()))
        except ValueError:
            pass  # keep previous value if the field is blank/invalid
        s.hide_empty_monitors = self._hide_empty_monitors.isChecked()
        try:
            s.monitor_zero_threshold = abs(float(self._monitor_zero_threshold.text()))
        except ValueError:
            pass  # keep previous value if the field is blank/invalid
        s.moving_average_width = self._moving_average_width.value()
        s.hover_show_monitor_name = self._hover_show_name.isChecked()
        s.hover_x_decimals = self._hover_x_decimals.value()
        s.hover_y_decimals = self._hover_y_decimals.value()
        s.region_stats = [
            self._region_stats.item(i).text()
            for i in range(self._region_stats.count())
            if self._region_stats.item(i).checkState() == Qt.Checked
        ]
        s.starccm_path = self._exe.text().strip()
        s.default_output_dir = self._out.text().strip()
        s.extra_args = shlex.split(self._extra.text())
        s.license = LicenseConfig(
            mode=self._mode.currentData(),
            podkey=self._podkey.text().strip(),
            licpath=self._licpath.text().strip(),
            license_file=self._licfile.text().strip(),
        )
        s.plot_classification = {
            "residual_keywords": _csv(self._residual.text()),
            "force_keywords": _csv(self._force.text()),
        }
        s.export_report_format = self._export_report_format.currentText()
        s.export_plot_format = self._export_plot_format.currentText()
        s.export_plot_theme = self._export_plot_theme.currentData()
        s.save()
        self.accept()

    def reject(self) -> None:  # noqa: D401 (Qt override)
        # Cancel: undo any live appearance preview before closing.
        apply_theme(
            QApplication.instance(),
            self._orig_mode,
            self._orig_accent,
            self._orig_checkmark,
            self._orig_text_scale,
        )
        if self._orig_mode != self._last_preview_mode:
            self._last_preview_mode = self._orig_mode
            self.preview_changed.emit(self._orig_mode)
        self.folder_color_changed.emit(self._orig_folder_color)
        super().reject()
