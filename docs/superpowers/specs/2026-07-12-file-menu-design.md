# Design: "File" menu in the top bar

**Date:** 2026-07-12
**Status:** Approved (pending user review of this document)

## Summary

Add a `File` hover-dropdown to the main window's top bar, giving toolbar-level
access to three existing operations: adding `.sim` files/folders (Files tab)
and importing/exporting portable data CSVs (Data tab). No new behavior — the
menu is a second entry point to code paths that already exist.

## Menu structure and placement

```
⭐ StarPost | File ▾ | Run batch ▾ | Export… | Settings…        v2.4.0  ─ □ ✕
             │
             ├ Add            ▸  Files…    → FileListPanel.add_files_dialog()
             │                   Folder…   → FileListPanel.add_folder_dialog()
             ├ Import data…      → MainWindow._import_data
             └ Export data…      → MainWindow._export_data
```

- `File` is the **first** item after the StarPost logo, before "Run batch"
  (standard File-menu-first convention).
- Built with the existing `HoverMenuToolButton` + `HoverMenu` pair (the "Run
  batch" pattern, `main_window.py:_build_toolbar`): opens on hover, closes when
  the pointer strays, hands off to neighbouring bar items via `sibling_bar`.
- "Add" is a plain `QMenu` submenu created with `addMenu("Add")`; Qt opens and
  closes submenus on hover natively.
- Menu labels end in `…` (they all open dialogs), matching the neighbouring
  "Export…" / "Settings…" actions. Native OS dialogs only — a single combined
  file+folder dialog was considered and rejected (native dialogs can't mix
  modes; the non-native Qt dialog workaround was declined).

## Wiring (decided: call existing slots directly)

- `FileListPanel._add_files` / `_add_folder` become public
  `add_files_dialog()` / `add_folder_dialog()`. The Files-tab buttons rewire to
  the new names — one code path, two entry points. Dialogs, folder-grouping,
  duplicate-skipping, and "no .sim files" messages are unchanged.
- "Import data…" / "Export data…" connect to the existing
  `MainWindow._import_data` / `_export_data` slots — identical to the Data
  tab's buttons (which connect via `import_requested` / `export_requested`).
- All existing tab buttons stay. A shared-`QAction` refactor was considered
  and rejected as unnecessary churn (it inverts the current panel-owns-its-
  buttons structure for the same end behavior).

## HoverMenu submenu fix (the one real code change)

`HoverMenu.mouseMoveEvent` (`gui/widgets.py`) closes the menu once the pointer
moves more than `CLOSE_MARGIN` (50 px) outside the menu or its owner button.
An open submenu is a separate popup window that can extend past that margin,
so moving deep into "Add ▸" would close the whole menu.

Fix: before closing, also treat any **visible child submenu** as safe — loop
over `self.actions()`, and for each `action.menu()` that `isVisible()`, keep
the menu open while the pointer is within that submenu's `frameGeometry()`
plus the same margin (~5 lines).

## Enabled states and edge cases

- All menu items are always enabled, mirroring the tabs today (the export
  dialog itself handles the "nothing loaded" case).
- No changes to extraction, batch, settings, or data-model code.

## Testing

Run via `scripts/run_tests.py` (GUI tests need `QT_QPA_PLATFORM=offscreen` on
headless machines). New coverage:

1. Toolbar structure: the File button exists, first after the logo, with an
   "Add" submenu (Files…/Folder…) plus "Import data…" and "Export data…".
2. Action wiring: triggering each of the four actions calls the right slot
   (monkeypatched).
3. `HoverMenu` safe region: a pointer position over a visible child submenu
   (beyond the 50 px margin of the parent) does not close the menu; a position
   outside both still does.
4. Existing `FileListPanel` tests updated for the renamed public methods.

## Changelog

One entry in `CHANGELOG.md` under a new Unreleased section, existing style.
