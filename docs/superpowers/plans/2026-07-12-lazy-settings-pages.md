# Lazy Settings-Dialog Pages — Deferred Optimization Plan

> **For agentic workers:** This is a self-contained, ready-to-run plan. Steps use
> checkbox (`- [ ]`) syntax for tracking. It is *deferred* (not yet implemented)
> because its payoff is now small — see **Payoff & whether to bother** first and
> confirm it is still worth doing.

**Goal:** Make the Settings dialog build its ~12 pages lazily (each on first
navigation) instead of all up front in `__init__`, cutting the **first**-open
cost of the dialog.

**Owning code:** `src/starpost/gui/views/settings_dialog.py` (the `SettingsDialog`
class) and `src/starpost/gui/main_window.py` (`_open_settings`).

---

## Background & measurements

Opening Settings constructs a `SettingsDialog`, whose `__init__` builds **all 12
pages eagerly** (`_add_page(...)` calls at the top of `__init__`). Measured
offscreen on this repo (relative costs hold on real hardware):

- `SettingsDialog()` construction: **~143 ms**. No single hotspot — page builds
  sum to ~40 ms (biggest: Screenplays 7, Appearance 7, Export 6.6), the rest
  (~100 ms) is the dialog/scroll-area/stack shell + Qt styling all those widgets.

Two related optimizations are **already implemented** (do not redo them):

- **#1 — Cancel skips the restyle** (`reject()` only re-applies the theme when a
  live preview actually changed it). Commit: "Settings: skip the theme restyle on
  Cancel when appearance unchanged".
- **#4 — dialog reuse** (built once, cached on `MainWindow._settings_dialog`,
  re-synced via `SettingsDialog.reload()` on each reopen). Commit: "Settings:
  build the dialog once and reuse it". This already makes **every open after the
  first ~5 ms**.

So this plan (#3) only improves the **first** open of a session (~143 ms → ~20 ms).

## Payoff & whether to bother

| Path | Now (with #1+#4) | With #3 added |
|---|---|---|
| Open, 1st of session | ~143 ms | **~20 ms** (shell + first page) |
| Open, 2nd+ | ~5 ms (reuse) | ~5 ms (unchanged) |
| Navigate to an unvisited page | ~0 ms | +one page build (~1–7 ms), once |

- **Time saved:** ~120 ms, **once per session**, on the first Settings open.
- **Complexity:** Medium–High (splitting per-page load/save; interaction with the
  #4 reuse path).
- **Risk:** Medium–High — the hazard is a setting silently not saved because its
  control wasn't built. The mitigations below make it safe but must be followed.

Given #4 already exists, confirm with the user that shaving the one-time first
open is worth this refactor before starting.

## Global constraints (from the repo)

- Ruff: line-length 100, py311. Run `ruff check .` before each commit.
- GUI tests offscreen, one file at a time, not piped through tail:
  `QT_QPA_PLATFORM=offscreen timeout 120 .venv/bin/python -m pytest tests/<file>.py -v`
- Tests touching config/cache use the `isolated_paths` autouse fixture pattern.
- Commit after each task; user-facing changes go in `CHANGELOG.md` (newest first).
- Brand **StarPost**; lowercase `starpost` only for identifiers.

---

## The core design problem

Today the flow assumes **every control exists**:
- `__init__` builds all pages (creating every control: `self._exe`, `self._decimals`, …).
- `_load_from_settings()` populates **all** controls from settings.
- `_on_accept()` reads **all** controls back into settings.
- `reload()` (reuse) re-runs `_load_from_settings()` + rebuilds the profile lists.

If a page is not built, its controls don't exist, so `_load_from_settings()` and
`_on_accept()` would `AttributeError`.

**Key insight that makes laziness safe:** *if a page was never built, the user
never saw or changed its controls, so its settings must remain exactly as they
were.* Therefore load/save must be **page-scoped** and only run for **built**
pages. Unbuilt page ⇒ its settings are left untouched on Save. Correct by
construction.

---

### Task 1: Split load/save into per-page functions

**Files:** Modify `src/starpost/gui/views/settings_dialog.py`.

- [ ] For each page `X` in {starccm, license, appearance, files, reports, plots,
  scenes, screenplays, export, profiles, misc, about}, add:
  - `_load_<X>_page()` — populate that page's controls from `self._settings`
    (carve the relevant lines out of the current `_load_from_settings()`).
  - `_save_<X>_page()` — write that page's controls into `self._settings`
    (carve the relevant lines out of the current `_on_accept()`).
  - Pages with no editable controls (About) get no-op or no functions.
- [ ] Keep `_load_from_settings()` as a thin wrapper that calls every
  `_load_<X>_page()` **for built pages only** (used by `reload()`), and keep the
  appearance revert-snapshot in `_capture_original_appearance()` as-is (it reads
  `self._settings`, not controls, so it needs no page).
- [ ] Verify: existing tests still pass (behaviour unchanged so far — all pages
  are still built eagerly at this point).

### Task 2: Lazy page construction + built-set tracking

**Files:** Modify `src/starpost/gui/views/settings_dialog.py`.

- [ ] Replace eager `_add_page(name, self._build_X_page())` calls with a registry
  of `(name, build_fn, load_fn, save_fn)` and add a **placeholder** widget per
  page to the `QStackedWidget` (so nav indices line up).
- [ ] Track built pages in `self._built: dict[int, PageRecord]` (or a set of
  indices).
- [ ] On `self._nav.currentRowChanged` (and initially for row 0), if the page
  isn't built: call its `build_fn`, swap the placeholder for the real page in the
  stack, call its `load_fn` (with `self._loading = True` around it so no live
  preview fires), and mark it built.
- [ ] `_on_accept()`: iterate **built** pages and call each `save_fn`; then
  `self._settings.save()`. Unbuilt pages are intentionally skipped.
- [ ] `reload()` (reuse path): reset to first page and either (a) clear the
  built-set + restore placeholders so pages rebuild lazily again, or (b) re-`load`
  only the already-built pages. Option (b) is simpler and keeps reopen cheap;
  pick it unless memory matters. Re-run `_capture_original_appearance()` and
  rebuild the profile lists as today.

### Task 3: Handle the special pages

**Files:** `src/starpost/gui/views/settings_dialog.py`.

- [ ] **Appearance:** its live preview (`_apply_preview`) and Cancel revert only
  matter once the user opens the page. If never built, `_orig_*` still come from
  settings via `_capture_original_appearance()`, and `reject()`'s `theme_changed`
  comparison uses `self._accent` / `self._effective_checkmark()` — ensure those
  fall back to the settings-derived values when the page was never built (they
  already do, because `_capture_original_appearance()` seeds `self._accent`,
  `self._checkmark_color`, `self._text_scale`, etc.). **Add a test.**
- [ ] **Profiles:** `_rebuild_profiles_list()` / `_rebuild_batch_profiles_list()`
  must run when the Profiles page is built (and on `reload`). Deleting a profile
  already re-runs them.
- [ ] **License:** `_sync_license_mode()` must run when the License page is built
  (it enables/disables fields by mode).

### Task 4: Tests

**Files:** `tests/test_text_scale.py` (or a new `tests/test_settings_lazy.py`).

- [ ] **Save without visiting a page leaves its setting untouched:** load a
  dialog, change nothing, `_on_accept()`, assert an unvisited page's setting
  equals its pre-existing value (not a control default).
- [ ] **Visiting then editing a page saves it:** navigate to Reports, change
  decimals, `_on_accept()`, assert `settings.report_decimals` updated and
  persisted (`Settings.load()`).
- [ ] **Cancel with Appearance never built skips the restyle** (extends the
  existing `test_dialog_cancel_without_appearance_change_skips_restyle`).
- [ ] **Reuse still works** (`test_dialog_reload_resyncs_for_reuse` must still
  pass; add one that reloads after visiting a subset of pages).
- [ ] Keep the existing `test_dialog_cancel_reverts_live_preview` and
  `test_dialog_change_and_save_persists_text_scale` green.

### Task 5: Verify the payoff + changelog

- [ ] Micro-benchmark first-open construction before/after (expect ~143 ms → ~20 ms).
  Reuse `bench_settings.py`-style timing (construct dialog, time it).
- [ ] `CHANGELOG.md` under `### Improvements` (newest first): note that the
  Settings dialog now builds pages on demand, making the first open faster.

---

## Risks & mitigations

- **A setting silently not saved** because its control wasn't built → the
  page-scoped `save_fn` + "only built pages" rule *is* the fix, but it is easy to
  get subtly wrong. Mitigation: Task 4's "save without visiting leaves it
  untouched" and "visit + edit saves it" tests for at least Reports, Plots,
  STAR-CCM+, and Media/Scenes fields.
- **Appearance revert breaking** when the page was never built → covered by the
  Appearance test in Task 3; `_capture_original_appearance()` must remain
  control-free (settings-only).
- **Nav index drift** between `QListWidget` rows and stack indices → keep
  placeholders so indices always line up; never `insert`/`remove` pages.
- **Interaction with #4 reuse** → decide the `reload()` strategy (Task 2, option
  b recommended) and test a reopen after visiting a subset of pages.

## Rollback

Single-file-ish change; revert the settings_dialog.py refactor (and the small
`_open_settings` touch if any) to return to eager construction. #1 and #4 are
independent and stay.
