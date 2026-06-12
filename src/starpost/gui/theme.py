"""Dynamic application theme.

The stylesheet is generated from two inputs the user controls in Settings →
Appearance:

  * ``mode``   -- "dark" or "light" (selects a colour palette)
  * ``accent`` -- a hex colour (e.g. "#ffc829") applied to buttons borders, the
                  selected tab, progress bars and the settings nav highlight.

`build_stylesheet` returns the QSS; `apply_theme` pushes it onto the running
QApplication so changes take effect live.
"""
from __future__ import annotations

from string import Template

# A curated set of accent presets offered as clickable swatches in the UI.
ACCENT_PRESETS: list[tuple[str, str]] = [
    ("Amber", "#ffc829"),
    ("Blue", "#4e79a7"),
    ("Teal", "#76b7b2"),
    ("Green", "#59a14f"),
    ("Orange", "#f28e2b"),
    ("Red", "#e15759"),
    ("Purple", "#b07aa1"),
    ("Pink", "#ff9da7"),
]

DEFAULT_ACCENT = "#ffc829"
DEFAULT_MODE = "dark"


_DARK = {
    "window_bg": "#1e1e1e",
    "text": "#e6e6e6",
    "subtle": "#cfcfcf",
    "hint": "#9a9a9a",
    "border": "#333333",
    "base_bg": "#232323",
    "alt_bg": "#1c1c1c",
    "input_bg": "#2a2a2a",
    "btn_bg": "#2a2a2a",
    "btn_text": "#ffffff",
    "btn_hover": "#353535",
    "btn_pressed": "#1e1e1e",
    "dis_bg": "#242424",
    "dis_text": "#6f6f6f",
    "dis_border": "#3a3a3a",
    "console_bg": "#161616",
    "console_text": "#d4d4d4",
    "tab_bg": "#262626",
    "tab_hover": "#303030",
    "toolbar_bg": "#1a1a1a",
    "header_bg": "#2a2a2a",
}

_LIGHT = {
    "window_bg": "#f4f4f4",
    "text": "#1f1f1f",
    "subtle": "#3a3a3a",
    "hint": "#6c6c6c",
    "border": "#c8c8c8",
    "base_bg": "#ffffff",
    "alt_bg": "#f3f3f3",
    "input_bg": "#ffffff",
    "btn_bg": "#fbfbfb",
    "btn_text": "#1f1f1f",
    "btn_hover": "#ececec",
    "btn_pressed": "#dcdcdc",
    "dis_bg": "#ececec",
    "dis_text": "#a6a6a6",
    "dis_border": "#d2d2d2",
    "console_bg": "#fbfbfb",
    "console_text": "#1f1f1f",
    "tab_bg": "#e6e6e6",
    "tab_hover": "#dcdcdc",
    "toolbar_bg": "#ebebeb",
    "header_bg": "#ededed",
}


def normalize_accent(accent: str) -> str:
    """Return a valid ``#rrggbb`` string, falling back to the default accent."""
    if not accent:
        return DEFAULT_ACCENT
    a = accent.strip()
    if not a.startswith("#"):
        a = "#" + a
    h = a[1:]
    if len(h) == 3:  # expand shorthand #abc -> #aabbcc
        h = "".join(c * 2 for c in h)
        a = "#" + h
    try:
        int(h, 16)
    except ValueError:
        return DEFAULT_ACCENT
    return a.lower() if len(h) == 6 else DEFAULT_ACCENT


def contrast_color(accent: str) -> str:
    """Black or white text colour for legibility on top of ``accent``."""
    h = normalize_accent(accent)[1:]
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#1e1e1e" if luminance > 0.55 else "#ffffff"


# QSS template. Uses $-style placeholders (string.Template) so the QSS's own
# { } braces need no escaping.
_QSS = Template(
    """
QWidget {
    font-size: 13px;
    background: $window_bg;
    color: $text;
}

QPushButton {
    padding: 4px 10px;
    border: 1px solid $accent;
    border-radius: 4px;
    background: $btn_bg;
    color: $btn_text;
}
QPushButton:hover { background: $btn_hover; }
QPushButton:pressed { background: $btn_pressed; }
QPushButton:disabled {
    background: $dis_bg;
    border-color: $dis_border;
    color: $dis_text;
}

QProgressBar {
    border: 1px solid $border;
    border-radius: 4px;
    text-align: center;
    background: $input_bg;
    color: $text;
}
QProgressBar::chunk { background: $accent; }

QPlainTextEdit {
    font-family: monospace;
    background: $console_bg;
    color: $console_text;
    border: 1px solid $border;
}

QComboBox, QLineEdit {
    background: $input_bg;
    color: $text;
    border: 1px solid $border;
    border-radius: 4px;
    padding: 3px 6px;
}
QComboBox:disabled, QLineEdit:disabled { color: $dis_text; border-color: $dis_border; }
QComboBox QAbstractItemView {
    background: $input_bg;
    color: $text;
    selection-background-color: $accent;
    selection-color: $on_accent;
}

QListWidget, QTableView, QTableWidget, QTreeView {
    background: $base_bg;
    color: $text;
    border: 1px solid $border;
    alternate-background-color: $alt_bg;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QHeaderView::section {
    background: $header_bg;
    color: $text;
    border: 1px solid $border;
    padding: 3px 6px;
}
QTableView QTableCornerButton::section { background: $header_bg; border: 1px solid $border; }

QCheckBox { color: $text; }

QTabWidget::pane { border: 1px solid $border; }
QTabBar::tab {
    background: $tab_bg;
    color: $subtle;
    border: 1px solid $border;
    padding: 5px 12px;
}
QTabBar::tab:hover { background: $tab_hover; }
QTabBar::tab:selected {
    background: $tab_bg;
    color: $accent;
    border-bottom: 2px solid $accent;
}

QGroupBox {
    border: 1px solid $border;
    border-radius: 4px;
    margin-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: $text;
}

QToolBar { background: $toolbar_bg; border-bottom: 1px solid $border; spacing: 4px; }
QLabel { color: $text; }

/* Destructive "Clear data" button: themed background (follows dark/light mode),
   but fixed red text+border independent of the user's accent colour. */
QPushButton#clearDataButton {
    background: $btn_bg;
    color: #e5484d;
    border: 1px solid #e5484d;
    border-radius: 4px;
    padding: 4px 10px;
}
QPushButton#clearDataButton:hover { background: $btn_hover; }
QPushButton#clearDataButton:pressed { background: $btn_pressed; }

QListWidget#settingsNav {
    background: $base_bg;
    border: 1px solid $border;
    border-radius: 4px;
    outline: 0;
    padding: 4px;
}
QListWidget#settingsNav::item {
    padding: 8px 10px;
    border-radius: 4px;
    color: $subtle;
}
QListWidget#settingsNav::item:hover { background: $tab_hover; }
QListWidget#settingsNav::item:selected {
    background: $accent;
    color: $on_accent;
    font-weight: bold;
}
QLabel#hint { color: $hint; }

/* Monitor selector dropdown beneath the plot */
QToolButton#monitorSelect {
    background: $btn_bg;
    color: $btn_text;
    border: 1px solid $accent;
    border-radius: 4px;
    padding: 3px 10px;
}
QToolButton#monitorSelect:hover { background: $btn_hover; }
QToolButton#monitorSelect:disabled {
    background: $dis_bg;
    border-color: $dis_border;
    color: $dis_text;
}

QMenu {
    background: $input_bg;
    color: $text;
    border: 1px solid $border;
}
QMenu::item { padding: 4px 22px 4px 10px; }
QMenu::item:selected { background: $accent; color: $on_accent; }
"""
)


def build_stylesheet(mode: str = DEFAULT_MODE, accent: str = DEFAULT_ACCENT) -> str:
    """Generate the full QSS for the given palette mode and accent colour."""
    palette = dict(_LIGHT if mode == "light" else _DARK)
    accent = normalize_accent(accent)
    palette["accent"] = accent
    palette["on_accent"] = contrast_color(accent)
    return _QSS.substitute(palette)


def apply_theme(app, mode: str = DEFAULT_MODE, accent: str = DEFAULT_ACCENT) -> None:
    """Apply the generated stylesheet to a running QApplication."""
    app.setStyleSheet(build_stylesheet(mode, accent))
