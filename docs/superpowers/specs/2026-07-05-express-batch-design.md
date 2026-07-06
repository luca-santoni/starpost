# Run-batch dropdown: Full Batch + Express batch

**Date:** 2026-07-05
**Status:** Approved

## Problem

The toolbar's **Run batch** button opens one dialog: the full five-tab wizard
(`BatchRunDialog` — Source, Reports, Plots, Scenes, Summary). Users who have
already saved a batch profile still walk the whole wizard to run it. We want a
faster path for them.

## Goal

Turn the single **Run batch** toolbar button into a hover dropdown with two
entries:

- **Full Batch** — opens the existing `BatchRunDialog`, unchanged.
- **Express batch** — opens a new, lean `ExpressBatchDialog` for users who
  already have a saved batch profile: pick a profile, pick sources, set export
  options, run. It provides the functionality of the full wizard's **Source** and
  **Summary** tabs only; the profile supplies the reports, plots, and scenes.

## Decisions

- **The dropdown opens on hover** (mouse-over the button), not click. Qt has no
  native hover popup mode, so a small `QToolButton` subclass overrides
  `enterEvent` to call `showMenu()`, guarded against re-triggering while the menu
  is already visible.
- **Express always opens**, regardless of whether any batch profiles exist. The
  batch-profile selector is front-and-centre; when none exist the selector is
  empty with a note pointing the user to Full Batch, and the run button is
  disabled until a profile is chosen.
- **The three report-output settings** — `report_format`, `include_units`,
  `combined_report` — currently live on the full wizard's Reports tab, which
  Express does not show. They are **added to the batch profile**, so a profile
  fully defines the report output. Full Batch saves them into the profile; Express
  reads them from the loaded profile.
- **Archive format and Include-dataset-CSV** remain per-run export choices,
  exposed on Express's own Export panel (mirroring the full Summary tab). They are
  NOT stored in the profile.
- **Shared code is extracted, not duplicated.** The Source tab's contents and the
  run-execution tail of `_run_batch` become reusable units used by both dialogs.

## Changes

### A. Toolbar dropdown — `src/starpost/gui/main_window.py`

- Add a small `HoverMenuToolButton(QToolButton)` whose `enterEvent` pops its
  `QMenu` when the pointer enters the button. A re-entrancy guard prevents
  re-popping the menu while it is already visible.
- Replace the single `self._run_action = tb.addAction("Run batch", self._run_batch)`
  with this tool button (label/icon "Run batch") added to the toolbar, carrying a
  `QMenu` with two actions:
  - **Full Batch** → `self._run_batch` (unchanged).
  - **Express batch** → new `self._run_express_batch`.
- The mid-run enable/disable currently applied to `self._run_action`
  (`main_window.py:494` disable, `:502` re-enable) moves to disabling/enabling the
  tool button, so neither menu entry opens while a numeric batch runs.
- `_run_express_batch` constructs `ExpressBatchDialog` with the same inputs Full
  gets that Express needs: `data_sets`, `results`, `settings`. (Express needs no
  `report_names` / `monitor_groups`.)

### B. Batch profile schema — `src/starpost/core/settings.py`

- Add three fields to `BatchProfile`:
  - `report_format: str = "CSV"`
  - `include_units: bool = True`
  - `combined_report: bool = True`
- `save()` writes the three new keys.
- `load()` reads them with `data.get(<key>, <default>)`, so existing profile files
  (which lack the keys) load unchanged with the defaults. No migration.

### C. Full dialog profile capture/apply — `src/starpost/gui/views/batch_run_dialog.py`

- `_build_profile` also captures the three settings from the existing widgets
  `_report_format` (`.currentText()`), `_report_include_units` (`.isChecked()`),
  `_report_combined` (`.isChecked()`).
- `_apply_profile` also restores them to those widgets when a profile is loaded.

### D. Extract two reusable units — `src/starpost/gui/views/batch_run_dialog.py`

1. **`SourcePanel(QWidget)`** — encapsulates the Source tab's widgets and helpers:
   the source-mode dropdown (`.sim files` / `Loaded data sets`), the Load Files /
   Load Data Set buttons, the checkable source list, Select All / Clear, and the
   source-resolution helpers. Public surface:
   - constructor takes `data_sets`, `results`, and `show_similar_format: bool`
   - `sources() -> list[BatchSource]` (the checked, resolved sources)
   - `has_checked() -> bool`
   - exposes the "Has similar format" checkbox only when `show_similar_format`
   The full dialog embeds a `SourcePanel(show_similar_format=True)` and keeps its
   existing "Has similar format" Continue-extraction flow, which reads the panel.
   Express embeds a `SourcePanel(show_similar_format=False)`.
2. **`execute_batch(parent, config, settings, runner, plot_render_cb) -> Path | None`**
   — the worker-thread + progress-dialog + result-messaging tail of the current
   `_run_batch` (everything after the `BatchConfig` is built and the output folder
   is chosen), lifted into a module-level function both dialogs call. Each dialog
   still gathers inputs, prompts for the output folder, builds the `BatchConfig`,
   and hands it to `execute_batch`.

### E. New Express dialog — `src/starpost/gui/views/express_batch_dialog.py` (new file)

A separate file because `batch_run_dialog.py` is already ~1900 lines.

`ExpressBatchDialog(QDialog)` layout, top to bottom:
- a prominent **Batch profile** selector (list of saved batch profiles);
- a `SourcePanel(show_similar_format=False)`;
- a compact **Export** panel: Archive format (ZIP / 7Z) + Include dataset .csv;
- a single **Batch run** button.

Behaviour:
- Opens regardless of profiles. When none exist, the selector is empty, a note
  directs the user to Full Batch, and the run button is disabled. The run button
  is enabled only when a profile is selected.
- On run:
  1. Load the selected `BatchProfile`.
  2. Resolve sources from the `SourcePanel` (`sources()`); guard "No data
     selected" if empty.
  3. Assemble `BatchConfig`:
     - `sources` from the panel
     - `reports = set(profile.selected_reports)`
     - `saved_plots = profile.saved_plots`, `saved_scenes = profile.saved_scenes`
     - `report_format = profile.report_format.lower()`,
       `include_units = profile.include_units`,
       `combined_report = profile.combined_report`
     - `archive_format` and `include_dataset_csv` from the Export panel
  4. Guard "Nothing to output" when the profile yields no reports/plots/scenes and
     dataset CSV is off (mirrors the full dialog's check).
  5. Guard "Set the STAR-CCM+ executable path in Settings first" when the run needs
     the exe (any source needs extraction, or saved scenes must render), same
     condition as the full dialog.
  6. Prompt for the output folder, build the dated destination filename with the
     chosen archive extension, and call `execute_batch` with a plot-render
     callback (saved plots render on the GUI thread, as in the full dialog).

### F. Error handling

Reuse the full dialog's guard messages via the shared `execute_batch` and the
Express run method: "No data selected", "Nothing to output — …", and "Set the
STAR-CCM+ executable path in Settings first". Express adds one guard: the run
button stays disabled until a batch profile is selected (so "run with no profile"
cannot happen).

## Testing

- **Settings:** `BatchProfile` round-trips `report_format` / `include_units` /
  `combined_report`; a profile file written without those keys loads with the
  defaults (`"CSV"`, `True`, `True`).
- **Full dialog:** `_build_profile` captures the three new settings and
  `_apply_profile` restores them (extend the existing profile test).
- **SourcePanel:** `sources()` resolves checked `.sim` file sources and checked
  data-set sources (carrying each data set's already-extracted result).
- **ExpressBatchDialog:**
  - constructs without error;
  - the run button is disabled when no profile is selected;
  - with a profile selected and a data-set source checked, the run assembles a
    `BatchConfig` carrying the profile's reports/plots/scenes and its
    `report_format` / `include_units` / `combined_report`, plus the Export panel's
    `archive_format` / `include_dataset_csv` — verified by monkeypatching
    `execute_batch` to capture the config instead of running it.
- **main_window:** the Run-batch tool button exposes a menu with exactly
  **Full Batch** and **Express batch**; triggering each opens the corresponding
  dialog (patch the dialog classes to assert construction).

## Out of scope

- Any change to the full wizard's Reports/Plots/Scenes tabs beyond the profile
  capture/apply of the three settings.
- Storing source selection, archive format, or dataset-CSV in the batch profile.
- Changes to the extraction pipeline, `BatchConfig`, or `build_batch_archive`.

## Documentation

- README: note the Run-batch button's Full Batch / Express batch dropdown and what
  Express does (run a saved batch profile quickly).
- `CHANGELOG.md`: a user-facing entry.
