# Screenplays in the Run-batch export — design

Date: 2026-07-08
Status: approved, ready for implementation plan

## Goal

Extend the **Run batch** export (the toolbar wizard, `batch/run.py` +
`gui/views/batch_run_dialog.py`) so a batch run can record screenplay **movies**
per data set, alongside the reports, saved plots and saved scenes it already
produces. This brings the Screenplays feature (shipped v2.3.0 as its own centre
tab) into the batch pipeline.

## Context

The Run-batch wizard already has a **Scenes** tab that captures "Saved Scenes"
(scene → displayers, saved views, image resolution/format) and, in
`build_batch_archive`, renders each saved scene per source via
`runner.render_scenes`. Screenplays are almost perfectly parallel:

- `_ScreenplayTree` already exists in `gui/views/selection_panel.py` (subclass of
  `_SceneTree`); `checked_displayers()` returns exactly the
  `{screenplay: [displayer, …]}` map that `record_screenplays` needs as its
  `screenplay_show` argument.
- `StarRunner.record_screenplays(sim_file, output_dir, screenplay_show,
  view_names, log_sink)` already shells out to STAR-CCM+ off the GUI thread and
  returns the recorded `MediaArtifact`s. **No GUI-thread hand-off is needed**
  (unlike saved plots, which build a `PlotView`).
- Screenplay entries need the `.sim` file, so they are gated on
  `source.sim_file is not None`, exactly like scenes.

Two design decisions were made during brainstorming:

1. **Placement:** a new dedicated **Screenplays** tab in the wizard (mirrors the
   main window's separate Screenplays tab and Settings page), not folded into the
   Scenes tab.
2. **Movie options:** captured **per saved-screenplay entry** in the wizard
   (resolution / format / fps / quality), mirroring how the Scenes tab captures
   per-entry resolution+format — not taken from global settings.

## Data model

A saved screenplay entry (the shape stored in the wizard list item's data, in the
`BatchConfig`/`BatchProfile`, and passed to `build_batch_archive`):

```python
{
    "name": str,                    # user-supplied entry name
    "data": {
        "displayers": {sp: [disp, …]},   # screenplay_show map (checked)
        "views": [str, …],               # checked saved camera views
        "resolution": "1080p" | "2160p",
        "format": "mp4" | "avi" | "mov",
        "fps": int,
        "quality": "low" | "medium" | "high",
    },
}
```

These enumerations match `MediaConfig.movie_resolution / movie_format /
movie_fps / movie_quality` in `core/settings.py`.

## Components / changes

### 1. `batch/run.py`

- `BatchConfig`: add `saved_screenplays: list[dict] = field(default_factory=list)`.
- New helper `_screenplay_runner(settings, entry_data, base) -> StarRunner`:
  mirrors `_scene_runner`, but replaces the media config's
  `movie_resolution / movie_format / movie_fps / movie_quality` with the entry's
  captured options (falling back to `base` when settings is None). Returns a
  `StarRunner` whose `record_screenplays` records at those settings.
- `_source_steps`: add `len(config.saved_screenplays)` to the count **only when
  `source.sim_file is not None`** (same gate as scenes).
- `build_batch_archive` main loop: after the scenes block, add a screenplays
  block:

  ```python
  if source.sim_file is not None:
      for entry in config.saved_screenplays:
          name = entry.get("name", "screenplay")
          steps.at(f"Recording screenplay “{name}” for {source.name}…")
          sdata = entry.get("data") or {}
          show = sdata.get("displayers") or {}
          if show:
              try:
                  _screenplay_runner(settings, sdata, runner).record_screenplays(
                      source.sim_file, folder, show,
                      sdata.get("views") or [], log_sink=log,
                  )
              except Exception as e:  # noqa: BLE001
                  log(f"  screenplay “{name}” failed: {e}")
          steps.advance()
  ```

  The recorded movie(s) + poster frame(s) + the media-index CSV land in that
  source's folder and get packed into the archive by the existing `_pack_dir`.

  **Deviation from the scenes block, deliberate:** the record call is wrapped in
  try/except-log-continue. Screenplay recording is RAM-heavy and the most
  failure-prone step in the pipeline; one screenplay failing (or STAR exiting
  non-zero) must not abort the whole archive. `record_screenplays` raises
  `StarRunError` on a non-zero exit, so without the wrapper a single bad case
  loses every other source's output too.

### 2. `core/settings.py` — `BatchProfile`

- Add `saved_screenplays: list[dict] = field(default_factory=list)` to the
  dataclass.
- `save()`: write `"saved_screenplays": list(self.saved_screenplays)`.
- `load()`: read `saved_screenplays=list(data.get("saved_screenplays", []))`
  (older profiles without the key load as an empty list — backward compatible).

### 3. `gui/views/batch_run_dialog.py`

- `_TAB_NAMES = ["Source", "Reports", "Plots", "Scenes", "Screenplays",
  "Summary"]`; add `self._tabs.addTab(self._screenplays_tab, "Screenplays")`
  before the Summary tab.
- `_build_screenplays_tab()` — mirrors `_build_scenes_tab()`:
  - **Options** column: resolution (`1080p`/`2160p`), format (`MP4`/`AVI`/`MOV`),
    fps (spin box), quality (`Low`/`Medium`/`High`) — seeded from
    `settings.media`.
  - A `_ScreenplayTree` (imported from `selection_panel`) filled from a
    screenplay-groups union across the source results (new
    `_screenplay_groups_union`, analogous to `_scene_groups_union`, built from
    `result.screenplays` → `{sp.name: [d.name for d in sp.displayers]}`).
  - Its own **Saved Views** checklist (`_CheckableList`), fed from the same saved
    views the Scenes tab uses.
  - A **Saved Screenplays** list with right-click Properties/Delete.
- `_capture_screenplay()`: returns the entry `data` dict above (displayers +
  views + the four options).
- `_on_save_screenplay()`: name prompt → add item (mirrors `_on_save_scene`).
- `_on_saved_screenplay_menu()` / summary menu: Properties + Delete
  (delete-in-place removes from the source list too, like plots/scenes).
- `_SavedScreenplayPropertiesDialog`: read-only view of the entry — the movie
  options, the saved views, and the screenplays with their kept-visible
  displayers (mirrors `_SavedScenePropertiesDialog`, plus the movie options).
- **Summary** tab: add a Screenplays column (`self._summary_screenplays`),
  mirrored from the saved list in `_refresh_summary` and cleaned up on delete.
- `to_config` / config building: add
  `saved_screenplays=self._saved_entries(self._saved_screenplays)`; include
  screenplays in the "nothing selected" validation and in the `needs_exe`
  (STAR-CCM+ path required) check — both like scenes.
- Profile save/restore: include `saved_screenplays`
  (`self._restore_saved(self._saved_screenplays, profile.saved_screenplays)`).

### 4. `gui/views/express_batch_dialog.py`

- Pull `saved_screenplays = list(profile.saved_screenplays)`, pass it into
  `BatchConfig`, and include it in the empty-profile ("nothing to output") and
  `needs_exe` checks (screenplays, like scenes, need the `.sim` + STAR path).

### 5. Docs

- `CHANGELOG.md`: newest-first entry noting screenplay recording in Run batch.
- `docs/StarPost_Documentation.md`: extend the Run-batch section with the
  Screenplays tab.

## Testing

- `build_batch_archive` screenplay path with a **fake `StarRunner`** whose
  `record_screenplays` records the arguments and writes a stub movie file into the
  target folder: assert it's called once per saved screenplay with the right
  show-map, views, and media override (resolution/format/fps/quality), that the
  file lands in the source's folder, and that a raised `StarRunError` from one
  screenplay is logged and does **not** abort the run (other outputs still
  present).
- `_source_steps`: the count includes `len(saved_screenplays)` when `sim_file` is
  set and excludes it when it isn't.
- `BatchProfile` round-trip (`save` → `load`) preserves `saved_screenplays`, and a
  profile file lacking the key loads as `[]`.

## Out of scope (YAGNI)

- No combined/root-level movie aggregation — movies are inherently per-sim.
- No new movie formats or encoder settings beyond the existing `MediaConfig`
  enumerations.
- No changes to the recording macro (`macros/record_screenplays.java.j2`) or the
  `record_screenplays` runner method — they are reused unchanged.
