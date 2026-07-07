# Screenplays Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Screenplays centre tab that records STAR-CCM+ screenplays to movie files (one movie per screenplay × saved view), mirroring the Scenes tab end-to-end.

**Architecture:** Parallel mirror of the Scenes subsystem (spec: `docs/superpowers/specs/2026-07-06-screenplays-tab-design.md`). Screenplays are *discovered* in the existing single extraction pass (extended `extract_all` macro → `__screenplays_index.csv` → `SimResult.screenplays`); *recording* is a separate on-demand pass (new `record_screenplays` macro → movies + poster PNGs → `__media_index.csv` → `MediaArtifact(kind="movie")`), driven by a new sequential QThread worker. The macro accesses the screenplay API **only via reflection** (`Class.forName` + method scanning) so an API mismatch degrades to a logged ERROR row, never a compile failure.

**Tech Stack:** Python 3.11, PySide6, Jinja2 (Java macro templates), pytest.

## Global Constraints

- Brand written **StarPost**; lowercase `starpost` only for package/path/command identifiers.
- Ruff: line-length 100, py311 target. Run `ruff check .` before each commit.
- GUI tests: run **offscreen, one file at a time, wrapped in timeout, never piped through tail**:
  `QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/<file>.py -v`
- Non-GUI tests: plain `python -m pytest tests/<file>.py -v` is fine.
- Tests touching config/cache must use the `isolated_paths` autouse fixture pattern (monkeypatch `paths.platformdirs.user_config_dir` / `user_cache_dir` to `tmp_path`).
- Commit after every task; user-facing changes go in `CHANGELOG.md` (newest first, existing style).
- Keep heavy imports lazy; do not add module-top-level imports of jinja2/pandas anywhere new.
- Do not weaken credential safety (redaction, 0600, masking). The new macro runs through the existing `StarRunner`, which already handles it.
- The central invariant: STAR-CCM+ runs once per file for extraction; recording is the on-demand exception.
- Java macro rule: the public class name must match the `.java` filename.
- Version source of truth: `__version__` in `src/starpost/__init__.py` (currently `2.2.0`; this feature ships as `2.3.0` in the final task).

---

### Task 1: Data model + cache persistence

**Files:**
- Modify: `src/starpost/data/models.py`
- Modify: `src/starpost/data/store.py`
- Test: `tests/test_screenplays.py` (new)

**Interfaces:**
- Produces: `Screenplay(name: str, scene: str = "", displayers: list[Displayer] = [])` dataclass; `SimResult.screenplays: list[Screenplay]`; `SimResult.screenplay_names() -> set[str]`; `MediaArtifact.poster: str = ""`; `kind="movie"` as the recorded-screenplay artifact kind. Cache round-trips all of it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_screenplays.py`:

```python
"""Screenplays feature: discovery, media-index parsing, record-macro generation,
settings round-trips, and cache persistence (the Screenplays tab's backend)."""
import json

from starpost.data.models import Displayer, MediaArtifact, Screenplay, SimResult
from starpost.data.store import ResultStore

CLASSIFICATION = {"residual_keywords": ["residual"], "force_keywords": ["force"]}


def test_store_round_trips_screenplays_and_movie_poster(tmp_path):
    res = SimResult(sim_path="/c/a.sim")
    res.screenplays = [
        Screenplay(
            name="Flyby",
            scene="Results",
            displayers=[Displayer(name="Scalar velocity", kind="scalar")],
        ),
    ]
    res.media = [
        MediaArtifact(
            name="Flyby-Front", path="/out/a-Flyby-Front.mp4", source="Flyby",
            kind="movie", view="Front", poster="/out/a-Flyby-Front_poster.png",
        ),
    ]
    store = ResultStore()
    store.put(res)
    path = tmp_path / "cache.json"
    store.save_cache(path)

    loaded = ResultStore()
    loaded.load_cache(path)
    got = loaded.get("/c/a.sim")
    assert [sp.name for sp in got.screenplays] == ["Flyby"]
    assert got.screenplays[0].scene == "Results"
    assert [(d.name, d.kind) for d in got.screenplays[0].displayers] == [
        ("Scalar velocity", "scalar")
    ]
    assert got.media[0].kind == "movie"
    assert got.media[0].poster == "/out/a-Flyby-Front_poster.png"
    assert got.screenplay_names() == {"Flyby"}


def test_old_cache_without_screenplays_loads_empty(tmp_path):
    # Caches written before this feature have no "screenplays" key and no
    # "poster" field on media entries; they must still load.
    store = ResultStore()
    res = SimResult(sim_path="/c/a.sim")
    res.media = [MediaArtifact(name="s", path="/out/s.png", source="S")]
    store.put(res)
    path = tmp_path / "cache.json"
    store.save_cache(path)
    payload = json.loads(path.read_text())
    for d in payload.values():
        d.pop("screenplays", None)
        for m in d.get("media", []):
            m.pop("poster", None)
    path.write_text(json.dumps(payload))

    loaded = ResultStore()
    loaded.load_cache(path)
    got = loaded.get("/c/a.sim")
    assert got.screenplays == []
    assert got.media[0].poster == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_screenplays.py -v`
Expected: FAIL with `ImportError: cannot import name 'Screenplay'`

- [ ] **Step 3: Implement the model changes**

In `src/starpost/data/models.py`, add after the `Scene` dataclass:

```python
@dataclass
class Screenplay:
    """A STAR-CCM+ screenplay (animation): the scene it plays and that scene's
    selectable scalar/vector displayers."""
    name: str
    scene: str = ""   # the scene the screenplay animates ("" if unresolved)
    displayers: list[Displayer] = field(default_factory=list)
```

In `MediaArtifact`, change the `kind` comment and add `poster` after `view`:

```python
    kind: str = "still"         # "still" | "movie" (movie == recorded screenplay)
```

```python
    view: str = ""              # the saved view applied ("" == the current view)
    poster: str = ""            # movie-kind only: absolute path to the poster PNG
```

In `SimResult`, add after the `views` field:

```python
    # Screenplays discovered in the .sim during extraction (no recording), each
    # with its scene's scalar/vector displayers; these populate the Screenplays
    # selection tree, mirroring the Scenes tree.
    screenplays: list[Screenplay] = field(default_factory=list)
```

And add next to `scene_names()`:

```python
    def screenplay_names(self) -> set[str]:
        return {s.name for s in self.screenplays}
```

- [ ] **Step 4: Implement the store changes**

In `src/starpost/data/store.py`:
- Add `Screenplay` to the `from starpost.data.models import (...)` block.
- In `_result_to_dict`, after the `"views"` entry add:

```python
        "screenplays": [asdict(sp) for sp in r.screenplays],
```

- In `_result_from_dict`, add before the `return`:

```python
    screenplays = [_screenplay_from_dict(s) for s in d.get("screenplays", [])]
```

  and pass `screenplays=screenplays,` in the `SimResult(...)` constructor call (after `views=...`).
- Add at module bottom, next to `_scene_from_dict`:

```python
def _screenplay_from_dict(s: dict) -> Screenplay:
    return Screenplay(
        name=s["name"],
        scene=s.get("scene", ""),
        displayers=[Displayer(**d) for d in s.get("displayers", [])],
    )
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_screenplays.py tests/test_store.py -v`
Expected: all PASS (`test_result_to_dict_matches_asdict` in test_store.py guards that the hand-built dict still matches `asdict` with the new field).

- [ ] **Step 6: Lint and commit**

```bash
ruff check .
git add src/starpost/data/models.py src/starpost/data/store.py tests/test_screenplays.py
git commit -m "Add Screenplay model, movie/poster media fields, cache persistence"
```

---

### Task 2: Discovery — extraction macro + parser

**Files:**
- Modify: `src/starpost/macros/extract_all.java.j2`
- Modify: `src/starpost/core/result_parser.py`
- Test: `tests/test_screenplays.py`

**Interfaces:**
- Consumes: `Screenplay` from Task 1.
- Produces: `<simname>__screenplays_index.csv` (columns `screenplay,scene,displayer,kind`) written by extraction; `parse_sim_output` fills `SimResult.screenplays`; `parse_media_index` reads an optional `poster` column into `MediaArtifact.poster`.

- [ ] **Step 1: Write the failing tests**

Add to the top import block of `tests/test_screenplays.py` (ruff's default E402 forbids mid-file module-level imports):

```python
from pathlib import Path

from starpost.core.macro_generator import render_macro
from starpost.core.result_parser import parse_media_index, parse_sim_output
```

Then append the tests:

```python
def test_parse_sim_output_reads_screenplays(tmp_path):
    sim = tmp_path / "caseA.sim"
    (tmp_path / "caseA__screenplays_index.csv").write_text(
        "screenplay,scene,displayer,kind\n"
        "Flyby,Results,Scalar velocity,scalar\n"
        "Flyby,Results,Vector 1,vector\n"
        "Intro,,,\n"  # a screenplay whose scene couldn't be resolved
    )
    res = parse_sim_output(str(sim), tmp_path, CLASSIFICATION)
    assert [s.name for s in res.screenplays] == ["Flyby", "Intro"]
    flyby = res.screenplays[0]
    assert flyby.scene == "Results"
    assert [(d.name, d.kind) for d in flyby.displayers] == [
        ("Scalar velocity", "scalar"),
        ("Vector 1", "vector"),
    ]
    intro = res.screenplays[1]
    assert intro.scene == "" and intro.displayers == []


def test_parse_sim_output_no_screenplays_index_is_empty(tmp_path):
    res = parse_sim_output(str(tmp_path / "caseA.sim"), tmp_path, CLASSIFICATION)
    assert res.screenplays == []


def test_parse_media_index_reads_movie_and_poster(tmp_path):
    (tmp_path / "caseA__media_index.csv").write_text(
        "kind,source,name,file,error,displayers,view,poster\n"
        "movie,Flyby,Flyby-Front,caseA-Flyby-Front.mp4,,"
        "Scalar velocity,Front,caseA-Flyby-Front_poster.png\n"
        "movie,Intro,Intro,,ERROR,,,\n"
    )
    media = parse_media_index("caseA", tmp_path)
    ok = media[0]
    assert ok.kind == "movie"
    assert ok.path == str((tmp_path / "caseA-Flyby-Front.mp4").resolve())
    assert ok.poster == str(
        (tmp_path / "caseA-Flyby-Front_poster.png").resolve()
    )
    bad = media[1]
    assert bad.error == "ERROR" and bad.path == "" and bad.poster == ""


def test_parse_media_index_without_poster_column(tmp_path):
    # A scenes render pass writes no poster column; artifacts default to "".
    (tmp_path / "caseA__media_index.csv").write_text(
        "kind,source,name,file,error,displayers,view\n"
        "still,Results,Results,caseA-Results.png,,,\n"
    )
    media = parse_media_index("caseA", tmp_path)
    assert media[0].poster == ""


def test_extract_macro_lists_screenplays(tmp_path):
    path = render_macro(Path("/out"), tmp_path)
    text = path.read_text()
    assert "exportScreenplays" in text
    assert "__screenplays_index.csv" in text
    # No compile-time dependency on the screenplay API.
    assert "import star.screenplay" not in text
    assert 'Class.forName("star.screenplay.ScreenplayManager")' in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_screenplays.py -v`
Expected: the five new tests FAIL (`res.screenplays == []`, missing poster attr content, macro text asserts).

- [ ] **Step 3: Extend the extraction macro**

In `src/starpost/macros/extract_all.java.j2`:

1. Update the header comment's outputs list (after the `__views_index.csv` line):

```java
//   <simname>__screenplays_index.csv screenplay,scene,displayer,kind
```

2. In `execute()`, after `exportViews(sim, simName, dir);` add:

```java
        exportScreenplays(sim, simName, dir);
```

3. Add these methods after `exportViews` (they reuse the existing `presentationName` and `esc` helpers):

```java
    // Lists the screenplays (animations) in the .sim and, for each, the scene
    // it plays and that scene's scalar/vector displayers. One row per
    // (screenplay, displayer); a screenplay with no such displayers still gets
    // a row with empty displayer/kind so it appears in the Screenplays tree.
    //
    // The screenplay API only exists on recent releases (2022+) and its class
    // names are never referenced at compile time (a compile error is fatal to
    // the whole macro): the manager comes from Class.forName, so on an older
    // release this writes a header-only index and extraction is unaffected.
    private void exportScreenplays(Simulation sim, String simName, String dir) {
        String out = dir + File.separator + simName + "__screenplays_index.csv";
        try (PrintWriter w = new PrintWriter(new FileWriter(out))) {
            w.println("screenplay,scene,displayer,kind");
            for (Object sp : screenplays(sim)) {
                String name = presentationName(sp);
                if (name == null) {
                    continue;
                }
                Scene scene = screenplayScene(sp);
                String sceneName = (scene == null)
                    ? "" : scene.getPresentationName();
                boolean any = false;
                if (scene != null) {
                    for (DisplayerBase d
                            : scene.getDisplayerManager().getObjects()) {
                        String kind = null;
                        if (d instanceof ScalarDisplayer) {
                            kind = "scalar";
                        } else if (d instanceof VectorDisplayer) {
                            kind = "vector";
                        }
                        if (kind != null) {
                            w.println(esc(name) + "," + esc(sceneName) + ","
                                + esc(d.getPresentationName()) + "," + kind);
                            any = true;
                        }
                    }
                }
                if (!any) {
                    w.println(esc(name) + "," + esc(sceneName) + ",,");
                }
            }
        } catch (Exception e) {
            sim.println("starpost: failed to write screenplays index: "
                + e.getMessage());
        }
    }

    // The sim's screenplays, or an empty list when this release has none.
    private java.util.List<Object> screenplays(Simulation sim) {
        java.util.List<Object> out = new java.util.ArrayList<>();
        try {
            Class<?> mgrClass =
                Class.forName("star.screenplay.ScreenplayManager");
            Object mgr = Simulation.class.getMethod("get", Class.class)
                .invoke(sim, mgrClass);
            Object objs = mgr.getClass().getMethod("getObjects").invoke(mgr);
            for (Object sp : (Iterable<?>) objs) {
                out.add(sp);
            }
        } catch (Exception e) {
            sim.println("starpost: no screenplays found ("
                + e.getMessage() + ")");
        }
        return out;
    }

    // The Scene a screenplay plays, found by probing common accessors on the
    // screenplay and its actors (the concrete API differs across releases).
    // Returns null when no scene can be resolved.
    private Scene screenplayScene(Object sp) {
        Object scene = firstScene(invokeQuiet(sp, "getScene"));
        if (scene == null) {
            scene = firstScene(invokeQuiet(sp, "getScenes"));
        }
        if (scene == null) {
            Object actors = invokeQuiet(sp, "getActors");
            if (actors instanceof Iterable) {
                for (Object actor : (Iterable<?>) actors) {
                    scene = firstScene(invokeQuiet(actor, "getScene"));
                    if (scene != null) {
                        break;
                    }
                }
            }
        }
        return (scene instanceof Scene) ? (Scene) scene : null;
    }

    // o itself when it is a Scene, else the first Scene inside an Iterable o.
    private Object firstScene(Object o) {
        if (o instanceof Scene) {
            return o;
        }
        if (o instanceof Iterable) {
            for (Object item : (Iterable<?>) o) {
                if (item instanceof Scene) {
                    return item;
                }
            }
        }
        return null;
    }

    // getMethod(name).invoke(o), or null if the method doesn't exist/fails.
    private Object invokeQuiet(Object o, String method) {
        if (o == null) return null;
        try {
            return o.getClass().getMethod(method).invoke(o);
        } catch (Exception e) {
            return null;
        }
    }
```

- [ ] **Step 4: Extend the parser**

In `src/starpost/core/result_parser.py`:

1. Add `Screenplay` to the models import block.
2. In `parse_sim_output`, after the `result.views = ...` line add:

```python
    result.screenplays = _parse_screenplays(
        output_dir / f"{sim_name}__screenplays_index.csv"
    )
```

3. Add after `_parse_scenes`:

```python
def _parse_screenplays(path: Path) -> list[Screenplay]:
    """Read the screenplays index (``screenplay,scene,displayer,kind`` rows)
    into Screenplays, each carrying its scene's scalar/vector displayers. Rows
    are grouped by screenplay; a row with an empty displayer just registers the
    screenplay. Preserves first-seen order."""
    if not path.exists():
        # Older extractions (pre-screenplays) simply have no screenplay list.
        return []
    plays: dict[str, Screenplay] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("screenplay") or "").strip()
            if not name:
                continue
            play = plays.setdefault(
                name,
                Screenplay(name=name, scene=(row.get("scene") or "").strip()),
            )
            disp = (row.get("displayer") or "").strip()
            kind = (row.get("kind") or "").strip() or "scalar"
            if disp:
                play.displayers.append(Displayer(name=disp, kind=kind))
    return list(plays.values())
```

4. In `parse_media_index`, inside the row loop, after the `full = ...` line add:

```python
            poster_cell = (row.get("poster") or "").strip()
            poster = (
                str((output_dir / poster_cell).resolve()) if poster_cell else ""
            )
```

   and add `poster=poster,` to the `MediaArtifact(...)` constructor call.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_screenplays.py tests/test_scenes.py tests/test_result_parser.py -v`
Expected: all PASS (scene tests confirm no regression in the shared media-index parser).

- [ ] **Step 6: Lint and commit**

```bash
ruff check .
git add src/starpost/macros/extract_all.java.j2 src/starpost/core/result_parser.py tests/test_screenplays.py
git commit -m "Discover screenplays during extraction; parse movie/poster media"
```

---

### Task 3: Settings — movie recording configuration

**Files:**
- Modify: `src/starpost/core/settings.py`
- Modify: `config/default_settings.yaml`
- Test: `tests/test_screenplays.py`

**Interfaces:**
- Produces: `MOVIE_FORMATS = ("mp4", "avi", "mov")`, `MOVIE_QUALITIES = ("low", "medium", "high")`; `MediaConfig.movie_format/movie_fps/movie_resolution/movie_quality/screenplays_per_checkout`; `MediaConfig.movie_dimensions() -> tuple[int, int]`. Full `from_dict`/`to_dict` round-trip with clamping.

- [ ] **Step 1: Write the failing tests**

Add to the top import block of `tests/test_screenplays.py`:

```python
from starpost.core.settings import MediaConfig, Settings
```

Then append the tests:

```python
def test_media_config_movie_defaults():
    m = MediaConfig()
    assert m.movie_format == "mp4"
    assert m.movie_fps == 30
    assert m.movie_resolution == "1080p"
    assert m.movie_quality == "high"
    assert m.screenplays_per_checkout == 1
    assert m.movie_dimensions() == (1920, 1080)
    assert MediaConfig(movie_resolution="2160p").movie_dimensions() == (3840, 2160)


def test_media_config_movie_round_trip():
    s = Settings.from_dict({"media": {
        "movie_format": "AVI",
        "movie_fps": 24,
        "movie_resolution": "2160p",
        "movie_quality": "Medium",
        "screenplays_per_checkout": 3,
    }})
    assert s.media.movie_format == "avi"          # normalized to lowercase
    assert s.media.movie_fps == 24
    assert s.media.movie_resolution == "2160p"
    assert s.media.movie_quality == "medium"
    assert s.media.screenplays_per_checkout == 3
    out = s.to_dict()["media"]
    assert out["movie_format"] == "avi"
    assert out["movie_fps"] == 24
    assert out["movie_resolution"] == "2160p"
    assert out["movie_quality"] == "medium"
    assert out["screenplays_per_checkout"] == 3


def test_media_config_movie_values_clamped():
    # Unknown values fall back to defaults; counts are coerced to >= 1.
    s = Settings.from_dict({"media": {
        "movie_format": "webm",
        "movie_resolution": "4320p",
        "movie_quality": "ultra",
        "movie_fps": 0,
        "screenplays_per_checkout": 0,
    }})
    assert s.media.movie_format == "mp4"
    assert s.media.movie_resolution == "1080p"
    assert s.media.movie_quality == "high"
    assert s.media.movie_fps == 1
    assert s.media.screenplays_per_checkout == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_screenplays.py -v`
Expected: the three new tests FAIL with `AttributeError: ... 'movie_format'`.

- [ ] **Step 3: Implement the settings changes**

In `src/starpost/core/settings.py`:

1. Add to the `MediaConfig` dataclass (after `image_resolution`), plus a docstring paragraph describing the movie fields:

```python
    # Screenplay recording (Screenplays tab → Record).
    movie_format: str = "mp4"        # recorded movie container: mp4 | avi | mov
    movie_fps: int = 30              # recorded movie frame rate
    movie_resolution: str = "1080p"  # recording resolution: "1080p" | "2160p"
    movie_quality: str = "high"      # encoder quality: low | medium | high
    screenplays_per_checkout: int = 1  # screenplays recorded per checkout
```

```python
    def movie_dimensions(self) -> tuple[int, int]:
        """The (width, height) in pixels for the configured movie resolution."""
        return IMAGE_RESOLUTIONS.get(
            self.movie_resolution, IMAGE_RESOLUTIONS["1080p"]
        )
```

2. Add module constants next to `IMAGE_FORMATS`:

```python
# Movie containers offered for screenplay recording (file extension == value).
MOVIE_FORMATS = ("mp4", "avi", "mov")

# Encoder quality levels for screenplay recording; the record macro maps them
# to a 0..1 quality factor (low/medium/high -> 0.5/0.75/1.0).
MOVIE_QUALITIES = ("low", "medium", "high")
```

3. In `Settings.from_dict`, extend the `MediaConfig(...)` call:

```python
                movie_format=(
                    str(med.get("movie_format", "mp4")).lower()
                    if str(med.get("movie_format", "mp4")).lower()
                    in MOVIE_FORMATS
                    else "mp4"
                ),
                movie_fps=max(1, int(med.get("movie_fps", 30))),
                movie_resolution=(
                    str(med.get("movie_resolution", "1080p")).lower()
                    if str(med.get("movie_resolution", "1080p")).lower()
                    in IMAGE_RESOLUTIONS
                    else "1080p"
                ),
                movie_quality=(
                    str(med.get("movie_quality", "high")).lower()
                    if str(med.get("movie_quality", "high")).lower()
                    in MOVIE_QUALITIES
                    else "high"
                ),
                screenplays_per_checkout=max(
                    1, int(med.get("screenplays_per_checkout", 1))
                ),
```

4. In `Settings.to_dict`, extend the `"media"` dict:

```python
                "movie_format": self.media.movie_format,
                "movie_fps": self.media.movie_fps,
                "movie_resolution": self.media.movie_resolution,
                "movie_quality": self.media.movie_quality,
                "screenplays_per_checkout": self.media.screenplays_per_checkout,
```

5. In `config/default_settings.yaml`, extend the `media:` block:

```yaml
  # Screenplay recording (Screenplays tab → Record).
  movie_format: mp4          # recorded movie container: mp4 | avi | mov
  movie_fps: 30              # recorded movie frame rate
  movie_resolution: 1080p    # recording resolution: 1080p | 2160p
  movie_quality: high        # encoder quality: low | medium | high
  screenplays_per_checkout: 1  # screenplays recorded per license checkout
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_screenplays.py tests/test_settings.py tests/test_scenes.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/core/settings.py config/default_settings.yaml tests/test_screenplays.py
git commit -m "Add movie recording settings to MediaConfig"
```

---

### Task 4: Record macro template + generator

**Files:**
- Create: `src/starpost/macros/record_screenplays.java.j2`
- Modify: `src/starpost/core/macro_generator.py`
- Test: `tests/test_screenplays.py`

**Interfaces:**
- Consumes: `_java_show_map_puts`, `_java_string_array`, `_get_env` (existing, `macro_generator.py`).
- Produces: `record_screenplays_macro(output_dir: Path, dest_dir: Path, screenplay_show: dict[str, list[str]], view_names: list[str], width: int, height: int, fps: int, movie_format: str = "mp4", quality: str = "high") -> Path` (returns the written `.java` path; class `record_screenplays`).

- [ ] **Step 1: Write the failing test**

Add to the top import block of `tests/test_screenplays.py`: `import tempfile`, and extend the macro_generator import to `from starpost.core.macro_generator import record_screenplays_macro, render_macro`. Then append the test:

```python
def test_record_screenplays_macro_embeds_selection_and_movie_settings():
    with tempfile.TemporaryDirectory() as d:
        path = record_screenplays_macro(
            Path("/out"),
            Path(d),
            {"Flyby": ["Scalar velocity"], "Intro": []},
            ["Front"],
            1920,
            1080,
            24,
            "avi",
            "medium",
        )
        text = path.read_text()
        assert path.name == "record_screenplays.java"
        assert "public class record_screenplays" in text
        assert 'MOV_EXT = "avi"' in text
        assert "FPS = 24" in text
        assert "MOV_WIDTH = 1920" in text and "MOV_HEIGHT = 1080" in text
        assert "QUALITY = 0.75" in text
        assert 'VIEW_NAMES = { "Front" }' in text
        assert (
            'm.put("Flyby", new LinkedHashSet<>(Arrays.asList('
            '"Scalar velocity")));'
        ) in text
        assert 'm.put("Intro", new LinkedHashSet<>(Arrays.asList()));' in text
        # No compile-time dependency on the screenplay API; graceful lookup.
        assert "import star.screenplay" not in text
        assert "Class.forName" in text
        # Each screenplay's scene is closed to free graphics memory.
        assert "scene.close()" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_screenplays.py -v`
Expected: FAIL with `ImportError: cannot import name 'record_screenplays_macro'`

- [ ] **Step 3: Create the macro template**

Create `src/starpost/macros/record_screenplays.java.j2` with exactly:

```java
// Auto-generated by starpost. Records screenplay MOVIES from the open
// simulation. Run via:  starccm+ -batch <this>.java [...] file.sim
//
// SEPARATE macro from extract_all (same reasoning as render_scenes): recording
// goes through OpenGL and the encoder, is heavy, and is only run on demand
// from the Screenplays tab.
//
// Outputs (in {{ output_dir }}):
//   <dataset>-<screenplay>[-<displayers>][-<view>].<ext>       one movie per
//                                                  screenplay (per chosen view)
//   <dataset>-<screenplay>[-<displayers>][-<view>]_poster.png  a poster frame
//   <simname>__media_index.csv  kind,source,name,file,error,displayers,view,poster
//
// SHOW maps each screenplay to record -> the scalar/vector displayers of its
// scene to keep visible; every other scalar/vector displayer in that scene is
// hidden first. VIEW_NAMES are the saved camera views: each screenplay is
// recorded once per view (empty = the screenplay's own/current camera).
//
// The screenplay API's class names shift across releases and a Java compile
// error is fatal to the whole macro, so it is never referenced at compile
// time: the manager comes from Class.forName and the record call is found by
// scanning the screenplay's public methods (invokeRecord). On a mismatch the
// screenplay gets an ERROR row and the run continues.
package macro;

import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import star.common.*;
import star.vis.*;           // Scene, VisView, displayers (not in star.common)

public class record_screenplays extends StarMacro {

    private static final int MOV_WIDTH = {{ width }};
    private static final int MOV_HEIGHT = {{ height }};
    private static final int FPS = {{ fps }};
    private static final String MOV_EXT = "{{ movie_ext }}";  // mp4 | avi | mov
    private static final double QUALITY = {{ quality_factor }};  // 0..1 factor
    // Saved views to record each screenplay from; empty == its own camera.
    private static final String[] VIEW_NAMES = { {{ view_names_java }} };

    // Screenplay -> scalar/vector displayers to keep visible (user-checked).
    private static Map<String, Set<String>> showMap() {
        Map<String, Set<String>> m = new HashMap<>();
        {{ show_map_puts }}
        return m;
    }

    public void execute() {
        Simulation sim = getActiveSimulation();
        String simPath = sim.getSessionPath();
        String simName = new File(simPath).getName().replaceAll("\\.sim$", "");
        String dir = "{{ output_dir }}";
        Map<String, Set<String>> show = showMap();

        String indexPath = dir + File.separator + simName + "__media_index.csv";
        try (PrintWriter idx = new PrintWriter(new FileWriter(indexPath))) {
            idx.println("kind,source,name,file,error,displayers,view,poster");
            for (Object sp : screenplays(sim)) {
                String name = presentationName(sp);
                if (name == null || !show.containsKey(name)) {
                    continue;
                }
                Scene scene = screenplayScene(sp);
                Set<String> visible = show.get(name);
                if (scene != null) {
                    applyVisibility(sim, scene, visible);
                }
                try {
                    if (VIEW_NAMES.length == 0) {
                        recordOne(sim, idx, sp, scene, simName, dir, name,
                            null, visible);
                    } else {
                        for (String view : VIEW_NAMES) {
                            if (scene != null) {
                                applyView(sim, scene, view);
                            }
                            recordOne(sim, idx, sp, scene, simName, dir, name,
                                view, visible);
                        }
                    }
                } finally {
                    // Release this screenplay's scene before the next one.
                    // Best-effort: never let closing abort the run.
                    if (scene != null) {
                        try {
                            scene.close();
                        } catch (Exception ce) {
                            sim.println("starpost: could not close scene for '"
                                + name + "': " + ce.getMessage());
                        }
                    }
                }
            }
        } catch (IOException e) {
            sim.println("starpost: failed to write media index: "
                + e.getMessage());
        }
    }

    // Records one movie of screenplay sp (optionally from saved view viewName)
    // plus a poster frame, and writes the media-index row. A null viewName
    // records from the screenplay's own/current camera.
    private void recordOne(Simulation sim, PrintWriter idx, Object sp,
                           Scene scene, String simName, String dir, String name,
                           String viewName, Set<String> visible) {
        String disp = (visible.size() > 1)
            ? "multiple-fields" : joinNames(visible);
        String dispReadable = String.join(", ", visible);
        String viewStr = (viewName == null) ? "" : viewName;
        String label = name;
        if (!disp.isEmpty()) label += "-" + disp;
        if (viewName != null) label += "-" + viewName;

        String base = sanitizeFile(simName + "-" + label);
        String movie = base + "." + MOV_EXT;
        String poster = base + "_poster.png";
        String moviePath = dir + File.separator + movie;
        String posterPath = dir + File.separator + poster;
        String tail = "," + esc(dispReadable) + "," + esc(viewStr);

        // Poster first: cheap, and useful in the gallery even if the recording
        // itself fails.
        boolean hasPoster = false;
        if (scene != null) {
            try {
                scene.printAndWait(resolvePath(posterPath), 1,
                    MOV_WIDTH, MOV_HEIGHT);
                hasPoster = true;
            } catch (Exception e) {
                sim.println("starpost: failed to render poster for '" + label
                    + "': " + e.getMessage());
            }
        }
        String posterCell = hasPoster ? esc(poster) : "";
        try {
            invokeRecord(sim, sp, resolvePath(moviePath));
            idx.println("movie," + esc(name) + "," + esc(label) + ","
                + esc(movie) + "," + tail + "," + posterCell);
            sim.println("starpost: recorded '" + label + "' -> " + movie);
        } catch (Exception e) {
            sim.println("starpost: failed to record '" + label + "': "
                + e.getMessage());
            idx.println("movie," + esc(name) + "," + esc(label) + ",,ERROR"
                + tail + "," + posterCell);
        }
    }

    // Finds and invokes a record/export method on the screenplay reflectively.
    // Candidates: public methods named "record" or starting with "export",
    // whose parameters can all be filled from what we have:
    //   String       -> the output file path (first String parameter only)
    //   int/long     -> width, height, fps (in positional order, then 0)
    //   float/double -> the QUALITY factor
    //   boolean      -> false
    // Tried smallest parameter list first; the first successful call wins. If
    // none succeeds, throws with the candidate signatures so the log shows
    // what this release offers.
    private void invokeRecord(Simulation sim, Object sp, String path)
            throws Exception {
        List<Method> candidates = new ArrayList<>();
        for (Method m : sp.getClass().getMethods()) {
            String n = m.getName().toLowerCase();
            if (n.equals("record") || n.startsWith("export")) {
                candidates.add(m);
            }
        }
        candidates.sort(Comparator.comparingInt(Method::getParameterCount));
        StringBuilder tried = new StringBuilder();
        for (Method m : candidates) {
            Object[] args = fillArgs(m.getParameterTypes(), path);
            if (args == null) {
                continue;
            }
            tried.append("\n  ").append(m.toString());
            try {
                m.invoke(sp, args);
                sim.println("starpost: recorded via " + m.getName() + "/"
                    + m.getParameterCount());
                return;
            } catch (Exception e) {
                // try the next candidate
            }
        }
        throw new Exception("no usable record/export method found on "
            + sp.getClass().getName() + "; candidates tried:" + tried);
    }

    // The argument list for the parameter types, or null when a type can't be
    // filled (or no String parameter exists to receive the output path).
    private Object[] fillArgs(Class<?>[] types, String path) {
        Object[] args = new Object[types.length];
        boolean pathUsed = false;
        int ints = 0;
        int[] intVals = { MOV_WIDTH, MOV_HEIGHT, FPS };
        for (int i = 0; i < types.length; i++) {
            Class<?> t = types[i];
            if (t == String.class && !pathUsed) {
                args[i] = path;
                pathUsed = true;
            } else if (t == int.class || t == Integer.class
                    || t == long.class || t == Long.class) {
                int v = (ints < intVals.length) ? intVals[ints++] : 0;
                args[i] = (t == long.class || t == Long.class)
                    ? (Object) (long) v : (Object) v;
            } else if (t == double.class || t == Double.class) {
                args[i] = QUALITY;
            } else if (t == float.class || t == Float.class) {
                args[i] = (float) QUALITY;
            } else if (t == boolean.class || t == Boolean.class) {
                args[i] = Boolean.FALSE;
            } else {
                return null;  // a type we can't supply
            }
        }
        return pathUsed ? args : null;
    }

    // The sim's screenplays, or an empty list when this release has none.
    private java.util.List<Object> screenplays(Simulation sim) {
        java.util.List<Object> out = new java.util.ArrayList<>();
        try {
            Class<?> mgrClass =
                Class.forName("star.screenplay.ScreenplayManager");
            Object mgr = Simulation.class.getMethod("get", Class.class)
                .invoke(sim, mgrClass);
            Object objs = mgr.getClass().getMethod("getObjects").invoke(mgr);
            for (Object sp : (Iterable<?>) objs) {
                out.add(sp);
            }
        } catch (Exception e) {
            sim.println("starpost: no screenplays found ("
                + e.getMessage() + ")");
        }
        return out;
    }

    // The Scene a screenplay plays, found by probing common accessors on the
    // screenplay and its actors. Returns null when no scene can be resolved.
    private Scene screenplayScene(Object sp) {
        Object scene = firstScene(invokeQuiet(sp, "getScene"));
        if (scene == null) {
            scene = firstScene(invokeQuiet(sp, "getScenes"));
        }
        if (scene == null) {
            Object actors = invokeQuiet(sp, "getActors");
            if (actors instanceof Iterable) {
                for (Object actor : (Iterable<?>) actors) {
                    scene = firstScene(invokeQuiet(actor, "getScene"));
                    if (scene != null) {
                        break;
                    }
                }
            }
        }
        return (scene instanceof Scene) ? (Scene) scene : null;
    }

    // o itself when it is a Scene, else the first Scene inside an Iterable o.
    private Object firstScene(Object o) {
        if (o instanceof Scene) {
            return o;
        }
        if (o instanceof Iterable) {
            for (Object item : (Iterable<?>) o) {
                if (item instanceof Scene) {
                    return item;
                }
            }
        }
        return null;
    }

    // getMethod(name).invoke(o), or null if the method doesn't exist/fails.
    private Object invokeQuiet(Object o, String method) {
        if (o == null) return null;
        try {
            return o.getClass().getMethod(method).invoke(o);
        } catch (Exception e) {
            return null;
        }
    }

    // Joins displayer names with "_" in iteration order (the map uses a
    // LinkedHashSet so this matches the user's selection order).
    private String joinNames(Set<String> names) {
        StringBuilder sb = new StringBuilder();
        for (String n : names) {
            if (sb.length() > 0) {
                sb.append("_");
            }
            sb.append(n);
        }
        return sb.toString();
    }

    private String sanitizeFile(String s) {
        return s.replaceAll("[^A-Za-z0-9._-]", "_");
    }

    // Apply the saved view named viewName to the scene's current view (matched
    // by its reflective name, applied via the VisView base type). Best-effort.
    private void applyView(Simulation sim, Scene s, String viewName) {
        try {
            for (Object o : sim.getViewManager().getObjects()) {
                if (viewName.equals(presentationName(o))) {
                    s.getCurrentView().setView((VisView) o);
                    return;
                }
            }
            sim.println("starpost: saved view '" + viewName + "' not found");
        } catch (Exception e) {
            sim.println("starpost: could not apply view '" + viewName
                + "': " + e.getMessage());
        }
    }

    // getPresentationName() via reflection — avoids depending on a concrete
    // class name that differs across releases.
    private String presentationName(Object o) {
        try {
            return String.valueOf(
                o.getClass().getMethod("getPresentationName").invoke(o));
        } catch (Exception e) {
            return null;
        }
    }

    // Hide the scalar/vector displayers NOT in keepVisible by setting their
    // opacity to 0; leave checked ones and all other displayer types alone.
    // The .sim is never saved, so these changes are discarded on exit.
    private void applyVisibility(Simulation sim, Scene s,
                                 Set<String> keepVisible) {
        for (DisplayerBase d : s.getDisplayerManager().getObjects()) {
            boolean isField = (d instanceof ScalarDisplayer)
                || (d instanceof VectorDisplayer);
            if (!isField || keepVisible.contains(d.getPresentationName())) {
                continue;
            }
            try {
                if (d instanceof ScalarDisplayer) {
                    ((ScalarDisplayer) d).setOpacity(0.0);
                } else {
                    ((VectorDisplayer) d).setOpacity(0.0);
                }
            } catch (Exception e) {
                sim.println("starpost: could not hide displayer '"
                    + d.getPresentationName() + "': " + e.getMessage());
            }
        }
    }

    private String esc(String s) {
        if (s == null) return "";
        if (s.contains(",") || s.contains("\"") || s.contains("\n")) {
            return "\"" + s.replace("\"", "\"\"") + "\"";
        }
        return s;
    }
}
```

- [ ] **Step 4: Add the generator function**

In `src/starpost/core/macro_generator.py`, add after the `_RENDER_CLASS_NAME` constants:

```python
_RECORD_TEMPLATE = "record_screenplays.java.j2"
_RECORD_CLASS_NAME = "record_screenplays"

# Encoder quality factor per MOVIE_QUALITIES level, embedded in the record
# macro (passed to float/double recorder parameters).
_QUALITY_FACTORS = {"low": 0.5, "medium": 0.75, "high": 1.0}
```

and add after `render_scenes_macro`:

```python
def record_screenplays_macro(
    output_dir: Path,
    dest_dir: Path,
    screenplay_show: dict[str, list[str]],
    view_names: list[str],
    width: int,
    height: int,
    fps: int,
    movie_format: str = "mp4",
    quality: str = "high",
) -> Path:
    """Render the screenplay-record macro that exports to ``output_dir``.
    Returns the .java path. ``screenplay_show`` maps each screenplay to record
    to the scalar/vector displayers of its scene to keep visible.
    ``view_names`` are the saved camera views to record each screenplay from;
    empty records from each screenplay's own camera. ``movie_format`` is the
    output file extension (mp4/avi/mov), which STAR-CCM+ uses to pick the
    encoder; ``quality`` is a MOVIE_QUALITIES level mapped to a 0..1 factor.

    ``dest_dir`` is where the .java file is written (a temp dir per run).
    """
    out = str(output_dir).replace("\\", "/")
    text = _get_env().get_template(_RECORD_TEMPLATE).render(
        output_dir=out,
        show_map_puts=_java_show_map_puts(screenplay_show),
        view_names_java=_java_string_array(view_names),
        width=int(width),
        height=int(height),
        fps=int(fps),
        movie_ext=str(movie_format),
        quality_factor=_QUALITY_FACTORS.get(str(quality), 1.0),
    )
    java_path = dest_dir / f"{_RECORD_CLASS_NAME}.java"
    java_path.write_text(text, encoding="utf-8")
    return java_path
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_screenplays.py tests/test_scenes.py -v`
Expected: all PASS.

- [ ] **Step 6: Lint and commit**

```bash
ruff check .
git add src/starpost/macros/record_screenplays.java.j2 src/starpost/core/macro_generator.py tests/test_screenplays.py
git commit -m "Add reflective screenplay-record macro and generator"
```

---

### Task 5: Runner method + record worker

**Files:**
- Modify: `src/starpost/core/starccm_runner.py`
- Modify: `src/starpost/batch/queue.py`
- Test: `tests/test_screenplays.py`

**Interfaces:**
- Consumes: `record_screenplays_macro` (Task 4), `MediaConfig.movie_*` (Task 3), `parse_media_index` poster support (Task 2).
- Produces: `StarRunner.record_screenplays(sim_file: Path, output_dir: Path, screenplay_show: dict[str, list[str]], view_names: list[str] | None = None, log_sink=None) -> list[MediaArtifact]` (movie-kind only; raises `StarRunError` on a non-zero exit); `ScreenplayRecordWorker(jobs: list[tuple[Path, dict[str, list[str]]]], runner, output_dir: Path, views=None)` with signals `log(str)`, `progress(int, int)`, `recorded(object, object)`, `finished()` and a `run()` slot.

- [ ] **Step 1: Write the failing tests**

Add `import pytest` to the top import block of `tests/test_screenplays.py`, then append:

```python
@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _StubRunner:
    """Duck-typed runner for worker tests: records calls, returns canned
    artifacts or raises."""

    def __init__(self, artifacts=None, error=None):
        self.calls = []
        self._artifacts = artifacts or []
        self._error = error

    def record_screenplays(self, sim_file, output_dir, show, views,
                           log_sink=None):
        self.calls.append((sim_file, dict(show), list(views)))
        if self._error:
            raise self._error
        return list(self._artifacts)


def test_screenplay_record_worker_emits_artifacts(app, tmp_path):
    from starpost.batch.queue import ScreenplayRecordWorker

    art = MediaArtifact(name="Flyby", path="/out/a.mp4", source="Flyby",
                        kind="movie")
    runner = _StubRunner(artifacts=[art])
    jobs = [(tmp_path / "a.sim", {"Flyby": ["Scalar velocity"]})]
    worker = ScreenplayRecordWorker(jobs, runner, tmp_path, views=["Front"])
    recorded, progress, finished = [], [], []
    worker.recorded.connect(lambda sp, arts: recorded.append((sp, arts)))
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    worker.finished.connect(lambda: finished.append(1))
    worker.run()
    assert recorded == [(str(tmp_path / "a.sim"), [art])]
    assert progress == [(1, 1)] and finished == [1]
    assert runner.calls == [
        (tmp_path / "a.sim", {"Flyby": ["Scalar velocity"]}, ["Front"])
    ]


def test_screenplay_record_worker_continues_after_failure(app, tmp_path):
    from starpost.batch.queue import ScreenplayRecordWorker

    runner = _StubRunner(error=RuntimeError("boom"))
    jobs = [
        (tmp_path / "a.sim", {"Flyby": []}),
        (tmp_path / "b.sim", {"Intro": []}),
    ]
    worker = ScreenplayRecordWorker(jobs, runner, tmp_path)
    logs, finished = [], []
    worker.log.connect(logs.append)
    worker.finished.connect(lambda: finished.append(1))
    worker.run()
    assert finished == [1]
    assert len(runner.calls) == 2  # the second job still ran
    assert any("Recording failed" in line for line in logs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_screenplays.py -v`
Expected: the two worker tests FAIL with `ImportError: cannot import name 'ScreenplayRecordWorker'`. (This file now instantiates a QApplication, so run it offscreen from here on.)

- [ ] **Step 3: Add the runner method**

In `src/starpost/core/starccm_runner.py`:
- Extend the macro_generator import: `from starpost.core.macro_generator import (record_screenplays_macro, render_macro, render_scenes_macro)`.
- Add after `render_scenes`:

```python
    def record_screenplays(
        self,
        sim_file: Path,
        output_dir: Path,
        screenplay_show: dict[str, list[str]],
        view_names: Optional[list[str]] = None,
        log_sink: Optional[LogSink] = None,
    ) -> list[MediaArtifact]:
        """Record the given screenplays of one .sim to movie files.

        ``screenplay_show`` maps each screenplay to record to the scalar/vector
        displayers of its scene to keep visible. ``view_names`` are the saved
        views to record each screenplay from (empty/None == its own camera).
        Runs the separate record macro (one license checkout) and returns the
        movie artifacts from the media index.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        sink = log_sink or (lambda s: None)
        media = self.settings.media
        np = self._render_np(media)
        width, height = media.movie_dimensions()

        with tempfile.TemporaryDirectory(prefix="starpost_macro_") as tmp:
            macro = record_screenplays_macro(
                output_dir,
                Path(tmp),
                screenplay_show,
                list(view_names or []),
                width,
                height,
                media.movie_fps,
                media.movie_format,
                media.movie_quality,
            )
            cmd = self.build_command(macro, sim_file, np=np)
            shown = redact_command(cmd)
            sink(f"$ {shown}")
            log.info("recording screenplays: %s", shown)

            code = self._stream(cmd, sink)
            if code != 0:
                msg = f"starccm+ exited with code {code} for {sim_file.name}"
                sink(msg)
                raise StarRunError(msg)

        artifacts = parse_media_index(sim_file.stem, output_dir)
        movies = [a for a in artifacts if a.kind == "movie"]
        sink(f"Recorded {len(movies)} movie(s) from {sim_file.name}")
        return movies
```

- [ ] **Step 4: Add the worker**

In `src/starpost/batch/queue.py`, add after `SceneRenderWorker`:

```python
class ScreenplayRecordWorker(QObject):
    """Records screenplay movies off the GUI thread, one .sim per STAR-CCM+
    process. Each job is a (sim_file, screenplay_show) pair, where
    screenplay_show maps each screenplay to record to the displayers to keep
    visible; all of a job's screenplays are recorded in a single starccm+
    invocation — one license checkout, the sim loaded once. Runs sequentially
    (license-safe) and emits the recorded artifacts per file so the UI can
    attach them to results. Mirrors SceneRenderWorker.
    """

    log = Signal(str)                  # a line of record output
    progress = Signal(int, int)        # (completed, total)
    recorded = Signal(object, object)  # (sim_path: str, list[MediaArtifact])
    finished = Signal()

    def __init__(
        self,
        jobs: list[tuple[Path, dict[str, list[str]]]],
        runner: StarRunner,
        output_dir: Path,
        views: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._runner = runner
        self._output_dir = output_dir
        self._views = list(views or [])

    def run(self) -> None:
        total = len(self._jobs)
        for i, (sim_file, screenplay_show) in enumerate(self._jobs):
            self.log.emit(f"--- [{i + 1}/{total}] recording {sim_file.name} ---")
            try:
                artifacts = self._runner.record_screenplays(
                    sim_file, self._output_dir, screenplay_show, self._views,
                    log_sink=self.log.emit,
                )
                self.recorded.emit(str(sim_file), artifacts)
            except Exception as e:  # noqa: BLE001 - surface any failure to UI
                self.log.emit(f"Recording failed for {sim_file.name}: {e}")
            self.progress.emit(i + 1, total)
        self.finished.emit()
```

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_screenplays.py tests/test_starccm_runner.py -v`
Expected: all PASS.

- [ ] **Step 6: Lint and commit**

```bash
ruff check .
git add src/starpost/core/starccm_runner.py src/starpost/batch/queue.py tests/test_screenplays.py
git commit -m "Add StarRunner.record_screenplays and ScreenplayRecordWorker"
```

---

### Task 6: Selection panel — Screenplays tree + section

**Files:**
- Modify: `src/starpost/gui/views/selection_panel.py`
- Test: `tests/test_screenplays_gui.py` (new)

**Interfaces:**
- Consumes: `_SceneTree` (existing).
- Produces: `SelectionPanel.screenplays` (`_ScreenplayTree`); signals `record_screenplays_requested`, `clear_screenplays_requested`; `set_available_screenplays(groups: dict[str, list[str]])`, `selected_screenplays() -> set[str]`, `selected_screenplay_displayers() -> dict[str, list[str]]`; `set_active_section("screenplays")` shows the Screenplays tree + shared Saved views list.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_screenplays_gui.py`:

```python
"""GUI tests for the Screenplays tab widgets (offscreen)."""
import pytest

import starpost.utils.paths as paths


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    """Point per-user config/cache at a temp dir so tests touch no real files."""
    monkeypatch.setattr(
        paths.platformdirs, "user_config_dir",
        lambda *a, **k: str(tmp_path / "config"),
    )
    monkeypatch.setattr(
        paths.platformdirs, "user_cache_dir",
        lambda *a, **k: str(tmp_path / "cache"),
    )


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_screenplay_tree_reveal_and_accessors(app):
    from PySide6.QtCore import Qt

    from starpost.gui.views.selection_panel import SelectionPanel

    panel = SelectionPanel()
    panel.set_available_screenplays(
        {"Flyby": ["Scalar velocity", "Vector 1"], "Intro": []}
    )
    tree = panel.screenplays
    root = tree.invisibleRootItem()
    flyby = next(
        root.child(i)
        for i in range(root.childCount())
        if root.child(i).text(0) == "Flyby"
    )
    # Checking a screenplay reveals its displayers unchecked.
    flyby.setCheckState(0, Qt.Checked)
    assert panel.selected_screenplays() == {"Flyby"}
    assert panel.selected_screenplay_displayers() == {"Flyby": []}
    flyby.child(0).setCheckState(0, Qt.Checked)
    assert panel.selected_screenplay_displayers() == {
        "Flyby": [flyby.child(0).text(0)]
    }


def test_screenplays_section_visibility(app):
    from starpost.gui.views.selection_panel import SelectionPanel

    panel = SelectionPanel()
    panel.set_active_section("screenplays")
    assert panel._screenplays_group.isVisibleTo(panel)
    assert panel._saved_views_group.isVisibleTo(panel)
    assert not panel._scenes_group.isVisibleTo(panel)
    assert not panel._reports_group.isVisibleTo(panel)
    assert not panel._plots_group.isVisibleTo(panel)
    panel.set_active_section("scenes")
    assert not panel._screenplays_group.isVisibleTo(panel)
    assert panel._scenes_group.isVisibleTo(panel)
    assert panel._saved_views_group.isVisibleTo(panel)


def test_record_and_clear_buttons_emit_signals(app):
    from PySide6.QtWidgets import QPushButton

    from starpost.gui.views.selection_panel import SelectionPanel

    panel = SelectionPanel()
    got = []
    panel.record_screenplays_requested.connect(lambda: got.append("record"))
    panel.clear_screenplays_requested.connect(lambda: got.append("clear"))
    buttons = panel._screenplays_group.findChildren(QPushButton)
    next(b for b in buttons if b.text() == "Record").click()
    next(b for b in buttons if b.text() == "Clear screenplays").click()
    assert got == ["record", "clear"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_screenplays_gui.py -v`
Expected: FAIL with `AttributeError: ... 'set_available_screenplays'`.

- [ ] **Step 3: Implement the panel changes**

In `src/starpost/gui/views/selection_panel.py`:

1. Add after the `_SceneTree` class:

```python
class _ScreenplayTree(_SceneTree):
    """Screenplay picker: identical behaviour to the Scenes tree, over
    ``{screenplay: [displayer, ...]}`` — checking a screenplay reveals its
    scene's displayers unchecked; the checked ones stay visible while
    recording."""

    # The tree logic is inherited wholesale; only the accessor name changes so
    # call sites read correctly.
    checked_screenplays = _SceneTree.checked_scenes
```

2. In `SelectionPanel`, add the signals next to the scene ones:

```python
    record_screenplays_requested = Signal()  # the Screenplays Record button
    clear_screenplays_requested = Signal()   # its "Clear screenplays" button
```

3. In `__init__`, after `self.scenes = _SceneTree()` add:

```python
        # Screenplays: a tree of screenplays (checkable) whose scene's
        # scalar/vector displayers are checkable children; its Record button
        # records the checked screenplays to movies.
        self.screenplays = _ScreenplayTree()
```

   and after `self.scenes.changed.connect(self.selection_changed)`:

```python
        self.screenplays.changed.connect(self.selection_changed)
```

4. **Generalize `_scenes_group_box`** into `_run_group_box` (the scenes and screenplays sections differ only in texts and signals). Replace the whole `_scenes_group_box` method with:

```python
    def _run_group_box(self, title, lst, run_text, run_tip, clear_text,
                       clear_tip, on_run, on_clear) -> QGroupBox:
        """Like ``_group`` but with a prominent action button at the top (Run /
        Record) plus a destructive clear button, emitting the given signals."""
        box = _SortableGroupBox(
            title, on_sort=lambda gp, lst=lst: self._show_sort_menu(lst, gp)
        )
        box.setToolTip("Right-click the title to sort A–Z / Z–A")
        run = QPushButton(run_text)
        run.setToolTip(run_tip)
        run.clicked.connect(lambda: on_run.emit())
        all_on = QPushButton("Select all")
        all_on.setToolTip(f"Select every entry under {title}")
        all_off = QPushButton("Clear")
        all_off.setToolTip(f"Deselect every entry under {title}")
        all_on.clicked.connect(
            lambda: (lst.set_all(True), self.selection_changed.emit())
        )
        all_off.clicked.connect(
            lambda: (lst.set_all(False), self.selection_changed.emit())
        )
        # Destructive: drops the rendered artifacts (not just the selection).
        # Styled red via the shared dangerButton object name.
        clear_rendered = QPushButton(clear_text)
        clear_rendered.setObjectName("dangerButton")
        clear_rendered.setToolTip(clear_tip)
        clear_rendered.clicked.connect(lambda: on_clear.emit())
        row = QHBoxLayout()
        row.addWidget(all_on)
        row.addWidget(all_off)
        row.addWidget(clear_rendered)
        v = QVBoxLayout(box)
        v.addWidget(run)
        v.addLayout(row)
        v.addWidget(lst)
        return box
```

5. In `__init__`, replace the `self._scenes_group = self._scenes_group_box("Scenes", self.scenes)` line with:

```python
        self._scenes_group = self._run_group_box(
            "Scenes", self.scenes,
            run_text="Run",
            run_tip="Render the selected scenes to still images",
            clear_text="Clear scenes",
            clear_tip="Delete all rendered scene stills",
            on_run=self.run_scenes_requested,
            on_clear=self.clear_scenes_requested,
        )
        self._screenplays_group = self._run_group_box(
            "Screenplays", self.screenplays,
            run_text="Record",
            run_tip="Record the selected screenplays to movie files",
            clear_text="Clear screenplays",
            clear_tip="Remove all recorded screenplay movies from the workspace",
            on_run=self.record_screenplays_requested,
            on_clear=self.clear_screenplays_requested,
        )
```

6. In the layout block, add after `layout.addWidget(self._scenes_group, 2)`:

```python
        layout.addWidget(self._screenplays_group, 2)
```

7. Replace `set_active_section` with:

```python
    def set_active_section(self, section: str) -> None:
        """Show the checklist(s) for the active centre tab: ``"reports"`` the
        Reports list, ``"scenes"`` the Scenes tree, ``"screenplays"`` the
        Screenplays tree (each with the shared Saved views list below),
        anything else the Monitor plots list."""
        scenes = section == "scenes"
        screenplays = section == "screenplays"
        self._reports_group.setVisible(section == "reports")
        self._scenes_group.setVisible(scenes)
        self._screenplays_group.setVisible(screenplays)
        self._saved_views_group.setVisible(scenes or screenplays)
        self._plots_group.setVisible(
            section not in ("reports", "scenes", "screenplays")
        )
```

8. Add the accessors after `selected_displayers`:

```python
    def set_available_screenplays(self, groups: dict[str, list[str]]) -> None:
        """Refresh the Screenplays tree from ``{screenplay: [displayer, ...]}``
        while preserving the current selection."""
        self.screenplays.set_items(groups, preserve=True)

    def selected_screenplays(self) -> set[str]:
        """The checked screenplays (tree parents)."""
        return set(self.screenplays.checked_screenplays())

    def selected_screenplay_displayers(self) -> dict[str, list[str]]:
        """The checked displayers per checked screenplay."""
        return self.screenplays.checked_displayers()
```

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_screenplays_gui.py -v`
Expected: PASS. Then confirm no regression in the existing GUI suites (one file at a time):

```bash
QT_QPA_PLATFORM=offscreen timeout 180 python -m pytest tests/test_main_window.py -v
QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_gui_imports.py -v
```

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/gui/views/selection_panel.py tests/test_screenplays_gui.py
git commit -m "Add Screenplays selection tree with Record/Clear controls"
```

---

### Task 7: Shared thumbnail cache + Screenplays gallery

**Files:**
- Create: `src/starpost/gui/views/thumbnails.py`
- Create: `src/starpost/gui/views/screenplay_view.py`
- Modify: `src/starpost/gui/views/scene_view.py`
- Modify: `src/starpost/gui/views/properties_dialog.py`
- Test: `tests/test_screenplays_gui.py`

**Interfaces:**
- Consumes: `MediaArtifact` (`kind`, `poster`, `path`, `error`, `name`, `source`).
- Produces: `ThumbnailCache(edge: int)` with `icon(path: str) -> QIcon | None`; `ScreenplayView` with `clear()` and `show_media(artifacts: list[MediaArtifact])` (filters `kind == "movie"`); `ScenePropertiesDialog(artifact, parent=None, source_label="Report group")` (new keyword, default preserves current UI text).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_screenplays_gui.py`:

```python
def _png(tmp_path, name="poster.png"):
    """A tiny real PNG on disk (galleries decode from disk)."""
    from PySide6.QtGui import QImage

    p = tmp_path / name
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(0xFF336699)
    img.save(str(p))
    return p


def test_thumbnail_cache_decodes_and_misses(app, tmp_path):
    from starpost.gui.views.thumbnails import ThumbnailCache

    cache = ThumbnailCache(64)
    png = _png(tmp_path)
    assert cache.icon(str(png)) is not None
    assert cache.icon(str(tmp_path / "missing.png")) is None


def test_screenplay_view_shows_movie_tiles(app, tmp_path):
    from starpost.data.models import MediaArtifact
    from starpost.gui.views.screenplay_view import ScreenplayView

    poster = _png(tmp_path)
    movie = tmp_path / "a-Flyby.mp4"
    movie.write_bytes(b"stub")
    view = ScreenplayView()
    view.show_media([
        MediaArtifact(name="Flyby", path=str(movie), source="Flyby",
                      kind="movie", poster=str(poster)),
        MediaArtifact(name="Broken", path="", source="Broken", kind="movie",
                      error="ERROR"),
        MediaArtifact(name="Gone", path=str(tmp_path / "gone.mp4"),
                      source="Gone", kind="movie"),
        # Stills are the Scenes gallery's business — ignored here.
        MediaArtifact(name="Still", path=str(poster), source="S",
                      kind="still"),
    ])
    gallery = view._gallery
    labels = [gallery.item(i).text() for i in range(gallery.count())]
    assert labels == ["Flyby", "Broken\n(record failed)", "Gone\n(file missing)"]
    assert not gallery.item(0).icon().isNull()


def test_screenplay_view_empty_shows_hint(app):
    from starpost.gui.views.screenplay_view import ScreenplayView

    view = ScreenplayView()
    view.show_media([])
    assert view._stack.currentWidget() is view._hint
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_screenplays_gui.py -v`
Expected: the three new tests FAIL with `ModuleNotFoundError: ... thumbnails`.

- [ ] **Step 3: Create the shared thumbnail cache**

Create `src/starpost/gui/views/thumbnails.py`:

```python
"""Decode-at-thumbnail-size icon cache shared by the media galleries.

Decoding a (potentially 4K) image straight to thumbnail resolution is cheap;
caching by path + mtime means rebuilding a gallery doesn't re-decode every
image from disk each time.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImageReader, QPixmap


class ThumbnailCache:
    """path -> (mtime, QIcon) cache of thumbnail-sized icons."""

    def __init__(self, edge: int) -> None:
        self._edge = edge
        self._cache: dict[str, tuple[float, QIcon]] = {}

    def icon(self, path: str) -> QIcon | None:
        """A thumbnail-sized QIcon for ``path``, decoded directly at thumbnail
        resolution (cheap for large images) and cached by path + mtime.
        Returns None if the file can't be read."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        cached = self._cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()  # reads the header only — cheap
        if size.isValid() and not size.isEmpty():
            # Decode straight to the thumbnail box (keeping aspect), so a
            # 3840×2160 image isn't fully decoded just to shrink to ~220 px.
            scaled = size.scaled(
                QSize(self._edge, self._edge),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            if not scaled.isEmpty():
                reader.setScaledSize(scaled)
        image = reader.read()
        if image.isNull():
            return None
        icon = QIcon(QPixmap.fromImage(image))
        self._cache[path] = (mtime, icon)
        return icon
```

- [ ] **Step 4: Refactor SceneView onto the cache**

In `src/starpost/gui/views/scene_view.py`:
- Add `from starpost.gui.views.thumbnails import ThumbnailCache`; drop the now-unused `os`, `QImageReader`, `QPixmap` imports (keep the others).
- In `__init__`, replace the `self._thumb_cache ...` assignment (and its comment) with:

```python
        # Shared decode-at-thumbnail-size icon cache (path + mtime keyed).
        self._thumbs = ThumbnailCache(_THUMB)
```

- Delete the `_thumbnail` method entirely.
- In `show_media`, replace `icon = self._thumbnail(art.path)` with `icon = self._thumbs.icon(art.path)`.

- [ ] **Step 5: Create the Screenplays gallery**

Create `src/starpost/gui/views/screenplay_view.py`:

```python
"""Screenplays view (centre tab): a gallery of recorded screenplay movies.

Mirrors the Scenes gallery: one tile per recorded movie, showing its poster
frame with a play badge (or a generic play icon when no poster exists).
Double-clicking a tile opens the movie in the system video player. While
nothing has been recorded it shows a centred hint.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPolygon
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStackedLayout,
    QStyle,
    QWidget,
)

from starpost.data.models import MediaArtifact
from starpost.gui.views.thumbnails import ThumbnailCache
from starpost.gui.widgets import enable_range_selection

_THUMB = 220  # thumbnail edge in px
_ART_ROLE = Qt.ItemDataRole.UserRole + 1  # the MediaArtifact behind a tile


def _play_badge(icon: QIcon, edge: int) -> QIcon:
    """``icon`` with a centred play badge (translucent disc + white triangle),
    so a movie tile reads as playable at a glance."""
    pm = icon.pixmap(QSize(edge, edge))
    if pm.isNull():
        return icon
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = min(pm.width(), pm.height()) // 5
    cx, cy = pm.width() // 2, pm.height() // 2
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 130))
    p.drawEllipse(QPoint(cx, cy), r, r)
    p.setBrush(QColor(255, 255, 255, 230))
    p.drawPolygon(
        QPolygon([
            QPoint(cx - r // 3, cy - r // 2),
            QPoint(cx - r // 3, cy + r // 2),
            QPoint(cx + r // 2, cy),
        ])
    )
    p.end()
    return QIcon(pm)


class _Gallery(QListWidget):
    """Thumbnail list that deselects when empty space is clicked, so the accent
    highlight is removed from any selected tile (default Qt keeps it)."""

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.itemAt(event.position().toPoint()) is None:
            self.clearSelection()
            self.setCurrentItem(None)
        super().mousePressEvent(event)


class ScreenplayView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._hint = QLabel("Select screenplays and press Record to create movies")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setEnabled(False)  # muted, like a placeholder

        self._gallery = _Gallery()
        self._gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self._gallery.setIconSize(QSize(_THUMB, _THUMB))
        self._gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._gallery.setMovement(QListWidget.Movement.Static)
        self._gallery.setSpacing(8)
        self._gallery.setWordWrap(True)
        self._gallery.setUniformItemSizes(True)
        enable_range_selection(self._gallery)  # Shift/Ctrl+click multi-select
        self._gallery.itemDoubleClicked.connect(self._open_item)
        self._gallery.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._gallery.customContextMenuRequested.connect(self._show_context_menu)

        self._stack = QStackedLayout(self)
        self._stack.addWidget(self._hint)
        self._stack.addWidget(self._gallery)
        self._stack.setCurrentWidget(self._hint)

        # Shared decode-at-thumbnail-size icon cache for the poster frames.
        self._thumbs = ThumbnailCache(_THUMB)

    def clear(self) -> None:
        self._gallery.clear()
        self._stack.setCurrentWidget(self._hint)

    def show_media(self, artifacts: list[MediaArtifact]) -> None:
        """Show one tile per movie in ``artifacts`` (errored or missing files
        are listed without a poster). Falls back to the hint when empty."""
        self._gallery.clear()
        movies = [a for a in artifacts if a.kind == "movie"]
        if not movies:
            self._stack.setCurrentWidget(self._hint)
            return

        for art in movies:
            label = art.name or Path(art.path).stem
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, art.path)
            item.setData(_ART_ROLE, art)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            if art.error:
                item.setText(f"{label}\n(record failed)")
            elif art.path and Path(art.path).exists():
                icon = self._thumbs.icon(art.poster) if art.poster else None
                if icon is not None:
                    item.setIcon(_play_badge(icon, _THUMB))
                else:
                    # No poster: a generic play icon still marks it a movie.
                    item.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
                item.setToolTip(art.path)
            else:
                item.setText(f"{label}\n(file missing)")
            self._gallery.addItem(item)

        self._stack.setCurrentWidget(self._gallery)

    def _open_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _show_context_menu(self, pos) -> None:
        """Right-clicking a tile offers Properties for that recorded movie."""
        item = self._gallery.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        properties = menu.addAction("Properties")
        chosen = menu.exec(self._gallery.viewport().mapToGlobal(pos))
        if chosen is properties:
            from starpost.gui.views.properties_dialog import (
                ScenePropertiesDialog,
            )

            art = item.data(_ART_ROLE)
            if art is not None:
                ScenePropertiesDialog(
                    art, self, source_label="Screenplay"
                ).exec()
```

- [ ] **Step 6: Parameterize the properties dialog's source label**

In `src/starpost/gui/views/properties_dialog.py`, `ScenePropertiesDialog`:
- Change the signature to:

```python
    def __init__(self, artifact, parent=None, source_label: str = "Report group") -> None:
```

  (the default preserves the Scenes gallery's current row label verbatim).
- Change the row `form.addRow("Report group:", QLabel(scene))` to:

```python
        form.addRow(f"{source_label}:", QLabel(scene))
```

- [ ] **Step 7: Run the tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_screenplays_gui.py -v
QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_gui_imports.py -v
```

Expected: all PASS (gui-imports catches any broken import in the refactored scene_view).

- [ ] **Step 8: Lint and commit**

```bash
ruff check .
git add src/starpost/gui/views/thumbnails.py src/starpost/gui/views/screenplay_view.py src/starpost/gui/views/scene_view.py src/starpost/gui/views/properties_dialog.py tests/test_screenplays_gui.py
git commit -m "Add Screenplays gallery with poster play badges; share thumbnail cache"
```

---

### Task 8: Main window wiring — tab, record flow, kind-aware clears

**Files:**
- Modify: `src/starpost/gui/main_window.py`
- Test: `tests/test_screenplays_gui.py`

**Interfaces:**
- Consumes: `ScreenplayView` (Task 7), `ScreenplayRecordWorker` (Task 5), `SelectionPanel` screenplay API (Task 6), `media.screenplays_per_checkout` (Task 3).
- Produces: a "Screenplays" centre tab; `_record_screenplays()` / `_start_record()` / `_on_screenplays_recorded()` / `_on_record_finished()` / `_clear_screenplays()` / `_record_busy()` / `_maybe_warn_screenplays()` / `_render_screenplays_view()`; kind-aware media replacement and clearing (Clear scenes no longer wipes movies).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_screenplays_gui.py`:

```python
def test_main_window_has_screenplays_tab(app):
    import starpost.gui.main_window as mw
    from starpost.core.settings import Settings

    win = mw.MainWindow(Settings())
    tabs = win._center_tabs
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert labels == ["Reports", "Plots", "Scenes", "Screenplays"]
    win.close()


def test_clear_scenes_keeps_movies_and_vice_versa(app, monkeypatch, tmp_path):
    import starpost.gui.main_window as mw
    from starpost.core.settings import Settings
    from starpost.data.models import MediaArtifact, SimResult

    win = mw.MainWindow(Settings())
    res = SimResult(sim_path=str(tmp_path / "a.sim"))
    res.media = [
        MediaArtifact(name="s", path="", source="S", kind="still"),
        MediaArtifact(name="m", path="", source="P", kind="movie"),
    ]
    win.store.put(res)
    monkeypatch.setattr(
        mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.Yes
    )
    win._clear_scenes()
    assert [m.kind for m in win.store.get(res.sim_path).media] == ["movie"]
    win._clear_screenplays()
    assert win.store.get(res.sim_path).media == []
    win.close()


def test_record_screenplays_requires_selection(app, monkeypatch):
    import starpost.gui.main_window as mw
    from starpost.core.settings import Settings

    win = mw.MainWindow(Settings(starccm_path="/bin/true"))
    infos = []
    monkeypatch.setattr(
        mw.QMessageBox, "information", lambda *a, **k: infos.append(a[2])
    )
    win._record_screenplays()
    assert infos and "screenplay" in infos[0].lower()
    win.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen timeout 180 python -m pytest tests/test_screenplays_gui.py -v`
Expected: the three new tests FAIL (tab labels lack "Screenplays"; `_clear_screenplays` / `_record_screenplays` missing).

- [ ] **Step 3: Implement the main-window changes**

In `src/starpost/gui/main_window.py`:

1. Imports: extend the queue import to `from starpost.batch.queue import BatchWorker, SceneRenderWorker, ScreenplayRecordWorker` and add `from starpost.gui.views.screenplay_view import ScreenplayView` next to the scene_view import.

2. `__init__` state, next to the render-thread fields:

```python
        # Separate thread/worker for on-demand screenplay recording
        # (Screenplays tab → Record). Mirrors the scene render pair above.
        self._record_thread: QThread | None = None
        self._record_worker: ScreenplayRecordWorker | None = None
        # Whether the Screenplays "recording is expensive" warning has shown
        # this session, and the movie paths last drawn in its gallery.
        self._screenplays_warning_shown = False
        self._screenplay_gallery_paths: list[str] | None = None
```

3. `__init__` widgets, after `self.scene_view = SceneView()`:

```python
        self.screenplay_view = ScreenplayView()
```

4. `__init__` signal wiring, after the scene connections:

```python
        self.selection.record_screenplays_requested.connect(
            self._record_screenplays
        )
        self.selection.clear_screenplays_requested.connect(
            self._clear_screenplays
        )
```

5. In `_build_layout` (where tabs are added), after `tabs.addTab(self.scene_view, "Scenes")`:

```python
        tabs.addTab(self.screenplay_view, "Screenplays")
```

6. `_on_center_tab_changed`: add the branch and follow-up —

```python
        elif widget is self.scene_view:
            section = "scenes"
        elif widget is self.screenplay_view:
            section = "screenplays"
```

   and after the `if section == "scenes":` block:

```python
        elif section == "screenplays":
            # Build the gallery now that it's visible (deferred while hidden).
            self._render_screenplays_view()
            self._maybe_warn_screenplays()
```

7. Add after `_maybe_warn_scenes` (same checkbox/save tail as that method):

```python
    def _maybe_warn_screenplays(self) -> None:
        """First time the Screenplays tab is opened this session, warn that
        recording is heavy. Shares the scenes warning's "do not show again"
        setting — both gate the same expensive rendering path."""
        if (
            self._screenplays_warning_shown
            or not self.settings.show_scenes_warning
        ):
            return
        self._screenplays_warning_shown = True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Screenplays")
        box.setText(
            "Recording screenplays is very computationally expensive — a "
            "movie takes far longer than a still image.\n\n"
            "It is not recommended on systems with less than 16 GB of system "
            "memory. Closing other programs on your computer first is "
            "recommended to prevent memory related errors."
        )
        box.setStandardButtons(QMessageBox.Ok)
        box.button(QMessageBox.Ok).setIcon(
            self.style().standardIcon(QStyle.SP_DialogYesButton)
        )
        dont_show = QCheckBox("Do not show this again")
        box.setCheckBox(dont_show)
        box.exec()
        if dont_show.isChecked():
            self.settings.show_scenes_warning = False
            self.settings.save()
```

8. Add next to `_render_busy`:

```python
    def _record_busy(self) -> bool:
        return self._record_thread is not None and self._record_thread.isRunning()
```

   and update `_run_scenes`'s opening guard to `if self._busy() or self._render_busy() or self._record_busy():`.

9. Add after `_on_render_finished` (mirrors `_run_scenes`/`_start_render`):

```python
    def _record_screenplays(self) -> None:
        """Screenplays tab → Record: record the ticked screenplays of the
        ticked data set to movies. Independent of the numeric batch, of Run
        batch, and of scene rendering."""
        if self._busy() or self._render_busy() or self._record_busy():
            QMessageBox.information(
                self, "StarPost", "A run is already in progress."
            )
            return
        if self._missing_exe():
            return
        screenplays = self.selection.selected_screenplays()
        if not screenplays:
            QMessageBox.information(
                self, "Screenplays",
                "Select at least one screenplay to record.",
            )
            return
        # Record one data set at a time: recording is heavy and the output is
        # per-.sim (same rule as scene rendering).
        results = self._active_results()
        if not results:
            QMessageBox.information(
                self, "Screenplays", "Tick a data set in the Data tab first."
            )
            return
        if len(results) > 1:
            QMessageBox.warning(
                self, "Screenplays",
                "Select only one data set to record. Untick the others in "
                "the Data tab, then press Record.",
            )
            return

        result = results[0]
        sim_file = Path(result.sim_path)
        if not sim_file.exists():
            QMessageBox.warning(
                self, "Screenplays",
                f"The .sim file for “{result.sim_name}” could not be found:\n"
                f"{result.sim_path}",
            )
            return
        available = result.screenplay_names()
        wanted = sorted(s for s in screenplays if s in available)
        if not wanted:
            QMessageBox.information(
                self, "Screenplays",
                "None of the selected screenplays are available in the "
                "ticked data set.",
            )
            return
        # Each screenplay maps to the displayers to keep visible.
        show_sel = self.selection.selected_screenplay_displayers()
        screenplay_show = {s: list(show_sel.get(s, [])) for s in wanted}
        # Chunk into checkouts of the configured size: each chunk is one
        # starccm+ session (one license, sim loaded once).
        per = max(1, self.settings.media.screenplays_per_checkout)
        items = list(screenplay_show.items())
        jobs: list[tuple[Path, dict[str, list[str]]]] = [
            (sim_file, dict(items[i:i + per]))
            for i in range(0, len(items), per)
        ]
        # Saved views: one movie per screenplay × view (empty == its camera).
        views = sorted(self.selection.selected_views())
        out_dir = (
            Path(self.settings.default_output_dir)
            if self.settings.default_output_dir
            else sim_file.parent
        )
        self._start_record(jobs, out_dir, views)

    def _start_record(
        self,
        jobs: list[tuple[Path, dict[str, list[str]]]],
        out_dir: Path,
        views: list[str],
    ) -> None:
        runner = StarRunner(self.settings)
        self._record_thread = QThread()
        self._record_worker = ScreenplayRecordWorker(
            jobs, runner, out_dir, views
        )
        self._record_worker.moveToThread(self._record_thread)

        self._record_thread.started.connect(self._record_worker.run)
        self._record_worker.log.connect(self.log_console.append)
        self._record_worker.progress.connect(self.log_console.set_progress)
        self._record_worker.recorded.connect(self._on_screenplays_recorded)
        self._record_worker.finished.connect(self._on_record_finished)
        self._record_worker.finished.connect(self._record_thread.quit)

        self.log_console.clear()
        # All of a chunk's screenplays record in one checkout, so progress is
        # per chunk (the macro streams per-screenplay progress to the log).
        self.log_console.start_progress(len(jobs))
        # Switch to the Screenplays tab so the gallery is in view when the
        # movies land.
        self._center_tabs.setCurrentWidget(self.screenplay_view)
        self._record_thread.start()

    def _on_screenplays_recorded(self, sim_path, artifacts) -> None:
        """A file's movies finished: attach them to its result (replacing any
        prior movies of the same screenplays; stills untouched) and persist."""
        target = Path(sim_path).resolve()
        res = next(
            (
                r for r in self.store.all()
                if Path(r.sim_path).resolve() == target
            ),
            None,
        )
        if res is None:
            return
        recorded_sources = {a.source for a in artifacts}
        res.media = [
            m for m in res.media
            if not (m.kind == "movie" and m.source in recorded_sources)
        ] + list(artifacts)
        self.store.put(res)
        self.store.save_cache_async()  # off the GUI thread; runs on it here

    def _on_record_finished(self) -> None:
        self.log_console.finish_progress()
        # New movies may reuse existing file names (same paths), so force the
        # gallery to rebuild — the poster cache reloads any changed images.
        self._screenplay_gallery_paths = None
        self._refresh_from_store()

    def _clear_screenplays(self) -> None:
        """Screenplays tab → "Clear screenplays": drop every recorded movie
        from the workspace after confirming. The movie/poster files on disk
        are left in place (matching "Clear scenes")."""
        if self._record_busy():
            QMessageBox.information(
                self, "Clear screenplays",
                "Screenplays are still recording. Wait for the run to finish "
                "first.",
            )
            return
        if not any(
            m.kind == "movie" for r in self.store.all() for m in r.media
        ):
            QMessageBox.information(
                self, "Clear screenplays",
                "There are no recorded screenplays to clear.",
            )
            return
        if QMessageBox.question(
            self, "Clear screenplays",
            "Clear all recorded screenplays? This removes every recorded "
            "movie from the workspace (the files already saved on disk are "
            "kept).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        for r in self.store.all():
            if any(m.kind == "movie" for m in r.media):
                r.media = [m for m in r.media if m.kind != "movie"]
                self.store.put(r)
        # Persist so the cleared state survives restart (async: no GUI freeze).
        self.store.save_cache_async()
        self._refresh_from_store()
```

10. **Make the existing scene paths kind-aware:**
    - `_on_scenes_rendered`: change the replacement filter to

```python
        res.media = [
            m for m in res.media
            if not (m.kind == "still" and m.source in rendered_sources)
        ] + list(artifacts)
```

    - `_clear_scenes`: change the emptiness check to `if not any(m.kind == "still" for r in self.store.all() for m in r.media):` and the clearing loop to

```python
        for r in self.store.all():
            if any(m.kind == "still" for m in r.media):
                r.media = [m for m in r.media if m.kind != "still"]
                self.store.put(r)
```

11. **Populate the Screenplays tree** — in `_refresh_scene_choices`, after the scenes loop (before `set_available_scenes`), add:

```python
        screenplay_groups: dict[str, list[str]] = {}
        for r in results:
            for sp in r.screenplays:
                names = screenplay_groups.setdefault(sp.name, [])
                for d in sp.displayers:
                    if d.name not in names:
                        names.append(d.name)
```

    and after `self.selection.set_available_scenes(scene_groups)`:

```python
        self.selection.set_available_screenplays(screenplay_groups)
```

12. **Gallery refresh** — in `_refresh_views`, after `self._render_scenes_view()` add `self._render_screenplays_view()`, and add the method next to `_render_scenes_view`:

```python
    def _render_screenplays_view(self) -> None:
        """Rebuild the recorded-movies gallery — but only when the Screenplays
        tab is showing and the set of movies actually changed (same deferral
        pattern as the scene gallery)."""
        if self._center_tabs.currentWidget() is not self.screenplay_view:
            self._screenplay_gallery_paths = None  # stale; rebuilt on switch
            return
        media = []
        for r in self._active_results():
            for m in r.media:
                if m.kind != "movie":
                    continue
                m.sim_path = r.sim_path  # provenance for Properties
                media.append(m)
        paths = [m.path for m in media]
        if paths == self._screenplay_gallery_paths:
            return  # unchanged — keep the gallery (and its poster thumbnails)
        self._screenplay_gallery_paths = paths
        if media:
            self.screenplay_view.show_media(media)
        else:
            self.screenplay_view.clear()
```

- [ ] **Step 4: Run the tests**

```bash
QT_QPA_PLATFORM=offscreen timeout 180 python -m pytest tests/test_screenplays_gui.py -v
QT_QPA_PLATFORM=offscreen timeout 180 python -m pytest tests/test_main_window.py -v
```

Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/gui/main_window.py tests/test_screenplays_gui.py
git commit -m "Add Screenplays centre tab with record flow and kind-aware clears"
```

---

### Task 9: Settings dialog — Screenplays page

**Files:**
- Modify: `src/starpost/gui/views/settings_dialog.py`
- Test: `tests/test_screenplays_gui.py`

**Interfaces:**
- Consumes: `MediaConfig.movie_*` / `screenplays_per_checkout` (Task 3).
- Produces: a "Screenplays" settings page (after "Scenes") whose controls load from and save to `Settings.media`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_screenplays_gui.py`:

```python
def test_settings_dialog_screenplays_page_round_trip(app):
    from starpost.core.settings import Settings
    from starpost.gui.views.settings_dialog import SettingsDialog

    s = Settings()
    s.media.movie_format = "mov"
    s.media.movie_fps = 24
    s.media.movie_resolution = "2160p"
    s.media.movie_quality = "low"
    s.media.screenplays_per_checkout = 2
    dlg = SettingsDialog(s)
    assert dlg._movie_format.currentData() == "mov"
    assert dlg._movie_fps.value() == 24
    assert dlg._movie_resolution.currentData() == "2160p"
    assert dlg._movie_quality.currentData() == "low"
    assert dlg._screenplays_per_checkout.value() == 2
    # Change in the UI and accept: _on_accept copies widget values back onto
    # the Settings object (and saves — redirected by isolated_paths).
    dlg._movie_format.setCurrentIndex(dlg._movie_format.findData("mp4"))
    dlg._movie_fps.setValue(60)
    dlg._on_accept()
    assert s.media.movie_format == "mp4"
    assert s.media.movie_fps == 60
```

(`SettingsDialog(settings: Settings, parent=None)` stores the object as `self._settings`; `_load_from_settings` fills the widgets and `_on_accept` writes them back and saves.)

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_screenplays_gui.py -v`
Expected: the new test FAILS with `AttributeError: ... '_movie_format'`.

- [ ] **Step 3: Implement the page**

In `src/starpost/gui/views/settings_dialog.py`:

1. Register the page after the Scenes one:

```python
        self._add_page("Screenplays", self._build_screenplays_page())
```

2. Add after `_build_scenes_page`:

```python
    def _build_screenplays_page(self) -> QWidget:
        # Recording resolution for screenplay movies.
        self._movie_resolution = QComboBox()
        self._movie_resolution.addItem("1080p", "1080p")
        self._movie_resolution.addItem("2160p", "2160p")

        # Movie container (the file extension STAR-CCM+ uses to pick the
        # encoder).
        self._movie_format = QComboBox()
        self._movie_format.addItem("MP4", "mp4")
        self._movie_format.addItem("AVI", "avi")
        self._movie_format.addItem("MOV", "mov")

        self._movie_fps = QSpinBox()
        self._movie_fps.setRange(1, 240)
        self._movie_fps.setFixedWidth(140)

        self._movie_quality = QComboBox()
        self._movie_quality.addItem("Low", "low")
        self._movie_quality.addItem("Medium", "medium")
        self._movie_quality.addItem("High", "high")

        # Screenplays recorded per license checkout (one starccm+ session).
        self._screenplays_per_checkout = QSpinBox()
        self._screenplays_per_checkout.setRange(1, 999)
        self._screenplays_per_checkout.setFixedWidth(140)

        form = QFormLayout()
        form.addRow("Movie resolution", self._movie_resolution)
        form.addRow("Movie format", self._movie_format)
        form.addRow("Frame rate (fps)", self._movie_fps)
        form.addRow("Quality", self._movie_quality)
        hint = QLabel(
            "Resolution, container, frame rate and encoder quality of the "
            "movies recorded in the Screenplays tab."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        form.addRow("Screenplays per license", self._screenplays_per_checkout)
        spc_hint = QLabel(
            "How many screenplays to record per license checkout (one "
            "STAR-CCM+ session, the sim loaded once). 1 records each in its "
            "own checkout (safest for memory); higher values batch more per "
            "checkout to cut license churn and reloads."
        )
        spc_hint.setObjectName("hint")
        spc_hint.setWordWrap(True)
        form.addRow("", spc_hint)
        return self._wrap(form)
```

3. In `_load_from_settings`, next to the existing `self._image_resolution` block (~line 1456):

```python
        midx = self._movie_format.findData(s.media.movie_format)
        self._movie_format.setCurrentIndex(midx if midx >= 0 else 0)
        mridx = self._movie_resolution.findData(s.media.movie_resolution)
        self._movie_resolution.setCurrentIndex(mridx if mridx >= 0 else 0)
        self._movie_fps.setValue(s.media.movie_fps)
        mqidx = self._movie_quality.findData(s.media.movie_quality)
        self._movie_quality.setCurrentIndex(mqidx if mqidx >= 0 else 2)
        self._screenplays_per_checkout.setValue(
            s.media.screenplays_per_checkout
        )
```

4. In `_on_accept`, after the `s.media.image_resolution = ...` line (~line 1574):

```python
        s.media.movie_format = self._movie_format.currentData()
        s.media.movie_resolution = self._movie_resolution.currentData()
        s.media.movie_fps = self._movie_fps.value()
        s.media.movie_quality = self._movie_quality.currentData()
        s.media.screenplays_per_checkout = (
            self._screenplays_per_checkout.value()
        )
```

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_screenplays_gui.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check .
git add src/starpost/gui/views/settings_dialog.py tests/test_screenplays_gui.py
git commit -m "Add Settings → Screenplays page for movie recording options"
```

---

### Task 10: Docs, changelog, version bump

**Files:**
- Modify: `src/starpost/__init__.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/StarPost_Documentation.md`
- Modify: `docs/screenplay_plan.md`

- [ ] **Step 1: Bump the version**

In `src/starpost/__init__.py`: `__version__ = "2.3.0"`.

- [ ] **Step 2: Add the changelog entry**

At the top of `CHANGELOG.md` (above `## [2.2.0]`), matching the existing style:

```markdown
## [2.3.0] — <today's date>

### New Features
- **Screenplays tab** — a new centre tab (after Scenes) that records STAR-CCM+
  screenplays to movie files. Screenplays are discovered during normal
  extraction (no extra license checkout); the selection panel's Screenplays
  tree mirrors the Scenes tree (checkable screenplays with their scene's
  scalar/vector displayers), and the shared **Saved views** list records one
  movie per screenplay × view. **Record** runs off the GUI thread, one license
  checkout at a time. Gallery tiles show a poster frame with a play badge;
  double-clicking opens the movie in the system video player.
- **Settings → Screenplays** — movie resolution (1080p/2160p), container
  (MP4/AVI/MOV), frame rate, encoder quality, and screenplays-per-license
  checkout batching.
```

- [ ] **Step 3: Update the reference documentation**

In `docs/StarPost_Documentation.md`: locate the Scenes tab reference section and add a parallel **Screenplays tab** section after it covering: what the tab shows (recorded movie gallery, poster + play badge, double-click opens the system player, right-click → Properties); the selection panel (Screenplays tree with displayer children, shared Saved views list, Record/Clear screenplays buttons); the one-data-set rule; output naming (`<dataset>-<screenplay>[-<displayers>][-<view>].<ext>` + `_poster.png`); the Settings → Screenplays options; and a note that screenplay recording requires STAR-CCM+ 2022 or newer (older releases simply list no screenplays). Update the document's TOC and any "numeric data only"/limitations wording that still excludes video. Bump the doc's last-updated date.

- [ ] **Step 4: Mark the old plan superseded**

At the top of `docs/screenplay_plan.md` (below the existing status blockquote), add:

```markdown
> **Update (2026-07-06):** Phase 2 (saved views) shipped earlier; Phase 3
> (screenplays) is now implemented — see
> `docs/superpowers/specs/2026-07-06-screenplays-tab-design.md`. The
> snippet-injection approach described below was superseded by a
> reflection-based turnkey record macro (no user paste-in).
```

- [ ] **Step 5: Full test suite, lint, commit**

```bash
python -m pytest tests/ --ignore=tests/test_main_window.py --ignore=tests/test_screenplays.py --ignore=tests/test_screenplays_gui.py --ignore=tests/test_gui_imports.py --ignore=tests/test_plot_view.py --ignore=tests/test_export_dialog.py --ignore=tests/test_widgets.py --ignore=tests/test_theme.py --ignore=tests/test_text_scale.py -v
QT_QPA_PLATFORM=offscreen timeout 180 python -m pytest tests/test_main_window.py -v
QT_QPA_PLATFORM=offscreen timeout 180 python -m pytest tests/test_screenplays.py -v
QT_QPA_PLATFORM=offscreen timeout 180 python -m pytest tests/test_screenplays_gui.py -v
QT_QPA_PLATFORM=offscreen timeout 120 python -m pytest tests/test_gui_imports.py -v
ruff check .
git add src/starpost/__init__.py CHANGELOG.md docs/StarPost_Documentation.md docs/screenplay_plan.md
git commit -m "Docs: Screenplays tab reference, changelog; version 2.3.0"
```

(If any other GUI test file was touched by review feedback, run it the same offscreen/serialized way.)

---

### Task 11: Manual verification against a real STAR-CCM+ install

This cannot be automated (needs a license, a GPU, and a solved `.sim` with at least one screenplay). Requires the user's machine — coordinate with them.

- [ ] **Step 1: Extraction discovery**

Load a `.sim` containing screenplays through the normal Files → run flow. Verify `<simname>__screenplays_index.csv` appears in the output folder and the Screenplays tab's tree lists each screenplay with its scene's displayers. On a pre-2022 release (if available), verify extraction still completes and the log shows `starpost: no screenplays found (...)`.

- [ ] **Step 2: Recording**

Tick one screenplay (and one displayer), tick one saved view, press **Record**. Verify: one `<dataset>-<screenplay>-<displayer>-<view>.mp4` and matching `_poster.png` in the output folder; the gallery tile shows the poster with a play badge; double-click opens the movie; Properties shows Screenplay/displayers/view. Then record with **no** view ticked and verify the movie uses the screenplay's own camera and the tile name has no view suffix.

- [ ] **Step 3: Reflection diagnostics**

If recording fails, capture the log line `no usable record/export method found on <class>; candidates tried: ...` — it lists the release's actual method signatures. Adjust `invokeRecord`/`fillArgs` (and possibly the manager class name in `screenplays(sim)`) in **both** `record_screenplays.java.j2` and (manager lookup only) `extract_all.java.j2` to match, update the template tests, and re-verify.

- [ ] **Step 4: Guards and clears**

While a recording runs: pressing Record again or Run (scenes) shows "A run is already in progress."; Clear screenplays is refused. After it finishes: Clear scenes leaves movies in the gallery; Clear screenplays leaves stills; both survive an app restart (cache round-trip).

- [ ] **Step 5: Commit any macro adjustments**

```bash
git add -A src/starpost/macros tests/
git commit -m "Adjust screenplay reflection to verified STAR-CCM+ API"
```
