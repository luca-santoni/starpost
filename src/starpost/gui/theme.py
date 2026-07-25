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

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF

from starpost.utils.paths import cache_dir

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

# Base UI font size (px) at a text scale of 1.0 — the original program-wide size.
# The Appearance "Text size" multiplier scales this; everything that inherits the
# QWidget font (buttons, labels, checkboxes, combos, tabs, menus, …) grows with it.
BASE_FONT_PX = 13


_DARK = {
    "window_bg": "#1e1e1e",
    "text": "#e6e6e6",
    "subtle": "#cfcfcf",
    "hint": "#9a9a9a",
    "border": "#333333",
    "check_border": "#777777",  # lighter than border so checkboxes read on dark bg
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
    "check_border": "#9a9a9a",  # a touch darker than border for contrast on light bg
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


def palette(mode: str) -> dict[str, str]:
    """The raw colour table for ``mode`` ("light", else dark) — for code that
    draws its own theme-matched pixmaps (e.g. the dropdown menu glyphs)."""
    return dict(_LIGHT if mode == "light" else _DARK)


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
    font-size: ${font_px}px;
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

/* Slim underline-style progress bar (bottom log panel): flat, no border, the
   accent fills left-to-right like a growing underline. */
QProgressBar#progressUnderline {
    border: none;
    border-radius: 0;
    background: $input_bg;
}
QProgressBar#progressUnderline::chunk { background: $accent; }

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
    /* No focus rectangle: otherwise the current row keeps a faint outline after
       its selection is cleared (e.g. clicking empty space in the Files tab). */
    outline: 0;
}
QHeaderView::section {
    background: $header_bg;
    color: $text;
    border: 1px solid $border;
    padding: 3px 6px;
}
QTableView QTableCornerButton::section { background: $header_bg; border: 1px solid $border; }

QCheckBox { color: $text; }
/* Disabled checkboxes (e.g. "Separate files" with <2 data sets) read clearly
   greyed: faded label, faded box, matching the disabled buttons/combos. */
QCheckBox:disabled { color: $dis_text; }

/* Checkmarks (checkboxes + checkable list items). The checked glyph is a
   generated SVG tinted with the user's checkmark colour. */
QCheckBox::indicator,
QListView::indicator,
QTreeView::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid $check_border;
    border-radius: 3px;
    background: $input_bg;
}
QCheckBox::indicator:disabled {
    border-color: $dis_border;
    background: $dis_bg;
}
QCheckBox::indicator:checked,
QListView::indicator:checked,
QTreeView::indicator:checked {
    image: url("$check_icon");
}
/* Checked menu items (e.g. the sort menus) use the same tinted glyph,
   without a box. */
QMenu::indicator { width: 14px; height: 14px; }
QMenu::indicator:checked { image: url("$check_icon"); }
/* On the highlighted item (accent background) use the contrast-colour glyph so
   the checkmark stays visible instead of blending into the accent. */
QMenu::indicator:checked:selected { image: url("$check_icon_selected"); }

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

/* Frameless-window caption pieces living in the top bar: the version label and
   the integrated window buttons on the right. Labels are transparent so they
   show the bar's colour (the global QWidget background would otherwise paint
   them window_bg and leave seams). The caption-button glyph/hover colours are
   Qt properties so they follow the theme (close goes red on hover). */
QToolBar#mainToolBar QLabel { background: transparent; }
/* Muted, theme-neutral gray (mid-gray at low alpha reads faint on dark and
   light alike), as the version wordmark was in earlier versions. */
QLabel#titleVersion { color: rgba(127, 127, 127, 0.55); }
CaptionButton {
    background: transparent;
    qproperty-glyphColor: $subtle;
    qproperty-hoverGlyph: $text;
    qproperty-hoverBg: $btn_hover;
}
CaptionButton#winClose {
    qproperty-hoverGlyph: #ffffff;
    qproperty-hoverBg: #c42b1c;
}

/* Main menu-style toolbar: the StarPost badge followed by flat menu items,
   modelled on a classic application menu bar (STAR-CCM+'s). Generous vertical
   padding for the roomy row height, a subtle hover fill, no blue chrome — it
   keeps the dark/light theme background. */
QToolBar#mainToolBar {
    background: $toolbar_bg;
    border-bottom: 1px solid $border;
    spacing: 2px;
    /* No right padding so the window buttons sit flush to the corner. */
    padding: 3px 0 3px 4px;
}
QToolBar#mainToolBar QToolButton {
    background: transparent;
    color: $text;
    border: none;
    border-radius: 0;
    padding: 13px 6px;
    margin: 0;
}
QToolBar#mainToolBar QToolButton:hover { background: $btn_hover; }
QToolBar#mainToolBar QToolButton:pressed { background: $btn_pressed; }
/* The File / Run batch menu buttons render sunken (":pressed") the whole time
   their dropdown is open — a persistent "this menu is open" state, not a
   momentary click. Keep the hover fill instead of the dark pressed fill so the
   open button stays clearly highlighted (the dark $btn_pressed all but vanishes
   against the toolbar). The objectName selector outranks the generic :pressed
   rule above, so it wins whether or not the pointer is still over the button. */
QToolBar#mainToolBar QToolButton#fileMenuButton:pressed,
QToolBar#mainToolBar QToolButton#runBatchButton:pressed { background: $btn_hover; }
QLabel#toolbarLogo { background: transparent; }

/* Destructive buttons (profile "Delete", "Clear rendered"): themed background
   (follows dark/light mode), but fixed red text+border independent of the
   user's accent colour. */
QPushButton#dangerButton {
    background: $btn_bg;
    color: #e5484d;
    border: 1px solid #e5484d;
    border-radius: 4px;
    padding: 4px 10px;
}
QPushButton#dangerButton:hover { background: $btn_hover; }
QPushButton#dangerButton:pressed { background: $btn_pressed; }

/* Destructive context-menu entry (the Files/Data tab menus' "Clear"): a label
   in a QWidgetAction, red like the danger buttons. Hover inverts it — red
   fill, white text (the close caption button's convention) — this entry's
   version of the accent highlight the ordinary items get. Left padding lines
   its text up with the checkable sort entries above it (item padding +
   indicator). */
QLabel#dangerMenuItem {
    background: transparent;
    color: #e5484d;
    padding: 4px 22px 4px 21px;
}
QLabel#dangerMenuItem:hover {
    background: #e5484d;
    color: #ffffff;
}

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
/* Toolbar "New update available" note: tinted with the user's accent so it
   stands out, and follows accent changes live (the QSS is re-applied). */
QLabel#updateAvailable { color: $accent; }

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
/* QMenu's own `color` above would otherwise paint disabled entries (e.g. the
   Tools dropdown's "coming soon" placeholders) in the normal text colour. */
QMenu::item:disabled { color: $dis_text; }
QMenu::item:disabled:selected { background: transparent; color: $dis_text; }
"""
)


def _checkmark_icon(color: str) -> str:
    """Render (once per colour) a checkmark PNG tinted ``color`` and return its
    path for use in QSS ``url(...)``. A PNG (not SVG) so it works without the Qt
    SVG image plugin; the colour is encoded in the filename so a colour change
    yields a new URL (sidestepping Qt's stylesheet image cache).

    Rendered at 2x and downscaled by the indicator size for crisp edges.
    """
    color = normalize_accent(color)
    path = cache_dir() / f"checkmark_{color.lstrip('#')}.png"
    if not path.exists():
        scale = 2
        pm = QPixmap(14 * scale, 14 * scale)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidth(2 * scale)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(
            QPolygonF([QPointF(3 * scale, 7.5 * scale),
                       QPointF(6 * scale, 10.5 * scale),
                       QPointF(11 * scale, 4 * scale)])
        )
        painter.end()
        pm.save(str(path), "PNG")
    return path.as_posix()


def build_stylesheet(
    mode: str = DEFAULT_MODE,
    accent: str = DEFAULT_ACCENT,
    checkmark_color: str | None = None,
    text_scale: float = 1.0,
) -> str:
    """Generate the full QSS for the given palette mode and colours. When
    ``checkmark_color`` is None the accent colour is used for checkmarks.
    ``text_scale`` multiplies the base UI font size (1.0 = the original size)."""
    palette = dict(_LIGHT if mode == "light" else _DARK)
    accent = normalize_accent(accent)
    palette["accent"] = accent
    palette["on_accent"] = contrast_color(accent)
    palette["check_icon"] = _checkmark_icon(checkmark_color or accent)
    # A second glyph in the accent's contrast colour for the highlighted menu
    # item, whose background is the accent — the normal (accent-tinted) checkmark
    # would otherwise be invisible against it.
    palette["check_icon_selected"] = _checkmark_icon(palette["on_accent"])
    palette["font_px"] = max(1, round(BASE_FONT_PX * float(text_scale)))
    return _QSS.substitute(palette)


def apply_theme(
    app,
    mode: str = DEFAULT_MODE,
    accent: str = DEFAULT_ACCENT,
    checkmark_color: str | None = None,
    text_scale: float = 1.0,
) -> None:
    """Apply the generated stylesheet to a running QApplication, and keep the
    dropdown hover-outline colour in sync with the accent."""
    from starpost.gui.widgets import set_combo_accent_color

    app.setStyleSheet(build_stylesheet(mode, accent, checkmark_color, text_scale))
    set_combo_accent_color(normalize_accent(accent))
