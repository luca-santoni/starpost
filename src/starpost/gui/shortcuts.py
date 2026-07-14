"""Single source of truth for keyboard shortcuts.

Every binding lives in ``SHORTCUTS``; widgets look keys up with :func:`key`
(to register a QShortcut / QAction shortcut) and :func:`hint` (to append the
key to tooltip text). Nothing here imports Qt — the table is plain data so it
adds nothing to startup.

Scopes (enforced where the keys are registered, not here):
- the ``file_*`` ids are active only while the Files list has focus;
- ``select_all`` / ``clear_selection`` / ``run_render`` / ``smooth`` act on the
  active centre tab (the selection panel tracks it);
- everything else is app-wide.
"""

SHORTCUTS: dict[str, tuple[str, str]] = {
    # id: (key sequence, human label)
    "tab_files": ("1", "Switch to Files"),
    "tab_data": ("2", "Switch to Data"),
    "tab_reports": ("F1", "Switch to Reports"),
    "tab_plots": ("F2", "Switch to Plots"),
    "tab_scenes": ("F3", "Switch to Scenes"),
    "tab_screenplays": ("F4", "Switch to Screenplays"),
    "batch_full": ("Ctrl+Shift+B", "Open the Full Batch wizard"),
    "batch_express": ("Ctrl+Shift+E", "Open the Express batch dialog"),
    "add_files": ("Ctrl+N", "Add .sim files to the Files list"),
    "add_folder": ("Ctrl+Shift+N", "Add a folder of .sim files to the Files list"),
    "import_data": ("Alt+Shift+I", "Import a portable data CSV"),
    "export_data": ("Alt+Shift+E", "Export the selected data set to a portable CSV"),
    "select_all": ("Ctrl+Shift+A", "Select all entries in the current checklist"),
    "clear_selection": ("Ctrl+Shift+D", "Deselect the current checklist"),
    "run_render": ("Ctrl+R", "Run / Record on the Scenes / Screenplays tab"),
    "smooth": ("Alt+Shift+S", "Toggle Smooth data on the Plots tab"),
    "file_load": ("Ctrl+L", "Load the selected file(s)"),
    "file_props": ("Ctrl+P", "Properties of the selected item"),
    "file_remove": ("Delete", "Remove the selected files/folders"),
}


def key(shortcut_id: str) -> str:
    """The key-sequence string for a shortcut id (raises KeyError if unknown)."""
    return SHORTCUTS[shortcut_id][0]


def hint(text: str, shortcut_id: str) -> str:
    """Tooltip text with the shortcut appended, e.g. ``"Switch to Reports (F1)"``."""
    return f"{text} ({key(shortcut_id)})"


# Qt anchors a menu's shortcut column straight after its widest label, which
# reads cramped; trailing spaces on the label widen that gap.
_MENU_GAP = " " * 6


def menu_label(text: str) -> str:
    """A menu-entry label padded so its shortcut sits further to the right."""
    return text + _MENU_GAP
