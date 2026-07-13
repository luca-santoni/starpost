# Design: click-to-open top-bar menus with hover-switching

**Date:** 2026-07-12
**Status:** Approved (pending user review of this document)

## Summary

Change the top-bar dropdowns (`File`, `Run batch`) from hover-open/auto-close to
standard menu-bar semantics:

- A menu opens **only on click** (no hover-open).
- Once open, it **stays open regardless of pointer position**.
- With a menu open, **hovering a different menu button in the bar switches** to
  that button's menu without another click.
- A menu closes **only** on a click anywhere else in the program (native QMenu
  outside-click dismissal; Esc and re-clicking the button also close it, as any
  menu does).

Approach chosen: rework the existing custom classes in
`src/starpost/gui/widgets.py`. A native `QMenuBar` replacement was considered
and rejected (QSS restyling + frameless drag-handle churn for the same result).

## Changes

### `src/starpost/gui/widgets.py`

- **`HoverMenuToolButton` → `BarMenuButton`.** Delete the `enterEvent`
  hover-open override entirely — the buttons' existing
  `InstantPopup` popup mode already opens the menu on click natively. The
  class keeps the stuck-hover-outline fix (see below).
- **`HoverMenu` → `BarMenu`.** Delete all auto-close logic from
  `mouseMoveEvent`: the `CLOSE_MARGIN` stray-close, the sibling-bar instant
  close, and the visible-submenu safe region (dead once nothing auto-closes).
  Replace with one behavior — **hover-switch**: while open, the menu holds the
  mouse grab and receives all mouse moves; when the pointer is inside a
  *different* `BarMenuButton` that has a menu and lives on `sibling_bar`, the
  menu closes itself and opens that button's menu via
  `QTimer.singleShot(0, other.showMenu)` (deferred because `showMenu` blocks;
  the close must unwind first). Pointer anywhere else — including non-dropdown
  bar items like Export…/Settings…, the bar's empty area, or far outside the
  window — does nothing.
- **Stuck-hover fix relocates.** The existing `_clear_stuck_hover` (button
  keeps its auto-raise hover outline after the menu closes, because the menu's
  grab swallowed the leave event) currently runs after the hover-open call.
  It must now run on every close path: trigger it from the menu's
  `hideEvent` override, targeting the owner button.
- Docstrings rewritten to describe the new semantics; the `owner` /
  `sibling_bar` constructor parameters keep their roles (owner = the button,
  sibling_bar = the toolbar searched for other menu buttons).

### `src/starpost/gui/main_window.py`

- Rename call sites only (`HoverMenu` → `BarMenu`, `HoverMenuToolButton` →
  `BarMenuButton`, import line included). Construction, order, labels,
  tooltips, and wiring are unchanged.

### Tests (`tests/test_widgets.py`, `tests/test_main_window.py`)

- Six tests describe deleted behavior and are removed:
  `test_hover_menu_closes_when_pointer_strays_far`,
  `test_hover_menu_stays_open_within_margin`,
  `test_hover_menu_closes_when_moving_onto_sibling_bar`,
  `test_hover_menu_sibling_bar_does_not_close_over_owner`,
  `test_hover_menu_stays_open_over_visible_submenu`,
  `test_hover_menu_closes_when_submenu_hidden`.
- New tests (same synthetic-mouse-move style, reusing `_move_to`):
  1. Menu stays open when the pointer moves far outside it.
  2. Menu stays open when the pointer moves onto the sibling bar's empty
     area / a non-menu item.
  3. Pointer over a different menu button on the sibling bar → this menu
     closes and the other button's menu opens (after the deferred singleShot
     runs — process events, or assert via a monkeypatched `showMenu`).
  4. Hover does not open a closed menu (deliver an enter event to the button;
     its menu must remain hidden).
- `tests/test_main_window.py`: `test_hover_menu_tool_button_respects_disabled_state`
  is deleted (it tests the removed `enterEvent` hover-open; its underlying
  concern — a disabled button must not open its menu mid-batch — is covered
  more strongly by a new widgets test that the hover-switch handoff skips
  disabled buttons). `test_hover_menu_tool_button_clears_leftover_hover`
  survives (the helper it tests remains); it and the structure/wiring tests
  only need class-name updates.
- New widgets test 5: the hover-switch handoff skips a disabled menu button
  (the open menu stays; the disabled button's menu is not opened).
- New widgets test 6: hiding the menu clears the owner button's stuck hover
  outline (the relocated `_clear_stuck_hover` trigger).

## Known consequences (accepted)

- An open menu abandoned by the mouse stays on screen until a click or Esc —
  inherent to the requested behavior, same as any OS menu bar.
- Clicking a non-dropdown bar action (e.g. Export…) while a menu is open
  spends that click on dismissing the menu (native popup behavior); a second
  click activates the action.
- While the File menu's "Add ▸" submenu is the active popup, Qt routes the
  grabbed mouse moves to it, so the hover-switch handoff pauses until the
  pointer re-crosses the parent menu (closing the submenu); a straight move
  to the other menu button then needs a click.

## Changelog

One entry in `CHANGELOG.md` under `[Unreleased]` (Improvements), existing
style, describing the new click-to-open behavior for both menus.
