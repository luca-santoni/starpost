# Screenplay Animation Length & Start Time Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user set the Animation Length (0 = Auto) and Start Time (plain seconds, default 0) of recorded screenplay movies — in Settings → Screenplays, in the run-batch window's screenplay options, and captured per saved screenplay.

**Architecture:** Two new `MediaConfig` fields thread down the exact pipeline `movie_fps` already uses: Settings YAML → Settings dialog page → `StarRunner.record_screenplays` → `record_screenplays_macro` → constants in the Java macro template. The batch dialog mirrors the fields, `_capture_screenplay` snapshots them, and `_screenplay_runner` applies them per saved entry with key-presence (not truthiness) semantics.

**Tech Stack:** Python 3.11, PySide6, Jinja2 (Java macro template), pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-screenplay-animation-length-design.md`
(note: the spec says `MediaSettings`; the real class is `MediaConfig` in
`src/starpost/core/settings.py`).

## Global Constraints

- `movie_anim_length: float = 0.0` — **0 = Auto** (use each screenplay's own preferred length); > 0 forces that duration (seconds) for every screenplay.
- `movie_start_time: float = 0.0` — plain seconds, **no Auto state**; recordings always start here. The macro's `getPreferredStartTime` probes are removed.
- Both clamped to ≥ 0 when read from YAML.
- Saved-screenplay entries override with **key presence**: `"anim_length"`/`"start_time"` present → use the captured value (including explicit 0); absent (older profile) → global setting.
- Run single test files with `python -m pytest tests/<file>.py -v`; run the full suite only via `python scripts/run_tests.py`. GUI tests on a headless machine need `QT_QPA_PLATFORM=offscreen`.
- Commit after every task. Log the user-facing change in `CHANGELOG.md` (newest-first style, under `## [Unreleased]`).
- Line length 100 (`ruff check .` must stay clean).

---

### Task 1: MediaConfig fields + YAML round-trip

**Files:**
- Modify: `src/starpost/core/settings.py` (dataclass ~line 123-128, `from_dict` ~line 270-290, `to_dict` ~line 340-352)
- Modify: `config/default_settings.yaml` (~line 26-30, media block)
- Test: `tests/test_screenplays.py` (extend the three `test_media_config_movie_*` tests, ~line 136-182)

**Interfaces:**
- Produces: `MediaConfig.movie_anim_length: float` (default 0.0) and `MediaConfig.movie_start_time: float` (default 0.0), round-tripped through `Settings.from_dict` / `Settings.to_dict` under `media.movie_anim_length` / `media.movie_start_time`. All later tasks read these two attributes.

- [ ] **Step 1: Extend the failing tests**

In `tests/test_screenplays.py`, add to `test_media_config_movie_defaults` (after the `screenplays_per_checkout` assert):

```python
    assert m.movie_anim_length == 0.0   # 0 == Auto (screenplay's own length)
    assert m.movie_start_time == 0.0
```

Add to the `Settings.from_dict({...})` dict in `test_media_config_movie_round_trip`:

```python
        "movie_anim_length": 12.5,
        "movie_start_time": 2.0,
```

and the corresponding asserts (both on `s.media.*` and on `out`):

```python
    assert s.media.movie_anim_length == 12.5
    assert s.media.movie_start_time == 2.0
```
```python
    assert out["movie_anim_length"] == 12.5
    assert out["movie_start_time"] == 2.0
```

Add to the dict in `test_media_config_movie_values_clamped`:

```python
        "movie_anim_length": -5,
        "movie_start_time": -1,
```

and the asserts:

```python
    assert s.media.movie_anim_length == 0.0
    assert s.media.movie_start_time == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_screenplays.py -v -k media_config`
Expected: 3 FAIL — `AttributeError: ... no attribute 'movie_anim_length'` / KeyError.

- [ ] **Step 3: Implement**

In `src/starpost/core/settings.py`, after `screenplays_per_checkout: int = 1` in `MediaConfig`:

```python
    movie_anim_length: float = 0.0   # seconds; 0 == each screenplay's own length
    movie_start_time: float = 0.0    # seconds into the animation to start recording
```

Extend the `MediaConfig` docstring's screenplay-recording sentence to mention the two
new knobs, e.g. append: ```movie_anim_length`` (recording duration in seconds; 0 records
each screenplay at its own preferred length) and ``movie_start_time`` (seconds into the
animation to start recording).`

In `Settings.from_dict`, after the `screenplays_per_checkout=` line inside the
`MediaConfig(...)` construction:

```python
                movie_anim_length=max(
                    0.0, float(med.get("movie_anim_length", 0.0))
                ),
                movie_start_time=max(
                    0.0, float(med.get("movie_start_time", 0.0))
                ),
```

In `Settings.to_dict`, after `"screenplays_per_checkout": ...` in the `"media"` dict:

```python
                "movie_anim_length": self.media.movie_anim_length,
                "movie_start_time": self.media.movie_start_time,
```

In `config/default_settings.yaml`, after `screenplays_per_checkout: 1  # ...`:

```yaml
  movie_anim_length: 0.0     # recording length in seconds; 0 = each screenplay's own
  movie_start_time: 0.0      # seconds into the animation to start recording
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_screenplays.py -v` then `ruff check .`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/core/settings.py config/default_settings.yaml tests/test_screenplays.py
git commit -m "Add movie_anim_length and movie_start_time media settings"
```

---

### Task 2: Macro template constants + generator + runner pass-through

**Files:**
- Modify: `src/starpost/macros/record_screenplays.java.j2` (constants ~line 36; `recordKnown` ~line 306-317; `recordFrameLoop` ~line 381-427)
- Modify: `src/starpost/core/macro_generator.py` (`record_screenplays_macro`, ~line 117-152)
- Modify: `src/starpost/core/starccm_runner.py` (`record_screenplays` macro call, ~line 250-260)
- Test: `tests/test_screenplays.py`

**Interfaces:**
- Consumes: `MediaConfig.movie_anim_length` / `movie_start_time` (Task 1).
- Produces: `record_screenplays_macro(..., movie_format="mp4", quality="high", anim_length: float = 0.0, start_time: float = 0.0)` — two new trailing keyword parameters; the rendered macro contains `ANIM_LENGTH` and `START_TIME` `double` constants.

- [ ] **Step 1: Write the failing tests**

In `tests/test_screenplays.py`, add to `test_record_screenplays_macro_embeds_selection_and_movie_settings` — first extend the existing call with the two new arguments (after `"medium",`):

```python
            anim_length=8.5,
            start_time=1.5,
```

then add asserts (next to the `FPS = 24` assert):

```python
        assert "ANIM_LENGTH = 8.5" in text
        assert "START_TIME = 1.5" in text
        # Start time is fully user-controlled now; the preferred-start-time
        # probe is gone from both export paths.
        assert "getPreferredStartTime" not in text
```

Add a new test after it:

```python
def test_record_screenplays_macro_timing_defaults_to_auto():
    """Default render: ANIM_LENGTH 0 (== Auto, probe each screenplay's own
    length) and START_TIME 0."""
    with tempfile.TemporaryDirectory() as d:
        path = record_screenplays_macro(
            Path("/out"), Path(d), {"Fly": []}, [], 1920, 1080, 30
        )
        text = path.read_text()
        assert "ANIM_LENGTH = 0.0" in text
        assert "START_TIME = 0.0" in text
        # Auto still probes the screenplay's own length.
        assert "probeLength" in text
        assert "getPreferredAnimationLength" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_screenplays.py -v -k record_screenplays_macro`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'anim_length'`.

- [ ] **Step 3: Implement the generator**

In `src/starpost/core/macro_generator.py`, change `record_screenplays_macro`'s signature:

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
    anim_length: float = 0.0,
    start_time: float = 0.0,
) -> Path:
```

Extend its docstring with: `` `anim_length` is the recording length in seconds (0 ==
record each screenplay at its own preferred length); ``start_time`` is the offset in
seconds the recording starts from.``

Add to the `.render(...)` kwargs:

```python
        anim_length=float(anim_length),
        start_time=float(start_time),
```

- [ ] **Step 4: Implement the template**

In `src/starpost/macros/record_screenplays.java.j2`:

**(a)** After `private static final int FPS = {{ fps }};` add:

```java
    // Recording length in seconds; <= 0 == each screenplay's own length.
    private static final double ANIM_LENGTH = {{ anim_length }};
    // Seconds into the animation the recording starts from.
    private static final double START_TIME = {{ start_time }};
```

**(b)** In `recordKnown`, replace:

```java
        double length = probeLength(sim, targets);
        if (length <= 0) {
            tried.append("\n  [known-signature path skipped: no animation "
                + "length getter found]");
            return false;
        }
        double start = 0.0;
        Object st = invokeQuiet(sp, "getPreferredStartTime");
        if (st instanceof Number) {
            start = ((Number) st).doubleValue();
        }
```

with:

```java
        double length = ANIM_LENGTH > 0 ? ANIM_LENGTH
            : probeLength(sim, targets);
        if (length <= 0) {
            tried.append("\n  [known-signature path skipped: no animation "
                + "length getter found]");
            return false;
        }
        double start = START_TIME;
```

**(c)** In `recordFrameLoop`, replace:

```java
        Object director = invokeQuiet(sp, "getScreenplayDirector");
        Object st = invokeQuiet(sp, "getPreferredStartTime");
        Object len = invokeQuiet(sp, "getPreferredAnimationLength");
        if (director == null || !(st instanceof Number)
                || !(len instanceof Number)
                || ((Number) len).doubleValue() <= 0) {
            tried.append("\n  [frame-loop skipped: director/start/length "
                + "unavailable]");
            return false;
        }
        double start = ((Number) st).doubleValue();
        double length = ((Number) len).doubleValue();
```

with:

```java
        Object director = invokeQuiet(sp, "getScreenplayDirector");
        Object len = invokeQuiet(sp, "getPreferredAnimationLength");
        double length = ANIM_LENGTH > 0 ? ANIM_LENGTH
            : (len instanceof Number ? ((Number) len).doubleValue() : -1);
        if (director == null || length <= 0) {
            tried.append("\n  [frame-loop skipped: director/length "
                + "unavailable]");
            return false;
        }
        double start = START_TIME;
```

**(d)** Update the header comment near the top of the file (the line
`// hidden first. VIEW_NAMES are the saved camera views: ...`) — no code change,
but append a sentence to that comment block:

```java
// ANIM_LENGTH/START_TIME clip the recording window; ANIM_LENGTH <= 0 falls
// back to each screenplay's own preferred length.
```

- [ ] **Step 5: Wire the runner**

In `src/starpost/core/starccm_runner.py`, the `record_screenplays_macro(...)` call
currently ends with:

```python
                media.movie_fps,
                media.movie_format,
                media.movie_quality,
            )
```

change to:

```python
                media.movie_fps,
                media.movie_format,
                media.movie_quality,
                anim_length=media.movie_anim_length,
                start_time=media.movie_start_time,
            )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_screenplays.py tests/test_starccm_runner.py -v` then `ruff check .`
Expected: all PASS (runner tests confirm nothing else broke), ruff clean.

- [ ] **Step 7: Commit**

```bash
git add src/starpost/macros/record_screenplays.java.j2 src/starpost/core/macro_generator.py src/starpost/core/starccm_runner.py tests/test_screenplays.py
git commit -m "Record macro honours animation length and start time settings"
```

---

### Task 3: Settings dialog — Screenplays page fields

**Files:**
- Modify: `src/starpost/gui/views/settings_dialog.py` (`_build_screenplays_page` ~line 676-725; load block ~line 1539-1548; apply block ~line 1662-1668)
- Test: `tests/test_screenplays_gui.py` (`test_settings_dialog_screenplays_page_round_trip`, ~line 184)

**Interfaces:**
- Consumes: `MediaConfig.movie_anim_length` / `movie_start_time` (Task 1).
- Produces: `SettingsDialog._movie_start_time` and `SettingsDialog._movie_anim_length` (`QDoubleSpinBox`es; length shows "Auto" at 0), loaded from and applied to `settings.media`.

- [ ] **Step 1: Extend the failing test**

In `test_settings_dialog_screenplays_page_round_trip`, after
`s.media.screenplays_per_checkout = 2`:

```python
    s.media.movie_start_time = 1.5
    s.media.movie_anim_length = 12.5
```

after `assert dlg._screenplays_per_checkout.value() == 2`:

```python
    assert dlg._movie_start_time.value() == 1.5
    assert dlg._movie_anim_length.value() == 12.5
    # 0 displays as "Auto" (use each screenplay's own length).
    assert dlg._movie_anim_length.specialValueText() == "Auto"
```

after `dlg._movie_fps.setValue(60)`:

```python
    dlg._movie_start_time.setValue(0.0)
    dlg._movie_anim_length.setValue(0.0)
```

after `assert s.media.movie_fps == 60`:

```python
    assert s.media.movie_start_time == 0.0
    assert s.media.movie_anim_length == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_screenplays_gui.py -v -k settings_dialog_screenplays_page`
Expected: FAIL — `AttributeError: ... '_movie_start_time'`.

- [ ] **Step 3: Implement**

In `_build_screenplays_page`, after the `self._movie_quality` block (before
`self._screenplays_per_checkout`):

```python
        # Recording window: start offset and length. Length 0 == "Auto"
        # (record each screenplay at its own preferred length).
        self._movie_start_time = QDoubleSpinBox()
        self._movie_start_time.setRange(0.0, 3600.0)
        self._movie_start_time.setDecimals(1)
        self._movie_start_time.setFixedWidth(140)
        self._movie_anim_length = QDoubleSpinBox()
        self._movie_anim_length.setRange(0.0, 3600.0)
        self._movie_anim_length.setDecimals(1)
        self._movie_anim_length.setSpecialValueText("Auto")
        self._movie_anim_length.setFixedWidth(140)
        self._movie_anim_length.setToolTip(
            "Auto records each screenplay at its own animation length; a "
            "number forces that duration (in seconds) for all screenplays."
        )
```

(`QDoubleSpinBox` is already imported in this file.)

In the form, after `form.addRow("Frame rate (fps)", self._movie_fps)`:

```python
        form.addRow("Start time (s)", self._movie_start_time)
        form.addRow("Animation length (s)", self._movie_anim_length)
```

In the load block (after `self._movie_fps.setValue(s.media.movie_fps)`):

```python
        self._movie_start_time.setValue(s.media.movie_start_time)
        self._movie_anim_length.setValue(s.media.movie_anim_length)
```

In the apply block (after `s.media.movie_fps = self._movie_fps.value()`):

```python
        s.media.movie_start_time = self._movie_start_time.value()
        s.media.movie_anim_length = self._movie_anim_length.value()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_screenplays_gui.py -v` then `ruff check .`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/gui/views/settings_dialog.py tests/test_screenplays_gui.py
git commit -m "Settings: start time and animation length on the Screenplays page"
```

---

### Task 4: Batch run dialog — options + Save Screenplay capture

**Files:**
- Modify: `src/starpost/gui/views/batch_run_dialog.py` (imports ~line 27-52; `_build_screenplays_tab` ~line 1355-1403; `_capture_screenplay` ~line 1903-1914)
- Test: `tests/test_main_window.py` (`test_batch_run_dialog_save_screenplay`, ~line 990-1028)

**Interfaces:**
- Consumes: `MediaConfig.movie_anim_length` / `movie_start_time` (Task 1).
- Produces: `BatchRunDialog._sp_start` / `_sp_length` (`QDoubleSpinBox`es), and `_capture_screenplay()` dicts carrying `"start_time": float` and `"anim_length": float` (consumed by Task 5).

- [ ] **Step 1: Extend the failing test**

In `test_batch_run_dialog_save_screenplay`, after `dlg._sp_quality.setCurrentIndex(...)`:

```python
    dlg._sp_start.setValue(1.5)
    dlg._sp_length.setValue(8.0)
```

and replace the expected dict with:

```python
    assert item.data(Qt.ItemDataRole.UserRole) == {
        "displayers": {"Fly": ["P"]}, "views": [],
        "resolution": "2160p", "format": "mov", "fps": 60, "quality": "medium",
        "start_time": 1.5, "anim_length": 8.0,
    }
```

Also add, right after the dialog is created (before any `_sp_*` is changed) —
`Settings()` defaults seed the timing spinboxes:

```python
    assert dlg._sp_start.value() == 0.0
    assert dlg._sp_length.value() == 0.0
    assert dlg._sp_length.specialValueText() == "Auto"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -v -k save_screenplay`
Expected: FAIL — `AttributeError: ... '_sp_start'`.

- [ ] **Step 3: Implement**

Add `QDoubleSpinBox,` to the `PySide6.QtWidgets` import list in
`batch_run_dialog.py` (alphabetical: after `QDialogButtonBox,`, before `QFileDialog,`).

In `_build_screenplays_tab`, after the `self._sp_quality` block (before the
`if self._settings is not None:` seed block):

```python
        # Recording window: start offset and length; length 0 == "Auto"
        # (each screenplay's own preferred length).
        self._sp_start = QDoubleSpinBox()
        self._sp_start.setRange(0.0, 3600.0)
        self._sp_start.setDecimals(1)
        self._sp_length = QDoubleSpinBox()
        self._sp_length.setRange(0.0, 3600.0)
        self._sp_length.setDecimals(1)
        self._sp_length.setSpecialValueText("Auto")
        self._sp_length.setToolTip(
            "Auto records each screenplay at its own animation length; a "
            "number forces that duration (in seconds) for all screenplays."
        )
```

In the seed block, after `self._sp_fps.setValue(media.movie_fps)`:

```python
            self._sp_start.setValue(media.movie_start_time)
            self._sp_length.setValue(media.movie_anim_length)
```

In the options column layout, after
`options.addWidget(QLabel("Frame rate"))` / `options.addWidget(self._sp_fps)`:

```python
        options.addWidget(QLabel("Start time (s)"))
        options.addWidget(self._sp_start)
        options.addWidget(QLabel("Animation length (s)"))
        options.addWidget(self._sp_length)
```

In `_capture_screenplay`, extend the returned dict (after `"quality": ...`):

```python
            "start_time": self._sp_start.value(),
            "anim_length": self._sp_length.value(),
```

and mention the timing fields in its docstring ("...the chosen views, and the
movie options including the recording start time and length.").

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -v` then `ruff check .`
Expected: all PASS (the full file, to catch layout/summary regressions), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/gui/views/batch_run_dialog.py tests/test_main_window.py
git commit -m "Run batch: start time and animation length in screenplay options"
```

---

### Task 5: Per-entry override in `_screenplay_runner`

**Files:**
- Modify: `src/starpost/batch/run.py` (`_screenplay_runner`, ~line 155-173)
- Test: `tests/test_screenplays.py` (new tests at the end)

**Interfaces:**
- Consumes: entry dicts with optional `"start_time"` / `"anim_length"` keys (Task 4), `MediaConfig` fields (Task 1).
- Produces: `_screenplay_runner(settings, entry_data, base) -> StarRunner` whose `settings.media` carries the entry's timing values (key present, even 0) or the global ones (key absent).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_screenplays.py`:

```python
def test_screenplay_runner_timing_key_presence():
    """Saved-screenplay timing overrides are decided by key presence, not
    truthiness: an explicit 0 (Auto length / zero start) wins over a non-zero
    global; a missing key falls back to the global setting."""
    from starpost.batch.run import _screenplay_runner
    from starpost.core.starccm_runner import StarRunner

    s = Settings()
    s.media.movie_anim_length = 15.0
    s.media.movie_start_time = 3.0
    base = StarRunner(s)

    # Explicit values (including 0) override the globals.
    r = _screenplay_runner(
        s, {"start_time": 0.0, "anim_length": 0.0}, base
    )
    assert r is not base
    assert r.settings.media.movie_anim_length == 0.0
    assert r.settings.media.movie_start_time == 0.0

    # Non-zero captured values apply too.
    r = _screenplay_runner(
        s, {"start_time": 1.5, "anim_length": 8.0}, base
    )
    assert r.settings.media.movie_anim_length == 8.0
    assert r.settings.media.movie_start_time == 1.5

    # Keys absent (entry saved by an older StarPost): globals stand. The
    # entry has another override so a new runner is still built.
    r = _screenplay_runner(s, {"fps": 24}, base)
    assert r.settings.media.movie_anim_length == 15.0
    assert r.settings.media.movie_start_time == 3.0

    # Nothing to override at all -> the base runner is reused.
    assert _screenplay_runner(s, {}, base) is base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_screenplays.py -v -k timing_key_presence`
Expected: FAIL — the explicit-0 entry returns `base` (today's truthiness guard).

- [ ] **Step 3: Implement**

Replace `_screenplay_runner` in `src/starpost/batch/run.py` with:

```python
def _screenplay_runner(settings, entry_data: dict, base: StarRunner) -> StarRunner:
    """A runner whose media settings use the saved screenplay's per-entry movie
    options (resolution/format/fps/quality and the recording start time and
    length), so each screenplay records at the settings captured on the
    Screenplays tab. Falls back to ``base`` when there is nothing to override.

    The timing keys are meaningful at 0 (0 length == Auto), so their presence
    in the saved entry — not truthiness — decides whether they override; keys
    absent from entries saved by older StarPost fall back to the globals."""
    res = entry_data.get("resolution")
    fmt = entry_data.get("format")
    fps = entry_data.get("fps")
    quality = entry_data.get("quality")
    has_start = "start_time" in entry_data
    has_length = "anim_length" in entry_data
    if settings is None or not (
        res or fmt or fps or quality or has_start or has_length
    ):
        return base
    media = dataclasses.replace(
        settings.media,
        movie_resolution=res or settings.media.movie_resolution,
        movie_format=fmt or settings.media.movie_format,
        movie_fps=fps or settings.media.movie_fps,
        movie_quality=quality or settings.media.movie_quality,
        movie_start_time=(
            float(entry_data["start_time"]) if has_start
            else settings.media.movie_start_time
        ),
        movie_anim_length=(
            float(entry_data["anim_length"]) if has_length
            else settings.media.movie_anim_length
        ),
    )
    return StarRunner(dataclasses.replace(settings, media=media))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_screenplays.py tests/test_main_window.py -v` then `ruff check .`
Expected: all PASS (main-window batch tests exercise `_screenplay_runner` callers), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/batch/run.py tests/test_screenplays.py
git commit -m "Batch: saved screenplays override recording start time and length"
```

---

### Task 6: Changelog + full-suite verification

**Files:**
- Modify: `CHANGELOG.md` (under `## [Unreleased]`)

**Interfaces:**
- Consumes: everything above. Produces: nothing new — release bookkeeping and the whole-suite gate.

- [ ] **Step 1: Write the changelog entry**

Under `## [Unreleased]` in `CHANGELOG.md`, add (matching the existing bold-lead style):

```markdown
### New Features
- **Screenplay recording length & start time** — Settings → Screenplays gains
  "Start time (s)" and "Animation length (s)" (Auto = each screenplay's own
  length, matching STAR-CCM+'s Write Animation dialog). The run-batch window's
  screenplay options carry the same two fields, and "Save Screenplay" captures
  them per saved screenplay. Recordings now always start at the configured
  start time (default 0) rather than the screenplay's preferred start time.
```

- [ ] **Step 2: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen python scripts/run_tests.py`
Expected: every file PASSES. (Never a bare `python -m pytest` for the full suite —
the GUI tests need per-file process isolation.)

Run: `ruff check .`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "Changelog: screenplay recording length & start time"
```
