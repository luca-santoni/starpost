# Convergence: bulk primary-selection buttons — design

## Goal

Add **Select all**, **Clear** and **Reset to auto** buttons to the Convergence
window's Monitors list, so the primary-QoI ticks can be set in one click instead
of one checkbox at a time. A real car-aero export carries ~40 monitors, which
makes "untick everything, then tick the one I care about" a 40-click operation
today.

The third button is not cosmetic. `MonitorConfig.is_primary` is currently a
plain `bool`, so *any* stored per-monitor configuration counts as an explicit
override — there is no value meaning "let the tool decide". The dialog seeds a
configuration for every monitor on the first assessment
(`convergence_dialog.py:239-248`), which means the auto-primary rule
(`_select_auto_primary`, "prefer `Downforce ALL` over its 36 per-element
siblings") effectively runs once per data set and is frozen thereafter. Adding
**Clear** without a route back would turn that from a latent quirk into a
one-way door: the only way to recover the tool's own choice would be closing and
reopening the window.

## Scope

Buttons act on **the currently selected data set only** — exactly the rows
visible in the Monitors table. This matches how the existing per-monitor
tolerance and reference-scale edits behave, and avoids changing rows the user
cannot see. Applying a selection across every loaded data set is deliberately
not in scope: the loaded sims do not necessarily share monitor names.

## Design

### 1. Tri-state primary override (core)

`MonitorConfig.is_primary` changes from `bool = False` to
`Optional[bool] = None`:

| value | meaning |
|---|---|
| `True` | the user pinned this monitor primary |
| `False` | the user pinned this monitor non-primary |
| `None` | no opinion — `_select_auto_primary` decides |

`assess` (`core/convergence/__init__.py:327-331`) falls through to the auto rule
whenever the override is absent **or** its `is_primary` is `None`.

`_auto_primary_reason` currently identifies "monitors the auto logic actually
decided" by testing `config.monitors.get(name) is None`. That test must widen to
"…or its `is_primary` is `None`". Without this, a monitor carrying only a
*tolerance* override drops out of the INFO reason that names the auto-selected
primaries. That reason exists so a wrong auto-choice leaves a trace in the
Reasons tab rather than silently narrowing the verdict, so losing entries from
it is a real regression, not a cosmetic one.

This is the only behavioural change in the analysis package. `MonitorConfig`'s
`is_primary` is read in exactly one place; `MonitorAssessment.is_primary` (the
assessment *output*, consumed throughout `verdict.py`) is a different field and
stays a plain `bool`.

### 2. Buttons (dialog)

A `QHBoxLayout` under the Monitors table: **Select all** · **Clear** ·
**Reset to auto**, then a stretch.

All three route through one handler that writes `True` / `False` / `None` to
`is_primary` for every monitor **in the current assessment**, then calls
`_reassess()` exactly once.

Two properties this handler must hold:

- **It mutates `_monitor_configs`, not the checkboxes.** Driving the widgets
  would fire `itemChanged` per row, and `_on_monitor_edited` calls `_reassess()`,
  which re-assesses *every loaded data set* — 40 monitors across 10 sims would
  be 400 assessments for one click. Writing the model and re-assessing once
  keeps the table a view of the configuration, which is how every other edit in
  this dialog already works.
- **It iterates the assessment's monitors, not the raw signals.** Monitors that
  are exactly zero at every iteration are excluded from the assessment upstream
  and must not be resurrected by a bulk selection.

**Reset to auto** writes `None` to `is_primary` only. That data set's tolerance
and reference-scale overrides survive — the button sits in a primary-selection
group and must not silently discard unrelated edits.

Buttons are disabled when the Monitors table is empty (no data sets loaded, or
none selected).

### 3. Remove the seeding loop

`_reassess`'s seeding loop (`convergence_dialog.py:239-248`) is deleted. Its
stated purpose is to make the auto choice "visible and editable", but under
tri-state it would write only `None` entries, which carry no information —
`_on_monitor_edited` already creates a `MonitorConfig` on demand via
`configs.get(name, MonitorConfig())`, and `_config_for` handles an absent dict.
Keeping it would leave dead code that appears to do the same job as the new
Reset button.

## Behaviour worth recording

**Clearing every primary is allowed and produces a valid verdict**, not an
error: convergence index `—`, binding constraint "no primary QoI declared",
state `CONVERGING`, confidence Low. This is the existing honest handling of
"no primary QoI", and it is the natural midpoint of the clear-then-pick-one
workflow the buttons are for. It should not later be "fixed" by forcing a
minimum selection.

## Testing

`tests/test_convergence_gui.py`:

- Select all → every monitor is primary in the next assessment.
- Clear → no monitor is primary; the verdict reports "no primary QoI declared"
  at Low confidence.
- Reset to auto, after a Clear → the primary set matches the auto rule
  (aggregate preferred over per-element siblings).
- Reset to auto preserves a tolerance override set on a monitor.
- One bulk click triggers exactly one re-assessment — this guards the
  performance property above, which is invisible in the rendered result.
- Buttons are disabled when no data sets are loaded.

`tests/test_convergence_config.py`:

- `MonitorConfig().is_primary is None` (replaces the existing `is False`
  assertion).
- A `MonitorConfig` setting a tolerance but leaving `is_primary` as `None`
  still follows the auto rule for primacy while honouring the tolerance.
- An explicit `is_primary=False` still demotes a monitor the auto rule would
  have selected.

## Documentation

- `CHANGELOG.md` entry in the existing style.
- One line in `docs/convergence-notes.md` §6 ("Design decisions that must not be
  silently undone") recording that `MonitorConfig.is_primary` is tri-state on
  purpose, so a later reader does not "simplify" it back to a plain `bool` and
  silently kill the auto-primary rule again.

No new keyboard shortcuts, so `src/starpost/gui/shortcuts.py` and
`docs/starpost_hotkeys.txt` are untouched.

## Out of scope

- Applying a selection across every loaded data set at once.
- Any change to `_select_auto_primary`'s own rule for which monitors it picks.
- Bulk editing of tolerance or reference scale.
