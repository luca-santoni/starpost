# StarPost — Scene Rendering & Screenplays: Action Plan

> Status: **Phase 1 (scene stills) in progress** — backend + Scenes tab built;
> Settings UI, user docs, and version bump still pending (see §9). Branch:
> `screenplay`.
> **Current focus: Phase 1 — Scene stills.** Saved views (Phase 2) and
> screenplays (Phase 3) are deferred; build the media pipeline on the stable,
> ships-turnkey stills case first (see §4).
> Companion reference macro: [`RunScreenplays.java`](../RunScreenplays.java) (in the repo root; the
> structural basis for the new render macro).

This document lays out how to expand StarPost from **reports + monitor plots** to
also producing **rendered media** from STAR-CCM+ scenes: still images (including
from saved camera views) and screenplay animations (video / image sequences).

---

## 1. Goal

Today StarPost extracts **numeric data only** (report values + monitor plots).
This feature adds **visual output**:

- **Scene stills** — render a scene to a PNG.
- **Saved-view stills** — render a scene from a stored camera view.
- **Screenplays** — run/export a named screenplay to a video (or image sequence).

---

## 2. Current architecture (what we're building on)

StarPost is an **orchestrator + viewer**, not a `.sim` parser. The whole program
is built around one flow: *extract numeric data → parse to CSV → load into a
dataclass model → cache → view / compare / export.*

```
file_list → BatchWorker → StarRunner.extract()
                              │
                              ├─ macro_generator.render_macro()  → extract_all.java  (ONE template)
                              ├─ starccm+ -batch ... file.sim     (one license checkout, sequential)
                              ├─ macro dumps CSVs to output_dir
                              └─ result_parser.parse_sim_output() → SimResult(reports[], plots[])
                                     │
                              ResultStore (in-memory + JSON crash cache)
                                     │
                  ReportTable · PlotView · SelectionPanel · ExportDialog
```

Key files:
- Model: `src/starpost/data/models.py` (`Report`, `PlotSeries`, `MonitorPlot`, `SimResult`)
- Macro: `src/starpost/macros/extract_all.java.j2`, rendered by `src/starpost/core/macro_generator.py`
- Runner: `src/starpost/core/starccm_runner.py` (`StarRunner.extract`)
- Parser: `src/starpost/core/result_parser.py`
- Store / portable: `src/starpost/data/store.py`, `src/starpost/data/portable.py`
- Batch: `src/starpost/batch/queue.py` (`BatchWorker`), `src/starpost/batch/job.py`
- Settings: `src/starpost/core/settings.py`, `config/default_settings.yaml`
- GUI: `src/starpost/gui/main_window.py` + `src/starpost/gui/views/*`

---

## 3. The fundamental tension: media is not re-parseable data

The existing pipeline assumes output is **re-parseable numeric data**. Rendered
media is not. Three hard constraints follow and shape every decision below:

1. **The artifact *is* the output.** No values to tabulate, no comparison math.
   Media files live on disk; the JSON cache can store only *paths + metadata*,
   not the bytes (unlike numeric data, which is embedded in the cache).
2. **Screenplay export is version-specific and cannot be shipped.** Per
   `RunScreenplays.java`, the Screenplay record/export API class names shift
   across releases, so the user must paste in a recorded snippet
   (`exportScreenplayByName`). **Scene stills are different** —
   `scene.printAndWait()` is stable and *can* be fully shipped.
3. **Rendering needs a GPU/display.** Headless/batch runs can silently produce
   all-black frames. The current "reports are just numbers" path never had this
   risk.

The current docs explicitly scope this *out* (`StarPost_Documentation.md`
§4 Limitations "numeric data only", §12 Design Decisions). This is a deliberate
scope **expansion**, and those docs must be updated.

---

## 4. Recommended phasing (de-risk in order)

The three outputs form a **subset → superset** ladder. Each phase reuses the
previous one's infrastructure and de-risks the next. **Build them in this order.**

### Phase 1 — Scene stills (ships fully working, no user setup) ← **CURRENT FOCUS**
`scene.printAndWait(file, magnification, width, height)` is stable across
versions. StarPost can enumerate scenes (`sim.getSceneManager().getObjects()`)
and render every (or selected) scene with **zero** user configuration. This phase
builds the **entire media pipeline** (model, render macro, manifest, parser,
cache, media view, settings, render trigger) on the easiest, most reliable case —
and proves headless rendering actually works before any heavy renders.

### Phase 2 — Saved-view stills (small increment on Phase 1) — *deferred*
A saved view is a stored camera position (`sim.getViewManager().getObjects()`),
applied to a scene's current view before `printAndWait()`. This is a **thin
addition** to the Phase 1 still path:
- Same render macro, same manifest, same parser/model/view — just "apply view X,
  then print" inside the scene loop, producing one still per (scene, view).
- Stable API, no paste-in, so it ships working like Phase 1.
- The **view-discovery + selection UI** built here is directly reused by
  screenplays (a screenplay is essentially a tour across views over time).

> **Why before screenplays:** it's the natural building block, uses stable API,
> ships without the version-specific paste-in, and validates the GPU/black-frame
> path on cheap stills before investing in long, fragile screenplay renders. The
> file itself recommends "export a still first to confirm rendering."

### Phase 3 — Screenplays (the hard tier: version-specific + GPU-heavy) — *deferred*
Run/export named screenplays to video. StarPost provides the scaffolding
(discovery, file naming, per-item error isolation, logging) and **injects the
user's recorded `exportScreenplayByName` snippet**. This is the only piece that
cannot be shipped turnkey.

---

## 5. Macro strategy (decision to confirm — see §7)

**Recommendation: a separate render macro (`render_media.java.j2`), run as an
optional second pass, leaving numeric extraction untouched.**

Rationale: the user's screenplay snippet is version-specific, and **a Java
compile error is fatal to the entire macro — it cannot be try/caught.** If the
snippet were folded into `extract_all.java`, one bad paste would also break
reports/plots. A separate macro confines the compile risk *and* the black-frame
risk entirely to the opt-in render pass. Cost: one extra license checkout per
file *when rendering is requested* — acceptable for a heavy, opt-in operation.

The render macro is modeled on `RunScreenplays.java`: a stable stills/views loop
(shipped) plus a `{% if screenplay_snippet %}` block injecting the user's
recorded export call (Phase 3 only).

---

## 6. Changes by layer

### Data model — `data/models.py`
- Add `MediaKind` enum (`STILL`, `VIDEO`).
- Add `MediaArtifact` dataclass: `name`, `kind`, `path`, `source` (scene name),
  `view` (saved-view name, optional), `width/height/fps`, `error`.
- Add `media: list[MediaArtifact]` to `SimResult`. Keep `signature()`
  (homogeneity check) numeric-only.

### Macro — `macros/render_media.java.j2` + `core/macro_generator.py`
- New template (from `RunScreenplays.java`): scene-still loop using stable
  `printAndWait`; optional saved-view application per scene; a
  `{% if screenplay_snippet %}` block for the pasted export call + screenplay
  discovery.
- Macro writes a manifest `<simname>__media_index.csv`
  (`kind,source,view,name,file,error`) so the parser learns what was produced
  without globbing — mirroring `__plots_index.csv`.
- `macro_generator` gains `render_media_macro(output_dir, dest_dir, options)`
  rendering the new template with scene/view/screenplay lists, resolution, and
  the snippet.

### Runner — `core/starccm_runner.py`
- Add `render()` (or a `RenderOptions` arg) that runs the render macro pass.
  Reuse existing log streaming + license redaction.
- Support an optional render-wrapper prefix (e.g. `vglrun`) for headless GPUs, or
  document using the existing `extra_args`.

### Parser — `core/result_parser.py`
- Parse `__media_index.csv` into `MediaArtifact[]`, attach to the `SimResult`.

### Store / portable — `data/store.py`, `data/portable.py`
- store: serialize/deserialize `media[]` (paths + metadata) in the JSON cache.
- portable: keep numeric-only for now; document that media is not bundled (a
  decision — see §7). Media stays on disk, referenced by path.

### Batch — `batch/queue.py`
- Let `BatchWorker` carry render options and invoke the render pass. A render
  can't be checkpointed mid-file; stop-after-current already fits. Per-scene log
  lines give coarse progress (the macro prints each still).

### Settings — `core/settings.py` + `config/default_settings.yaml`
- New `MediaConfig` dataclass: `render_stills` (bool), `still_width`,
  `still_height`, `magnification`, `screenplay_export_snippet` (multi-line Java),
  output subdir. Full `from_dict`/`to_dict` round-trip.

### GUI
- **New view** `gui/views/media_view.py`: thumbnail/preview for stills; a list of
  videos with **Open** / **Open containing folder** (media isn't drawn like a
  plot).
- **`main_window.py`:** add a **Media** center tab; wire a render trigger.
  Recommended: a small **Run dialog** with checkboxes (Reports/Plots · Stills ·
  Screenplays) rather than overloading "Run batch", since rendering is slow/opt-in.
- **`selection_panel.py`:** add a scenes/views/screenplays section shown when the
  Media tab is active (same per-tab pattern as reports/plots).
- **`settings_dialog.py`:** new **Rendering/Screenplays** page — resolution, the
  snippet paste box, a **"Test-render one still"** button (the recommended
  headless sanity check), and the black-frame/vglrun note.
- **Export dialog / Properties / Welcome:** add media counts to Properties; an
  Export "Media" tab that *collects/copies* artifacts (lower priority — they
  already exist on disk).

### Docs / version / tests
- Update `README.md`, `docs/StarPost_Documentation.md` (Purpose, §4 Limitations
  "numeric only", §12 Design Decisions, §9 Project Structure), `CHANGELOG.md`,
  and bump the version.
- Tests: media-index parsing; store/portable round-trip with media; macro
  generation with snippet injection; `MediaConfig` round-trip.

---

## 7. Decisions to confirm before coding

1. **One macro pass or two?** Recommendation: a *separate* render macro (isolates
   version-specific, compile-fragile, GPU-dependent rendering from rock-solid
   numeric extraction), at the cost of a second license checkout per file when
   rendering. Alternative: fold into `extract_all` (single checkout) but risk a
   bad snippet breaking reports/plots.
2. **Phase scope for v1:** ✅ **DECIDED — start with Phase 1 (scene stills) only.**
   Saved views (Phase 2) and screenplays (Phase 3) are deferred to follow-ups.
3. **Trigger UX:** ✅ **DECIDED — a "Run" button at the top of the Scenes
   selection list** renders the checked scenes for the checked data sets, on its
   own thread. "Run batch" is left untouched (to be reworked later).
4. **Media in portable export:** leave portable CSV numeric-only (media stays on
   disk by path) or copy/bundle media files on export?

---

## 8. Risks

- **Headless black frames** — rendering needs a real GL context; mitigate with the
  test-still button, a documented `vglrun`/offscreen note, and Phase-1-first.
- **Version-specific screenplay (and view-manager) API** — handled via the
  paste-in snippet; needs clean settings UX + a note that it's recorded once per
  STAR-CCM+ version.
- **Compile errors from the pasted snippet** — isolated by the separate render
  macro (decision §7.1).
- **Render time + disk** — videos are slow and large; coarse per-file progress,
  stop-after-current applies, no mid-render checkpoint.
- **Model mismatch** — media doesn't compare/aggregate like numeric data; the
  cache holds metadata only, and "comparison mode" is N/A (or side-by-side
  stills).

---

## 9. Implementation order

### Phase 1 — scene stills (current work)
1. ✅ **Model** — `MediaArtifact` + `SimResult.scenes` / `SimResult.media`
   (`data/models.py`).
2. ✅ **Macro** — `extract_all.java.j2` now also writes `__scenes_index.csv`
   (names only, no rendering); new `render_scenes.java.j2` renders stills via
   `printAndWait` and writes `__media_index.csv`. Generated by
   `macro_generator.render_scenes_macro(...)`.
3. ✅ **Runner** — `StarRunner.render_scenes()` pass (reuses log streaming +
   license redaction).
4. ✅ **Parser** — `_parse_scenes()` fills `SimResult.scenes`; `parse_media_index()`
   → `MediaArtifact[]` (`result_parser.py`).
5. ✅ **Store/cache** — `scenes` + `media` round-trip in the JSON cache
   (`store.py`).
6. ✅ **Settings** — `MediaConfig` (`still_width/height`, `magnification`) +
   `config/default_settings.yaml`.
7. ✅ **Trigger** — `SceneRenderWorker` (off-thread) + a **Run** button at the top
   of the Scenes selection list (`selection_panel.py`, `main_window._run_scenes`).
8. ✅ **GUI** — `scene_view.py` (thumbnail gallery, double-click opens the image),
   a **Scenes** centre tab, and a scenes section in the selection panel.
9. **Docs / version** — *pending:* update `StarPost_Documentation.md` (drop
   "numeric only"), `README.md`, `CHANGELOG.md`; bump version.
   ✅ Tests added (`tests/test_scenes.py`): scene/media-index parsing, macro
   generation, Java-array escaping (cache + settings round-trips covered by
   existing suites).

**Still pending for Phase 1:** a Settings → Rendering page exposing
`still_width/height` + `magnification` (today they're only editable in
`settings.yaml`); user-facing docs; version bump.

### Deferred
- **Phase 2 (saved-view stills):** view discovery + apply-view-then-print +
  view-selection UI (reuses everything above).
- **Phase 3 (screenplays):** screenplay snippet plumbing + settings paste box +
  discovery.
- Export "Media" tab (collect/copy artifacts) and Properties/Welcome polish.
