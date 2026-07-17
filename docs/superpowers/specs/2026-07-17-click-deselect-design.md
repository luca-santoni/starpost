# Click-to-deselect — design

**Date:** 2026-07-17
**Status:** approved for implementation (autonomous session; decisions documented below)

## Problem

Clicking an item in any of StarPost's lists, trees, or tables paints it with the
accent selection highlight, and there is no easy way to remove that highlight
afterwards: clicking the item again is a no-op, so the highlight lingers on the
last-clicked row (Reports table, Files tree, galleries, dialog lists, …).
Several views already clear the highlight on an empty-space click
(`_DataTree`, `_FileTree`, the scene/screenplay galleries, batch dialog lists),
but clicking the highlighted item itself still does nothing, and views without
convenient empty space (a full Reports table) have no clear spot at all.

**Goal:** a plain left click on an already-selected item clears the selection
highlight — in every item view of the app.

## Approaches considered

1. **App-wide event filter** (chosen). One `QObject` filter installed on the
   `QApplication`, watching mouse press/release over any `QAbstractItemView`
   viewport — the same pattern as `install_combo_accent`. Covers every current
   and future view automatically; exclusions handled in one place.
2. Per-view helper (`enable_click_deselect(view)`) called at each construction
   site — explicit, but ~20 call sites today and every future view must
   remember to opt in; contrary to the "global" requirement.
3. Subclassing every view class — most invasive, no benefit over 1.

## Design

`_ClickDeselectFilter` in `gui/widgets.py`, installed once via
`install_click_deselect(app)` from `app.py` (next to `install_combo_accent`).

Trigger — all of:

- left button, no keyboard modifiers (Ctrl/Shift multi-select stays native);
- press landed on a valid index that was **already selected at press time**;
- release on the same index, moved less than `QApplication.startDragDistance()`
  (a drag is not a click);
- the item's check state did not change during the click (a click that toggled
  a checkbox — native indicator clicks, and the click-anywhere-toggles rows of
  the Data tab / export checklists — is a check action, not a deselect).

Action: clear the view's selection **and** current index
(`selectionModel().clear()`), so both the accent fill and the focus outline go.
The clear is deferred one event-loop turn (`QTimer.singleShot(0)`) so Qt's own
release handling (selection collapse, check toggles, click signals) finishes
first; the check-state guard is evaluated at that point. The filter never
consumes events, so dragging, double-click actions (file loading, gallery
opening), context menus, and editing are untouched.

Excluded views:

- popup windows (combo dropdowns, completers) — deselecting there breaks the
  control;
- `QFileDialog` internals (the non-native fallback dialog);
- `QHeaderView` (a `QAbstractItemView` subclass; header clicks sort);
- views with `selectionMode() == NoSelection` (checkbox-driven lists);
- views opted out via `exempt_click_deselect(view)` (a dynamic property) —
  applied to the settings dialog's nav list, whose selection drives which
  settings page is shown and must never be empty.

Multi-selection: a plain click on any selected row clears the whole selection
(one click kills the highlight, per the request). Ctrl+click still toggles
individual rows natively. Double-clicking a selected item briefly drops the
highlight after the first click; the double-click action itself is unaffected.

## Testing

Unit tests in `tests/test_widgets.py` drive synthetic clicks through the filter
on real widgets (list, tree, table): click-selected clears; click-unselected
selects; modifier clicks skipped; checkbox toggles skipped; drag-distance
moves skipped; exempted views and popup views skipped; multi-select cleared
wholesale. A settings-dialog test asserts the nav list is exempt.
