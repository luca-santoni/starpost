# Screenplay animation length & start time — design

Date: 2026-07-17
Status: approved

## Goal

Let the user control the **Animation Length** and **Start Time** of recorded
screenplay movies — the same two timing fields STAR-CCM+'s own "Write
Animation" dialog exposes alongside Frame Rate. The values must be settable in
three places:

1. **Settings → Screenplays tab** — the global defaults used by the
   Screenplays tab's Record button.
2. **Run-batch window** — the screenplay options panel, seeded from settings.
3. **Saved screenplays** — captured by "Save Screenplay" and applied per entry
   when the batch runs.

## Semantics

- **Animation length** (`movie_anim_length: float = 0.0`, seconds):
  **0 = Auto** — record each screenplay at its own preferred length probed
  from the sim (today's behavior). Any value > 0 forces that duration for
  every screenplay in the recording run.
- **Start time** (`movie_start_time: float = 0.0`, seconds): a plain number,
  default 0, **no Auto state**. The recording always starts at this value;
  the macro's current `getPreferredStartTime` probe is removed. (Behavior
  change: a screenplay with a non-zero preferred start time now starts at the
  user's value — 0 unless adjusted. Intentional.)
- Both values are clamped to ≥ 0 when read from YAML.

## Changes by component

### `core/settings.py` + `config/default_settings.yaml`

Add `movie_anim_length` and `movie_start_time` to `MediaSettings`, following
`movie_fps` exactly: dataclass field, `to_dict`, `from_dict` (with ≥ 0
clamping), and commented defaults in `default_settings.yaml` (noting the
0 = Auto convention for length).

### `macros/record_screenplays.java.j2` + `core/macro_generator.py`

`record_screenplays_macro` gains `anim_length: float` and `start_time: float`
parameters, rendered as constants next to `FPS`:

- `ANIM_LENGTH` — used when > 0, otherwise `probeLength(...)` as today. When
  the override is set, the known-signature path's "no animation length getter
  found" bail-out no longer applies.
- `START_TIME` — always used. The `getPreferredStartTime` probe goes away;
  the frame-loop's "start missing" skip condition is dropped.

Both export paths honor them: known-signature
`record(w, h, FPS, START_TIME, length, ...)`; frame-loop
`t = START_TIME + f / FPS` over `length * FPS + 1` frames.

`StarRunner.record_screenplays` passes `media.movie_anim_length` and
`media.movie_start_time` through — the Screenplays tab's Record button picks
the settings values up with no further wiring.

### `gui/views/settings_dialog.py` (Screenplays page)

Two new form rows between "Frame rate (fps)" and "Quality":

- **"Start time (s)"** — `QDoubleSpinBox`, range 0–3600, 1 decimal,
  default 0.
- **"Animation length (s)"** — same, but the minimum (0) displays as
  **"Auto"** via `specialValueText`; tooltip explains Auto = each
  screenplay's own length.

Load/apply wired like the neighboring media fields.

### `gui/views/batch_run_dialog.py`

- Screenplay options gain matching spinboxes `_sp_start` and `_sp_length`
  (same widget config as the settings page), seeded from
  `media.movie_start_time` / `media.movie_anim_length` the way `_sp_fps` is
  seeded today.
- `_capture_screenplay` adds `"start_time"` and `"anim_length"` to the saved
  snapshot, so "Save Screenplay" persists them in the profile.
- The saved-screenplay Properties popup shows the new keys automatically
  (it renders the captured dict).

### `batch/run.py`

`_screenplay_runner` applies both values per saved entry with
**key-presence semantics**, not truthiness:

- Key present → use the captured value, **including an explicit 0**
  (0 length = Auto, 0 start = start at zero), even when the global setting
  differs.
- Key absent (entry saved by an older StarPost) → fall back to the global
  `MediaSettings` value.

The existing "nothing to override" early-return is updated so an entry whose
only override is a timing key still gets its own runner.

## Out of scope

- Per-screenplay lengths in the Screenplays tree (one value per recording
  run, like fps/quality).
- Movie Type / anti-aliasing / transparent-background toggles from the STAR
  dialog.
- Any change to scene stills or screenplay poster frames.

## Testing

- **Settings round-trip:** defaults (0.0 / 0.0), custom values, negatives
  clamped to 0 on load.
- **Macro generator:** rendered `.java` contains the passed `ANIM_LENGTH` and
  `START_TIME` values; default render keeps `ANIM_LENGTH = 0` (Auto).
- **Batch dialog:** `_capture_screenplay` includes both keys; spinboxes seed
  from settings.
- **`_screenplay_runner`:** explicit-0 override wins over a non-zero global;
  missing key falls back to the global; timing-only override still produces
  an overridden runner.
- **Settings dialog:** load → change → apply round-trips both fields.
- `CHANGELOG.md` entry. No keyboard shortcuts touched, so no hotkey doc
  change.
