"""First-run welcome / setup wizard.

Shown on startup while Settings.show_setup_on_startup is true. It collects the
essential configuration a new user needs (STAR-CCM+ paths, licensing, theme) so
they can get going without first hunting through the full Settings dialog, then
points them at Settings and the documentation for everything else.

Theme changes preview live (like the Settings dialog); closing without
finishing reverts the preview. Finishing writes every field into the shared
Settings object and persists it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from starpost.core.settings import LicenseConfig, Settings
from starpost.core.starccm_runner import exe_dialog_filter, exe_placeholder
from starpost.gui.theme import (
    ACCENT_PRESETS,
    apply_theme,
    contrast_color,
    normalize_accent,
)
from starpost.gui.widgets import SecretLineEdit

# Sensible default for the POD license server, prefilled so users on the stock
# Siemens cloud server only have to enter their key.
DEFAULT_POD_SERVER = "1999@flex.cd-adapco.com"


class WelcomeDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Welcome to StarPost")
        self.resize(640, 680)

        # Remember the live appearance so closing without finishing reverts the
        # theme preview.
        self._orig_mode = settings.appearance.mode
        self._orig_accent = normalize_accent(settings.appearance.accent)
        self._accent = self._orig_accent

        # Scrollable body so the wizard stays usable on short screens.
        body = QWidget()
        inner = QVBoxLayout(body)
        inner.addWidget(self._header())
        inner.addWidget(self._starccm_group())
        inner.addWidget(self._license_group())
        inner.addWidget(self._theme_group())
        inner.addWidget(self._info_label())
        inner.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)

        # Persisted across launches via the same flag the Misc settings page
        # exposes; pre-checked to match the current setting.
        self._show_again = QCheckBox("Show this setup on startup")
        self._show_again.setChecked(settings.show_setup_on_startup)

        buttons = QDialogButtonBox()
        buttons.addButton("Get Started", QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._show_again)
        layout.addWidget(buttons)

        self._load_from_settings()
        self._sync_license_mode()

    # --- sections --------------------------------------------------------
    def _header(self) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Welcome to StarPost")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        about = QLabel(
            "StarPost is a custom post processing software for Star CCM+ focused "
            "on numerical analysis."
        )
        about.setWordWrap(True)
        intro = QLabel(
            "Let's get a few essentials set up. You can change all of this later "
            "from the Settings… button in the toolbar."
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        v.addWidget(title)
        v.addWidget(about)
        v.addWidget(intro)
        return box

    def _starccm_group(self) -> QWidget:
        self._exe = QLineEdit()
        self._exe.setPlaceholderText(exe_placeholder())
        self._out = QLineEdit()
        self._out.setPlaceholderText("Empty = your home folder")

        form = QFormLayout()
        form.addRow("Executable Location", self._path_row(self._exe, self._browse_exe))
        form.addRow("Output folder", self._path_row(self._out, self._browse_out))
        group = QGroupBox("STAR-CCM+")
        group.setLayout(form)
        return group

    def _license_group(self) -> QWidget:
        self._mode = QComboBox()
        self._mode.addItem("POD key + license server", "podkey_server")
        self._mode.addItem("License file", "license_file")
        self._mode.currentIndexChanged.connect(self._sync_license_mode)

        self._podkey = SecretLineEdit()
        self._podkey.setPlaceholderText("Power-on-Demand key")
        self._licpath = QLineEdit()
        self._licpath.setPlaceholderText(DEFAULT_POD_SERVER)
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
            self._licfile_label, self._path_row(self._licfile, self._browse_licfile)
        )
        group = QGroupBox("Licensing")
        group.setLayout(form)
        return group

    def _theme_group(self) -> QWidget:
        self._theme = QComboBox()
        self._theme.addItem("Dark", "dark")
        self._theme.addItem("Light", "light")
        self._theme.currentIndexChanged.connect(self._apply_preview)

        # Accent preset swatches, mirroring the Settings appearance page.
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

        pick = QPushButton("Pick…")
        pick.clicked.connect(self._pick_accent)

        form = QFormLayout()
        form.addRow("Theme", self._theme)
        form.addRow("Accent", swatch_box)
        form.addRow("", pick)
        group = QGroupBox("Appearance")
        group.setLayout(form)
        return group

    def _info_label(self) -> QWidget:
        info = QLabel(
            "Open <b>Settings…</b> from the toolbar to customize reports, plots, "
            "profiles and more. For full details and advanced usage, please read "
            "the documentation."
        )
        info.setWordWrap(True)
        info.setObjectName("hint")
        return info

    # --- small helpers ---------------------------------------------------
    @staticmethod
    def _path_row(line: QLineEdit, on_browse) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line)
        btn = QPushButton("Browse…")
        btn.clicked.connect(on_browse)
        row.addWidget(btn)
        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

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

    def _sync_license_mode(self) -> None:
        server = self._mode.currentData() == "podkey_server"
        for w in (self._podkey, self._podkey_label, self._licpath, self._licpath_label):
            w.setEnabled(server)
        for w in (self._licfile, self._licfile_label):
            w.setEnabled(not server)

    # --- theme preview ---------------------------------------------------
    def _resolved_checkmark(self) -> str:
        a = self._settings.appearance
        return self._accent if a.checkmark_match_theme else a.checkmark_color

    def _set_accent(self, accent: str) -> None:
        self._accent = normalize_accent(accent)
        self._refresh_swatches()
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

    def _pick_accent(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._accent), self, "Accent colour")
        if chosen.isValid():
            self._set_accent(chosen.name())

    def _apply_preview(self) -> None:
        apply_theme(
            QApplication.instance(),
            self._theme.currentData(),
            self._accent,
            self._resolved_checkmark(),
        )

    # --- load / save -----------------------------------------------------
    def _load_from_settings(self) -> None:
        s = self._settings
        self._exe.setText(s.starccm_path)
        self._out.setText(s.default_output_dir)

        idx = self._mode.findData(s.license.mode)
        self._mode.setCurrentIndex(idx if idx >= 0 else 0)
        self._podkey.setText(s.license.podkey)
        # Prefill the stock POD server on first run so the default just works.
        self._licpath.setText(s.license.licpath or DEFAULT_POD_SERVER)
        self._licfile.setText(s.license.license_file)

        idx = self._theme.findData(s.appearance.mode)
        self._theme.setCurrentIndex(idx if idx >= 0 else 0)
        self._set_accent(s.appearance.accent)

    def _on_accept(self) -> None:
        s = self._settings
        s.starccm_path = self._exe.text().strip()
        s.default_output_dir = self._out.text().strip()
        s.license = LicenseConfig(
            mode=self._mode.currentData(),
            podkey=self._podkey.text().strip(),
            licpath=self._licpath.text().strip(),
            license_file=self._licfile.text().strip(),
        )
        s.appearance.mode = self._theme.currentData()
        s.appearance.accent = self._accent
        s.show_setup_on_startup = self._show_again.isChecked()
        self._apply_preview()  # keep the chosen theme
        s.save()
        self.accept()

    def reject(self) -> None:  # noqa: D401 (Qt override)
        # Closed without finishing: don't keep the setup entries, but still
        # honour the startup-visibility choice so unchecking it here sticks
        # (and is reflected in the Misc settings page).
        self._settings.show_setup_on_startup = self._show_again.isChecked()
        self._settings.save()
        # Revert the live theme preview.
        apply_theme(
            QApplication.instance(),
            self._orig_mode,
            self._orig_accent,
            self._settings.appearance.resolved_checkmark(),
        )
        super().reject()
