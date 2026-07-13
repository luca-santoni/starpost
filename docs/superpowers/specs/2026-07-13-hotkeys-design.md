# Hotkeys — design spec

Date: 2026-07-13
Status: approved

## Goal

Add keyboard shortcuts throughout StarPost and make them discoverable in the UI the way
STAR-CCM+ does: key names shown right-aligned in menus, and in tooltips that appear when
hovering tabs and buttons.

## Bindings

### Tab navigation — app-wide, always active

| Key | Action |
|-----|--------|
| `1` | Left panel → Files tab |
| `2` | Left panel → Data tab |
| `F1` | Centre → Reports tab |
| `F2` | Centre → Plots tab |
| `F3` | Centre → Scenes tab |
| `F4` | Centre → Screenplays tab |

Plain `1`/`2` are safe app-wide: Qt text-input widgets accept the ShortcutOverride event
for unmodified keys, so typing digits into line edits is never intercepted.

### Top bar — app-wide

| Key | Action |
|-----|--------|
| `Ctrl+Shift+B` | Open the Full Batch wizard (`MainWindow._run_batch`) |
| `Ctrl+Shift+E` | Open the Express batch dialog (`MainWindow._run_express_batch`) |

### Contextual — dispatch depends on the active centre tab

| Key | Action |
|-----|--------|
| `Ctrl+Shift+A` | Click "Select all" on the selection panel of the visible centre tab |
| `Ctrl+Shift+D` | Click "Clear" (untick all) on the selection panel of the visible centre tab |
| `Ctrl+R` | Scenes tab: Run (render stills). Screenplays tab: Record. Other tabs: no-op |
| `Alt+Shift+S` | Plots tab only: toggle the "Smooth data" checkbox. Other tabs: no-op |

`Ctrl+Shift+D` intentionally maps to the checklist "Clear" (deselect), **not** the
"Clear scenes"/"Clear screenplays" buttons that delete rendered artifacts — a two-key
chord must not destroy output.

### Files list — active only while the Files list has keyboard focus

| Key | Action |
|-----|--------|
| `Ctrl+L` | Load the selected file(s) — the existing Open action, renamed |
| `Ctrl+P` | Properties of the current item |
| `Delete` | Remove selected items, keeping the existing confirmation dialog |

The context menu is updated to match: "Open"/"Open All" is renamed **"Load file"** /
**"Load files"**, and a **"Remove"** entry is added so all three shortcuts have a visible
menu counterpart. Folder items keep their existing menu; Delete on a folder routes to the
existing folder-delete path with its confirmation.

## Architecture

### New module: `src/starpost/gui/shortcuts.py`

Single source of truth for every binding. Pure data + string helpers, no widget code:

- A table mapping a stable id (`"tab_files"`, `"tab_reports"`, `"batch_full"`,
  `"select_all"`, `"run_render"`, `"smooth"`, `"file_load"`, `"file_props"`,
  `"file_remove"`, …) to its key-sequence string and human label.
- `key(id) -> str` — the sequence string (feed to `QShortcut`/`QAction.setShortcut`).
- `hint(text, id) -> str` — tooltip text with the key appended, e.g.
  `"Switch to Reports (F1)"`.

Every place that displays or registers a key pulls from this table, so display text can
never drift from the actual binding.

### Wiring

- `MainWindow._init_shortcuts()` (new, called once from `__init__`): creates `QShortcut`
  objects with `Qt.WindowShortcut` context for the tab, batch, and contextual keys.
- Contextual slots check `self._center_tabs.currentWidget()` and dispatch to the existing
  button/checkbox via `.click()` / `.toggle()` so enabled/disabled state and confirmations
  behave exactly as a mouse click would.
- `FileListPanel` creates its three `QShortcut`s with `Qt.WidgetWithChildrenShortcut`
  context on the tree, targeting the same methods the context menu uses.

### Visibility

- **Tabs:** `setTabToolTip` on all six tabs with `hint()` text — shows after the standard
  hover delay ("hover for a moment").
- **Menus:** the Run batch menu entries and the Files context-menu entries become
  `QAction`s with `setShortcut(...)` set, so Qt renders the key right-aligned in the menu
  (STAR-CCM+ style). For the context menu this is display only; the always-active binding
  is the panel-level `QShortcut`. Context-menu actions must set
  `setShortcutVisibleInContextMenu(True)` (Qt hides them by default in context menus).
- **Buttons/checkbox:** Select all, Clear, Run, Record, and Smooth data get the key
  appended to their existing tooltips via `hint()`.

## Error handling

No new failure modes. Contextual shortcuts no-op when their tab is not active; clicking a
disabled button via `.click()` is a no-op; Delete/remove keeps its confirmation dialog.

## Testing

New `tests/test_shortcuts.py`, following the existing GUI-test pattern (shared offscreen
`QApplication`, autouse tmp-path config fixture; run via `scripts/run_tests.py`):

- Every id in the shortcuts table registers exactly once — no ambiguous-shortcut
  collisions among app-wide keys.
- `QTest.keyClick` on the main window switches tabs for `1`, `2`, `F1`–`F4`.
- Contextual dispatch: `Ctrl+R` on the Scenes tab emits `run_scenes_requested`; on the
  Screenplays tab emits `record_screenplays_requested`; on Reports does nothing.
  `Ctrl+Shift+A`/`Ctrl+Shift+D` tick/untick the visible checklist. `Alt+Shift+S` toggles
  the smooth checkbox only on the Plots tab.
- Files list: with focus on the tree, `Delete` opens the confirmation path (patch
  `QMessageBox`), `Ctrl+L` emits `open_requested`.
- Tooltip/menu text spot-checks: tab tooltips and menu action shortcut text come from the
  shortcuts table.

Also: `CHANGELOG.md` entry (newest-first style).

## Out of scope

- No consolidated "Keyboard shortcuts" help dialog.
- No user-configurable rebinding.
- No shortcuts inside modal dialogs (batch wizard, settings, export).
