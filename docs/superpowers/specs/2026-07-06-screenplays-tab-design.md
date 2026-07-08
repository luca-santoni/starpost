# Screenplays tab — design

**Date:** 2026-07-06
**Status:** Implemented (v2.3.0) and verified against Simcenter STAR-CCM+ 2506.

## Verification findings (2026-07-07)

Manual verification against a real STAR-CCM+ 2506 install refined the record
macro beyond the original reflective design. Recorded here so the next round of
work (on higher-spec hardware) starts from what we learned:

- **Recorder API (introspected from `screenplay.jar` / `starbase.jar`).** The
  working call is `star.common.AnimationDirectorBase.record(int, int, double,
  double, double, String, int[, boolean, boolean])` on the screenplay's
  animation director, after arming it (`markRecordingScene`,
  `setFramesPerSecond`, `prepareForExport`). The three doubles are **Frame Rate,
  Start Time, Animation Length** (read off the GUI export dialog); the trailing
  int is **movie type**: `0` = Movie File, `1` = Directory of PNG Frames. Only
  `movieType 0` is used. Length comes from `getPreferredAnimationLength()`.
- **Two working paths, RAM decides which runs.** `recordKnown` (native
  `record(movieType=0)`) is tried first; `recordFrameLoop`
  (`initializeForMovieExport` → `beginMovieExport` → per-frame `updateAnimation`
  + `exportMovieFrame` → `endMovieExport`/`finalizeMovieExport`) is the fallback.
  - On the **16 GB laptop**, the native call did not deliver the movie in our
    verify window and the **frame loop** produced it (slowly — RAM-bound).
  - On a **higher-spec machine** (2026-07-08), the **native `record()` path
    succeeded and was fast — ~2:15** for the ~11 s / 330-frame test case. It is
    confirmed the *native* path because `recordKnown` returns before the frame
    loop is ever reached, so **no per-frame progress markers were emitted**.
  So native recording works on adequate hardware; the frame loop remains the
  fallback. A GUI macro of a manual **Movie File** export would still pin the
  exact preferred native call for other releases.
- **No progress bar on the native path (open).** STAR *does* track frame
  progress during native `record()` — the GUI shows `Writing Animation File:
  Writing Frame N` / `NN%` — but it pushes those updates to its graphical
  **`star.base.neo.ProgressPresenter`** (`setMessage`/`setValue`/`setMaximum`,
  in `starbase.jar`), which has no GUI in `-batch` mode. Our per-frame
  `starpost-progress:` markers live only in `recordFrameLoop`, which the native
  path skips, so the StarPost progress bar never moves during a fast native
  render. Deciding question for the next session: **does that
  `Writing Frame N` / percentage text reach the `starccm+` stdout in batch?**
  - **If yes** → trivial: teach `ScreenplayRecordWorker._sink` to recognise the
    line (or the `NN%`) and emit `frame_progress`, exactly like the frame-loop
    markers — a real per-frame bar on the fast native path.
  - **If no** (GUI-only) → options are (a) an indeterminate "Recording movie…"
    **busy indicator** during the native call (honest, always doable); (b) force
    the frame-loop path for its markers (but that likely gives up the native
    path's speed); or (c) inject a custom `ProgressPresenter` — the
    `record(int,int,…)` overloads take no presenter, while the
    `record(SimulationProcessObject, …)` overloads (currently marked
    `[unfillable]`) do route through a process object, so wiring a presenter we
    can read is *possible in principle* but unverified and fragile.
- **A `File.canWrite()` quirk** aborts STAR's hardcopy path for a not-yet-
  existing target ("File … is not writable, hardcopy aborted"); the macro
  pre-creates an empty target and cleans up empty stubs.
- **`movieType 1` was a trap:** it renders every frame to PNGs in a directory,
  which `verifyOutput` then rejects as a non-file — a full wasted render. It is
  no longer attempted.
- **Performance is RAM-bound, not macro-bound.** Batch recording loads the whole
  mesh per session; a case that exceeds available RAM swaps to disk (the
  multi-tens-of-minutes `Loading/configuring connectivity` stall). A
  ~21M-cell case wants ~30–40 GB; verification hit this wall on a 16 GB /
  i5-12500H laptop. Levers: adequate RAM (the real fix), batch multiple
  recordings per checkout to pay the load once, and re-save at the local
  partition count to skip re-partition compute. `-np` does **not** add memory on
  a single machine. See `docs/StarPost_Documentation.md` §3.6b for the
  user-facing version.

Open items for the next session (higher-spec hardware, for faster iteration):

1. **Progress bar on the native path** — first check whether STAR's
   `Writing Frame N` / `NN%` progress text appears in the `starccm+` stdout
   during a batch record (look at the StarPost log console mid-record). If it
   does, parse it in `ScreenplayRecordWorker._sink` → `frame_progress`. If not,
   add an indeterminate "Recording movie…" busy indicator during the record
   call. (See the "No progress bar on the native path" finding above.)
2. **Confirm the native call is the preferred one** across releases — a GUI
   macro recording of a manual **Movie File** export pins the exact signature;
   consider dropping the pre-created stub for the movie-file path and/or polling
   for async completion so `recordKnown` wins even on the first, cold attempt.
3. **Optional speed:** pipeline the frame-loop fallback via
   `exportMovieFrameAsync` to overlap render and encode (only relevant when the
   native path can't be used).

## Summary

Add a new **Screenplays** centre tab to StarPost, modeled on the existing Scenes
tab. Screenplays are STAR-CCM+ animations; "running" one records it to a **movie
file**. The tab lets the user pick which screenplays to record (with per-field
displayer control) and which **saved camera views** to record each from — saved
views being a critical control for recording screenplays correctly. Discovery of
screenplays happens in the *same single extraction pass* as scenes; recording is a
separate, on-demand pass, exactly as scene rendering is today.

The implementation mirrors the Scenes subsystem at each layer (Approach A —
parallel mirror), reusing shared helpers (thumbnail decode/cache, saved-view
application, filename sanitisation, media-index handling) without modifying the
working scenes code.

## Decisions (from brainstorming)

- **Output:** a single movie file per recording (not an image sequence). MP4/H.264
  is the default container/codec.
- **Saved views:** one movie per *screenplay × checked view*. Applying each checked
  saved view to the screenplay's scene before recording; no view checked = the
  screenplay's own/current camera. Mirrors the Scenes tab exactly.
- **Picker shape:** a **tree** with displayer children, exactly like the Scenes
  tree — each screenplay expands to its scene's scalar/vector displayers, and
  unchecked ones are hidden before recording.
- **STAR-CCM+ target:** modern first-class Screenplays (Simcenter STAR-CCM+
  2022+/2306+).
- **Macro API access — reflection, turnkey:** the record macro never references
  the screenplay API at compile time (a Java compile error is fatal to the whole
  macro and cannot be try/caught). The screenplay manager is obtained via
  `Class.forName` + `Simulation.get`, and the record call is found by scanning the
  screenplay object's public record/export methods, filling arguments by type.
  An API mismatch on some release degrades to a logged `ERROR` media row, never a
  dead macro. This supersedes the user-pasted-snippet approach in the older
  `docs/screenplay_plan.md` (Phase 3): no Settings paste box, ships working with
  no user setup.
- **Movie settings exposed:** format (MP4/AVI/MOV), frame rate (fps), resolution
  (width × height), and quality/bitrate.
- **Gallery preview:** the record macro also exports one **poster frame** (PNG) per
  movie; the gallery shows the poster with a play badge, and double-click opens the
  movie in the system video player.

## Central invariant (unchanged)

STAR-CCM+ runs once per file for extraction; everything after is cached.
Screenplays are **discovered** in that single extraction pass (no extra checkout to
browse them). **Recording** is the on-demand exception, a separate pass — exactly
like scene rendering.

## Section 1 — Data model & discovery

### Model (`data/models.py`)
- New `Screenplay` dataclass, parallel to `Scene`:
  - `name: str`
  - `scene: str` — the scene the screenplay animates (owning scene)
  - `displayers: list[Displayer]` — the scalar/vector displayers of that scene
- `SimResult.screenplays: list[Screenplay]` (default empty) plus a
  `screenplay_names()` helper, mirroring `scenes` / `scene_names()`.
- `MediaArtifact`:
  - Use `kind="movie"` for recorded screenplays. (The model comment currently
    reserves the token `"video"` "for later"; this design settles on `"movie"` and
    updates that comment — one token, used consistently everywhere.)
  - `path` points at the movie file.
  - New field `poster: str = ""` — absolute path to the poster PNG.
  - Reuse existing provenance fields (`source`, `view`, `displayers`, `sim_path`).

### Discovery (`macros/extract_all.java.j2` + `core/result_parser.py`)
- Extend the existing extraction macro with an `exportScreenplays()` step writing
  `<simname>__screenplays_index.csv` with columns `screenplay,scene,displayer,kind`
  — the same shape as `__scenes_index.csv` plus the owning `scene` column. A
  screenplay whose scene has no scalar/vector displayers still emits one row (empty
  displayer/kind) so it appears in the tree.
- Screenplays are enumerated from the sim's screenplay manager; each resolves to its
  associated scene, whose scalar/vector displayers are listed by reusing the scene
  displayer logic.
- `result_parser.py` gains `_parse_screenplays()` reading that CSV into `Screenplay`
  objects, called alongside the existing scenes/views parsing.
- Saved views are already discovered (`SimResult.views`) and reused unchanged.

### Cache persistence (`data/store.py`)
- `_result_to_dict` builds its payload with explicit keys (not plain `asdict`), so
  it gains a `"screenplays": [asdict(sp) for sp in r.screenplays]` entry, and
  `_result_from_dict` reads it back via `d.get("screenplays", [])` — older caches
  without the key load with an empty list. `MediaArtifact(**m)` already tolerates
  the new `poster` field (it defaults when absent from old caches).

## Section 2 — Recording macro, runner & worker

### Macro (`macros/record_screenplays.java.j2`, public class `record_screenplays`)
Sibling to `render_scenes.java.j2`. Jinja params:
- `screenplay_show` — map of screenplay → displayers to keep visible
- `view_names_java` — saved views to record from (empty = current camera)
- movie settings: `width`, `height`, `fps`, `format`/extension, `quality`
- `output_dir`

For each checked screenplay × each view:
1. Resolve the screenplay's scene; apply displayer visibility (reuse the scenes
   macro's `applyVisibility` — hide unchecked scalar/vector displayers via opacity
   0; other displayer types untouched).
2. Apply the saved view to the scene's current view (reuse `applyView` and the
   reflective `presentationName` helper so we don't bind to a release-specific view
   class).
3. Record the screenplay to a movie in `output_dir` at the configured
   resolution/fps/format/quality, invoking the recorder **reflectively** (see the
   Decisions section): candidate `record`/`export…` methods on the screenplay are
   scanned and the first whose parameters can be filled (String → output path,
   ints → width/height/fps, float/double → quality factor) is invoked. If none
   fits, the failure is logged with the candidate signatures so the log shows
   what the installed release offers.
4. Export one **poster frame** (PNG) for that movie — first frame, via
   `scene.printAndWait` after the view/visibility are set.
5. Write a media-index row: `kind=movie`, `source=<screenplay>`,
   `name=<screenplay>[-<displayers>][-<view>]`, `file=<movie>`, plus `poster`,
   `displayers`, `view`, `error` columns.

Discipline copied from `render_scenes`: best-effort per screenplay (log + `ERROR`
row on failure, never abort the whole run); close the scene after each recording to
release graphics resources; reuse `sanitizeFile`/`esc`/index-writing scaffolding.
The reflective lookup is exercised against a real 2022+ install as a manual
verification step (automated tests cover the template rendering only).

### Runner (`core/starccm_runner.py` + `core/macro_generator.py`)
- New `record_screenplays(sim_file, output_dir, screenplay_show, views)` alongside
  `render_scenes`, rendering the new macro via a new
  `record_screenplays_macro(...)` in `macro_generator.py` and shelling out
  `starccm+ -batch … file.sim`.
- Returns `list[MediaArtifact]` (kind `movie`, with `poster`) parsed from the media
  index. The media-index parser learns the `poster` column and the `movie` kind.
- Invoked through the same `StarRunner`, so existing credential safeguards (license
  redaction, 0600 perms, POD-key masking) apply automatically — nothing weakened.

### Worker (`batch/queue.py`)
- New `ScreenplayRecordWorker(QObject)` cloned from `SceneRenderWorker`: runs
  sequentially, one license checkout at a time. Signals:
  `log(str)`, `progress(int, int)`, `recorded(sim_path, artifacts)`, `finished()`.
- Jobs chunk screenplays by a `screenplays_per_checkout` setting, mirroring
  `scenes_per_checkout`.

## Section 3 — Settings & GUI

### Settings (`core/settings.py`, `config/default_settings.yaml`, Settings dialog)
Extend `MediaConfig` with:
- `movie_format` — `mp4` | `avi` | `mov` (default `mp4`)
- `movie_fps` — int (default 30)
- `movie_resolution` — reuse the `IMAGE_RESOLUTIONS` map (`1080p` | `2160p`)
- `movie_quality` — enum `low` | `medium` | `high` (default `high`); the macro maps
  the enum to the recorder's encoder quality/bitrate knob
- `screenplays_per_checkout` — int ≥ 1 (default 1)

Add `to_dict`/`from_dict` round-tripping (clamp malformed values) and a
`SettingsDialog` "Screenplays" group mirroring the scene-media controls.

### Selection panel (`gui/views/selection_panel.py`)
- New `_ScreenplayTree`, a near-copy of `_SceneTree`: checkable screenplays →
  checkable displayer children; checking a screenplay reveals its displayers
  unchecked; `checked_screenplays()` / `checked_displayers()` accessors.
- Reuse the existing `self.views` `Saved views` checklist. `set_active_section`
  learns a `"screenplays"` mode that shows the Screenplays tree **and** the Saved
  views list, split identically to scenes.
- A `_screenplays_group_box` with its own **Record** button
  (`record_screenplays_requested` signal) and **Clear screenplays** button
  (`clear_screenplays_requested`, styled `dangerButton`), mirroring the scenes
  group.
- Profiles: unchanged. Profiles do not persist scene selection today, so
  screenplay selection is likewise not persisted — an exact mirror of the Scenes
  tab. (Persisting both is a possible follow-up, out of scope here.)

### Gallery (`gui/views/screenplay_view.py`)
- New `ScreenplayView`, modeled on `SceneView`: a thumbnail gallery driven by
  `MediaArtifact` where `kind == "movie"`. Thumbnails the artifact's **poster**
  path (reuse `SceneView`'s decode-at-thumbnail-size cache logic, factored into a
  shared helper) and overlays a **play badge**.
- Double-click opens the **movie** (`art.path`) in the system player via
  `QDesktopServices`. Right-click → Properties (reuse/extend
  `ScenePropertiesDialog` to show fps/format/view).
- Hint text: "Select screenplays and press Record to create movies."

### Main window (`gui/main_window.py`)
- Add a **"Screenplays"** centre tab after "Scenes" holding `ScreenplayView`.
  `_on_center_tab_changed` maps it to the `"screenplays"` selection section and
  builds the gallery on show (deferred while hidden, like scenes).
- `_record_screenplays()` mirrors `_run_scenes()`: guard busy/exe, require exactly
  one ticked data set, intersect checked screenplays with the result's available
  ones, build `screenplay_show`, chunk by `screenplays_per_checkout`, gather checked
  views, pick output dir, start a `ScreenplayRecordWorker` on a `QThread`.
- `_on_screenplays_recorded` / `_on_record_finished` attach artifacts to the result
  and persist (`save_cache_async`), replacing prior movies of the same sources —
  same pattern as scenes.
- Reuse the one-time "recording is expensive" warning (recording is heavier than
  still rendering — the warning text gets a screenplay-aware variant).

## Section 4 — Error handling & edge cases

- **No screenplays in the .sim:** tree shows empty; Record with nothing checked
  pops an informational message ("Select at least one screenplay to record.").
- **Screenplay with no scene / no displayers:** still listed (empty-displayer row);
  recording proceeds with no visibility overrides. If the recorder API can't
  resolve a scene for a screenplay, that screenplay logs an `ERROR` media row and
  the run continues.
- **Recording/codec failure** (headless, no GPU, missing encoder): best-effort per
  screenplay — logged, `ERROR` row written, tile shows "(record failed)" like the
  scene "(render failed)" path. A failed movie whose poster exported still shows the
  poster; a movie present but poster missing falls back to a play-badge-only tile.
- **Movie/poster file missing on disk** at gallery build: tile shows "(file
  missing)", mirroring `SceneView`.
- **Concurrency:** `_record_busy()` guards against overlap with the numeric batch,
  scene render, and other screenplay runs (one license at a time). Clear-screenplays
  is blocked while recording.
- **Stale reuse:** re-recording the same screenplay × view overwrites the same file
  paths; `_on_record_finished` clears the gallery path cache to force a rebuild (as
  scenes does).
- **Credential safety:** unchanged — the new macro is invoked through the same
  `StarRunner`; existing redaction / 0600 / masking safeguards apply.

## Testing

Offscreen and serialized per the repo's GUI-pytest rule
(`QT_QPA_PLATFORM=offscreen`, one test at a time under a timeout).

- `result_parser`: parsing `__screenplays_index.csv` into `Screenplay` objects
  (empty-displayer and multi-displayer rows); media-index parsing of `movie` rows
  with a `poster` column.
- `macro_generator`: `record_screenplays_macro` renders valid Java with correct
  show-map, view-names, and movie-setting substitutions (string tests, no
  STAR-CCM+).
- `settings`: `MediaConfig` round-trips the new movie fields; sane defaults;
  malformed values clamped.
- `selection_panel`: `_ScreenplayTree` check/reveal/accessor behaviour;
  `"screenplays"` section visibility toggling; profile persistence of screenplay
  selection.
- `ScreenplayView`: `show_media` filters to `kind == "movie"`, builds poster
  thumbnails, handles error/missing tiles.
- STAR-CCM+ execution itself is out of scope for automated tests (as with scene
  rendering) — verified manually against a real 2022+ install.

## Docs & housekeeping

- Bump `__version__` (minor).
- Add a `CHANGELOG.md` entry (newest first) and a reference-docs section for the
  Screenplays tab.
- Commit after each logical change per the repo convention.

## Out of scope (YAGNI)

- Image-sequence output (movie file only).
- Including recorded movies in the "Run batch" `.zip` export (`batch/run.py`) —
  movies live in the gallery/output folder only for now; bundling them is a
  follow-up if wanted.
- Editing/authoring screenplays inside StarPost (they are authored in STAR-CCM+;
  StarPost only records existing ones).
- In-app video playback (open in the system player).
- Generalising scenes + screenplays into a shared kind-parameterised abstraction
  (Approach B) — not worth the blast radius for two consumers.
