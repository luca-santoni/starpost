"""Settings dialog: edit every application setting from the YAML file.

Layout: a left-hand nav lists the setting *groups*; the right-hand stack shows
that group's individual settings. On Save, the values are written back into the
Settings object and persisted via Settings.save().

Covers everything in settings.yaml:
  - STAR-CCM+:  starccm_path, default_output_dir, extra_args
  - License:    mode, podkey, licpath, license_file
  - Reports:    report_decimals, hide_empty_reports, zero_threshold
  - Plots:      hide_empty_monitors, monitor_zero_threshold, hover_show_monitor_name,
                hover_x_decimals, hover_y_decimals, classification keywords

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
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from starpost.core.settings import (
    LicenseConfig,
    Profile,
    Settings,
    delete_profile,
    list_profiles,
)
from starpost.gui.theme import (
    ACCENT_PRESETS,
    apply_theme,
    contrast_color,
    normalize_accent,
)


def _csv(text: str) -> list[str]:
    """Parse a comma-separated field into a list of trimmed, non-empty tokens."""
    return [t.strip() for t in text.split(",") if t.strip()]


def _path_row(line: QLineEdit, on_browse) -> QHBoxLayout:
    """A line edit followed by a Browse… button."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(line)
    btn = QPushButton("Browse…")
    btn.clicked.connect(on_browse)
    row.addWidget(btn)
    return row


class ProfileDetailsDialog(QDialog):
    """Read-only view of one profile's selected reports and plots/monitors."""

    def __init__(self, profile: Profile, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Profile: {profile.name}")
        self.resize(540, 420)

        reports = QListWidget()
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

        cols = QHBoxLayout()
        cols.addLayout(self._column("Reports", reports), 1)
        cols.addLayout(self._column("Plots", plots), 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
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

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(660, 460)
        self._settings = settings

        # Remember the live appearance so Cancel can revert the preview.
        self._orig_mode = settings.appearance.mode
        self._orig_accent = settings.appearance.accent
        self._accent = normalize_accent(settings.appearance.accent)
        self._last_preview_mode = self._orig_mode

        # Left nav (groups) drives the right stack (individual settings).
        self._nav = QListWidget()
        self._nav.setObjectName("settingsNav")
        self._nav.setMaximumWidth(180)
        self._stack = QStackedWidget()

        self._add_page("STAR-CCM+", self._build_starccm_page())
        self._add_page("License", self._build_license_page())
        self._add_page("Reports", self._build_reports_page())
        self._add_page("Plots", self._build_plots_page())
        self._add_page("Profiles", self._build_profiles_page())
        self._add_page("Appearance", self._build_appearance_page())

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        body = QHBoxLayout()
        body.addWidget(self._nav)
        body.addWidget(self._stack, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)

        self._load_from_settings()
        self._sync_license_mode()

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
        self._exe.setPlaceholderText("/path/to/starccm+")
        self._out = QLineEdit()
        self._out.setPlaceholderText("Empty = your home folder")
        self._extra = QLineEdit()
        self._extra.setPlaceholderText("e.g.  -np 4 -mpi openmpi")

        form = QFormLayout()
        form.addRow("Executable path", _path_row(self._exe, self._browse_exe))
        form.addRow("Default output folder", _path_row(self._out, self._browse_out))
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

        self._podkey = QLineEdit()
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
            self._licfile_label, _path_row(self._licfile, self._browse_licfile)
        )
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

        self._hover_show_name = QCheckBox("Show monitor name in hover label")

        self._hover_x_decimals = QSpinBox()
        self._hover_x_decimals.setRange(0, 15)
        self._hover_x_decimals.setValue(0)
        self._hover_y_decimals = QSpinBox()
        self._hover_y_decimals.setRange(0, 15)
        self._hover_y_decimals.setValue(4)

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
        form.addRow("", self._hover_show_name)
        hover_hint = QLabel(
            "When off, hovering a line shows only its coordinates, without the "
            "monitor's name."
        )
        hover_hint.setObjectName("hint")
        hover_hint.setWordWrap(True)
        form.addRow("", hover_hint)
        form.addRow("Hover X decimals", self._hover_x_decimals)
        form.addRow("Hover Y decimals", self._hover_y_decimals)
        dec_hint = QLabel(
            "Decimal places shown for the X and Y coordinates in the hover label."
        )
        dec_hint.setObjectName("hint")
        dec_hint.setWordWrap(True)
        form.addRow("", dec_hint)
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

    def _build_profiles_page(self) -> QWidget:
        # A header row plus one row per saved profile, rebuilt on delete.
        page = QWidget()
        outer = QVBoxLayout(page)
        intro = QLabel(
            "Saved selection profiles. Deleting one removes it permanently."
        )
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        self._profiles_list = QVBoxLayout()
        self._profiles_list.setContentsMargins(0, 4, 0, 0)
        self._profiles_list.setSpacing(4)
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

        names = list_profiles()
        if not names:
            empty = QLabel("No saved profiles yet.")
            empty.setObjectName("hint")
            self._profiles_list.addWidget(empty)
            return

        for name in names:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(QLabel(name))
            rl.addStretch(1)
            details = QPushButton("Show Details")
            details.clicked.connect(lambda _=False, n=name: self._show_profile_details(n))
            rl.addWidget(details)
            btn = QPushButton("Delete")
            btn.setObjectName("dangerButton")
            btn.clicked.connect(lambda _=False, n=name: self._delete_profile(n))
            rl.addWidget(btn)
            self._profiles_list.addWidget(row)

    def _show_profile_details(self, name: str) -> None:
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
        self._swatches: list[QPushButton] = []
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (name, color) in enumerate(ACCENT_PRESETS):
            btn = QPushButton()
            btn.setToolTip(f"{name}  {color}")
            btn.setFixedSize(30, 30)
            btn.setProperty("accent_hex", color)
            btn.clicked.connect(lambda _=False, c=color: self._set_accent(c))
            self._swatches.append(btn)
            grid.addWidget(btn, i // 4, i % 4)
        swatch_box = QWidget()
        swatch_box.setLayout(grid)

        # Custom hex + colour picker + live preview chip
        self._hex = QLineEdit()
        self._hex.setMaxLength(7)
        self._hex.setPlaceholderText("#rrggbb")
        self._hex.setFixedWidth(110)
        self._hex.textEdited.connect(self._on_hex_edited)
        pick = QPushButton("Pick…")
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

        form = QFormLayout()
        form.addRow("Theme", self._theme)
        form.addRow("Accent presets", swatch_box)
        form.addRow("Custom accent", custom_box)
        hint = QLabel("Changes preview instantly; click Save to keep them.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return self._wrap(form)

    # --- appearance helpers ---------------------------------------------
    def _current_mode(self) -> str:
        return self._theme.currentData()

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
        self._apply_preview()

    def _refresh_swatches(self) -> None:
        for btn in self._swatches:
            color = btn.property("accent_hex")
            selected = normalize_accent(color) == self._accent
            ring = (
                f"3px solid {contrast_color(color)}"
                if selected
                else "1px solid rgba(127, 127, 127, 0.6)"
            )
            btn.setStyleSheet(
                f"background-color: {color}; border: {ring};"
                " border-radius: 4px; padding: 0;"
            )

    def _on_hex_edited(self, text: str) -> None:
        h = text.lstrip("#")
        if len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h):
            self._set_accent(text, update_field=False)

    def _on_pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._accent), self, "Accent colour")
        if chosen.isValid():
            self._set_accent(chosen.name())

    def _apply_preview(self) -> None:
        mode = self._current_mode()
        apply_theme(QApplication.instance(), mode, self._accent)
        # Only the mode (not accent) affects non-QSS widgets; notify on change.
        if mode != self._last_preview_mode:
            self._last_preview_mode = mode
            self.preview_changed.emit(mode)

    # --- browse helpers -------------------------------------------------
    def _browse_exe(self) -> None:
        f, _ = QFileDialog.getOpenFileName(
            self, "STAR-CCM+ executable", self._exe.text()
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
        for w in (self._podkey, self._podkey_label, self._licpath, self._licpath_label):
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

        self._decimals.setValue(s.report_decimals)
        self._hide_empty.setChecked(s.hide_empty_reports)
        self._zero_threshold.setText(f"{s.zero_threshold:g}")

        self._hide_empty_monitors.setChecked(s.hide_empty_monitors)
        self._monitor_zero_threshold.setText(f"{s.monitor_zero_threshold:g}")
        self._hover_show_name.setChecked(s.hover_show_monitor_name)
        self._hover_x_decimals.setValue(s.hover_x_decimals)
        self._hover_y_decimals.setValue(s.hover_y_decimals)

        pc = s.plot_classification or {}
        self._residual.setText(", ".join(pc.get("residual_keywords", [])))
        self._force.setText(", ".join(pc.get("force_keywords", [])))

        idx = self._theme.findData(s.appearance.mode)
        self._theme.setCurrentIndex(idx if idx >= 0 else 0)
        self._set_accent(s.appearance.accent)

    def _on_accept(self) -> None:
        s = self._settings
        s.appearance.mode = self._current_mode()
        s.appearance.accent = self._accent
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
        s.hover_show_monitor_name = self._hover_show_name.isChecked()
        s.hover_x_decimals = self._hover_x_decimals.value()
        s.hover_y_decimals = self._hover_y_decimals.value()
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
        s.save()
        self.accept()

    def reject(self) -> None:  # noqa: D401 (Qt override)
        # Cancel: undo any live appearance preview before closing.
        apply_theme(QApplication.instance(), self._orig_mode, self._orig_accent)
        if self._orig_mode != self._last_preview_mode:
            self._last_preview_mode = self._orig_mode
            self.preview_changed.emit(self._orig_mode)
        super().reject()
