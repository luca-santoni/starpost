"""Tests for the Appearance "Text size" multiplier.

Covers three layers:
  * the settings model (default, round-trip, clamping of out-of-range values),
  * the theme (the multiplier scales the base UI font size in the QSS), and
  * the GUI (the Settings dialog reflects/saves/reverts it, and the whole app —
    including the main window — still builds and themes at an enlarged size).
"""
import re

import pytest

import starpost.utils.paths as paths
from starpost.core.settings import (
    MAX_TEXT_SCALE,
    MIN_TEXT_SCALE,
    Settings,
    clamp_text_scale,
)
from starpost.gui.theme import BASE_FONT_PX, apply_theme, build_stylesheet


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    """Point every per-user location (config, cache, profiles) at a temp dir.

    All path helpers resolve through platformdirs, so patching its two directory
    functions isolates settings, profiles and the generated theme icons without
    touching the developer's real files."""
    monkeypatch.setattr(
        paths.platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path / "config")
    )
    monkeypatch.setattr(
        paths.platformdirs, "user_cache_dir", lambda *a, **k: str(tmp_path / "cache")
    )
    return tmp_path


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _qss_font_px(qss: str) -> int:
    """The base UI font size (px) declared on QWidget in a generated stylesheet."""
    m = re.search(r"font-size:\s*(\d+)px", qss)
    assert m is not None, "stylesheet has no px font-size"
    return int(m.group(1))


# --- settings model --------------------------------------------------------
def test_text_scale_defaults_to_one():
    # The default is the original size, so existing users see no change.
    assert Settings.from_dict({}).appearance.text_scale == 1.0
    assert MIN_TEXT_SCALE == 1.0


def test_legacy_settings_without_text_scale_default_to_one():
    # Settings written before this option existed have no "text_scale" key.
    s = Settings.from_dict({"appearance": {"mode": "light", "accent": "#4e79a7"}})
    assert s.appearance.text_scale == 1.0


def test_text_scale_round_trips():
    s = Settings.from_dict({"appearance": {"text_scale": 1.5}})
    assert s.appearance.text_scale == 1.5
    # Serialising and re-parsing preserves the value.
    assert Settings.from_dict(s.to_dict()).appearance.text_scale == 1.5


def test_text_scale_below_minimum_is_clamped_up():
    # Shrinking below the original size isn't allowed; it floors at 1.0.
    assert Settings.from_dict({"appearance": {"text_scale": 0.5}}).appearance.text_scale == 1.0


def test_text_scale_above_maximum_is_clamped_down():
    s = Settings.from_dict({"appearance": {"text_scale": 99.0}})
    assert s.appearance.text_scale == MAX_TEXT_SCALE


def test_text_scale_invalid_falls_back_to_one():
    assert Settings.from_dict({"appearance": {"text_scale": "huge"}}).appearance.text_scale == 1.0


def test_clamp_text_scale_helper():
    assert clamp_text_scale(0.0) == MIN_TEXT_SCALE
    assert clamp_text_scale(1.4) == 1.4
    assert clamp_text_scale(1000) == MAX_TEXT_SCALE
    assert clamp_text_scale(None) == MIN_TEXT_SCALE


# --- theme -----------------------------------------------------------------
# build_stylesheet renders the checkmark icon (a QPixmap), so it needs a running
# QApplication — hence the app fixture even where the assertion is text-only.
def test_default_scale_uses_base_font_size(app):
    assert _qss_font_px(build_stylesheet("dark", "#ffc829", None, 1.0)) == BASE_FONT_PX


def test_scale_enlarges_the_font(app):
    px_1x = _qss_font_px(build_stylesheet("dark", "#ffc829", None, 1.0))
    px_2x = _qss_font_px(build_stylesheet("dark", "#ffc829", None, 2.0))
    assert px_2x == round(BASE_FONT_PX * 2.0)
    assert px_2x > px_1x


def test_apply_theme_pushes_scaled_font_onto_app(app):
    apply_theme(app, "dark", "#ffc829", None, 2.0)
    try:
        assert _qss_font_px(app.styleSheet()) == round(BASE_FONT_PX * 2.0)
    finally:
        apply_theme(app, "dark", "#ffc829", None, 1.0)  # restore for other tests


# --- Settings dialog -------------------------------------------------------
def test_dialog_reflects_saved_text_scale(app):
    from starpost.gui.views.settings_dialog import SettingsDialog

    settings = Settings.from_dict({"appearance": {"text_scale": 1.5}})
    dlg = SettingsDialog(settings)
    try:
        assert dlg._text_scale_spin.value() == 1.5
    finally:
        dlg.deleteLater()


def test_dialog_change_and_save_persists_text_scale(app):
    from starpost.gui.views.settings_dialog import SettingsDialog

    settings = Settings.from_dict({})
    dlg = SettingsDialog(settings)
    try:
        dlg._text_scale_spin.setValue(1.4)
        dlg._on_accept()  # Save
        assert settings.appearance.text_scale == 1.4
        # Persisted to disk: a fresh load sees the saved multiplier.
        assert Settings.load().appearance.text_scale == 1.4
    finally:
        dlg.deleteLater()


def test_dialog_cancel_reverts_live_preview(app):
    from starpost.gui.views.settings_dialog import SettingsDialog

    apply_theme(app, "dark", "#ffc829", None, 1.0)
    settings = Settings.from_dict({})  # starts at 1.0
    dlg = SettingsDialog(settings)
    try:
        dlg._text_scale_spin.setValue(MAX_TEXT_SCALE)  # live-previews bigger text
        assert _qss_font_px(app.styleSheet()) == round(BASE_FONT_PX * MAX_TEXT_SCALE)
        dlg.reject()  # Cancel
        assert _qss_font_px(app.styleSheet()) == BASE_FONT_PX
        assert settings.appearance.text_scale == 1.0  # nothing saved
    finally:
        dlg.deleteLater()
        apply_theme(app, "dark", "#ffc829", None, 1.0)


# --- whole app -------------------------------------------------------------
def test_main_window_builds_at_enlarged_text_scale(app):
    """The app functions normally with a non-default text size: the main window
    and its panels build, and the enlarged font is in effect."""
    from starpost.gui.main_window import MainWindow

    settings = Settings.from_dict({"appearance": {"text_scale": MAX_TEXT_SCALE}})
    apply_theme(
        app, settings.appearance.mode, settings.appearance.accent, None,
        settings.appearance.text_scale,
    )
    win = MainWindow(settings)
    try:
        assert win.file_list is not None
        assert win.data_list is not None
        assert win.plot_view is not None
        assert _qss_font_px(app.styleSheet()) == round(BASE_FONT_PX * MAX_TEXT_SCALE)
    finally:
        win.close()
        win.deleteLater()
        apply_theme(app, "dark", "#ffc829", None, 1.0)
