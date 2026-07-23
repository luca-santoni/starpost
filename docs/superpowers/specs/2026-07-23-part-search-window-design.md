# Part Search window — design

## Goal

Wire up the currently inert **Tools → Part Search** menu entry so it opens a
separate window for finding, across all loaded data sets, which sims contain a
given part. Typing part-name text into a search bar filters a list of data sets
down to only those containing a matching part, revealing which parts matched.

## Context (what already exists)

- **Menu entry** — "Part Search" exists in the Tools dropdown but is UI-only,
  no slot wired (`src/starpost/gui/main_window.py:547`).
- **Part data is already extracted and cached** per sim. `build_parts_tree(
  result.properties)` (`src/starpost/data/parts_tree.py`) returns a nested
  `PartsTree` of `PartNode`s (each with `.name`), already used by the Properties
  dialog's Parts tab. No STAR-CCM+ re-run is needed — this feature reads cached
  data only, consistent with the central "STAR runs once, everything after is
  cached" invariant.
- **Loaded data sets** come from `self.store.all()`; each `SimResult` has
  `.sim_name` and `.error` (non-`None` = failed extraction).
- **Separate windows** follow the `QDialog` pattern (e.g. `PropertiesDialog` in
  `src/starpost/gui/views/properties_dialog.py`), opened from a wired menu action.

## Design

### New component: `PartSearchDialog`

New file `src/starpost/gui/views/part_search_dialog.py`.

- **Window**: non-modal `QDialog` opened with `.show()` (not `.exec()`),
  parented to the main window, so it stays open while the user works in the main
  app. The main window keeps a reference (`self._part_search_dialog`) so the
  window isn't garbage-collected; re-triggering "Part Search" raises and
  refreshes the existing window rather than spawning a duplicate.
- **Layout**: a `QLineEdit` search bar at the top (placeholder
  *"Search part names…"*, focused on open), a `QTreeWidget` filling the rest,
  and a small header/count label.
- **Tree contents**:
  - Top level = each loaded data set (`sim_name`) that contains at least one
    matching part.
  - Children = the matched part names within that sim.
  - **Empty query** → all data sets shown collapsed, each expandable to its full
    part list.
  - **Non-empty query** → only sims with matches, auto-expanded, showing just
    the matched parts.
  - Count label reports results, e.g. *"3 data sets, 12 parts"*.
- **Matching**: case-insensitive substring against **every** node name in the
  parts tree — both composite/group names and leaf parts. Live, on every
  keystroke (`QLineEdit.textChanged`).
- **Interaction**: double-clicking either a data-set row or a part row opens
  that sim's existing `PropertiesDialog` (which defaults to showing the Parts
  tab context), reusing the pattern from `_show_data_properties`.
- **Data source**: `self.store.all()` filtered to `r.error is None`;
  `build_parts_tree(r.properties)` per sim. Sims extracted before the parts
  feature have empty trees and simply never match — no special-casing.

### Pure logic added to `parts_tree.py` (Qt-free, headless-testable)

Kept out of the Qt view so it is unit-testable without a `QApplication`, per the
repo convention.

- `iter_part_names(tree: PartsTree) -> list[str]` — flatten every node name
  (composites and leaves) in tree order.
- `matching_parts(tree: PartsTree, query: str) -> list[str]` — case-insensitive
  substring filter over `iter_part_names`; an empty/whitespace-only query returns
  all names.

### Wiring (`main_window.py`)

- Add `_open_part_search()` that creates (or raises) `PartSearchDialog`.
- Connect it to the existing "Part Search" action at
  `src/starpost/gui/main_window.py:547`.

## Testing

- **Unit** (`tests/test_parts_tree.py`): the flatten + match helpers —
  empty-query returns all, case-insensitivity, matching both composite and leaf
  names, and a sim with no part data (empty tree) yielding nothing.
- **GUI smoke** (headless, via the `verify` skill): open the dialog against a
  store with known parts, type text, assert the tree filters to the expected
  sims/parts, and that double-clicking a row opens the Properties window.

## Out of scope (YAGNI)

- Searching sim names, report names, or plot names — parts only.
- Ticking/selecting the matched sim in the main file list (double-click opens
  Properties instead).
- Any re-extraction or STAR-CCM+ invocation.

## Changelog / docs

- Add a `CHANGELOG.md` entry (newest first) for the new Part Search window.
- No new keyboard shortcut, so `shortcuts.py` / `docs/starpost_hotkeys.txt` are
  untouched.
