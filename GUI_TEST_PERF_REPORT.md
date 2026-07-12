# Task: Fix the GUI test-suite slowdown / on-screen hang (2.4.0, Windows)

> Handoff report. Self-contained — no prior conversation context needed.
> Repo: `starpost` (PySide6 desktop app). **Implement and verify this on Linux**,
> then confirm on Windows (offscreen). The mid-test widget teardown that fixes
> this crashes the interpreter *on Windows* if done naively (see "Pitfalls");
> Linux does not have that fragility, which is why the bug was never seen there.

## Symptom

Running the full test suite:

- **On Linux:** fine (~70s), no issues — this is why it went unnoticed.
- **On Windows, on-screen (default Qt platform):** **hangs** (~65% through; a
  "not responding" window). This is a **2.4.0 regression** — the 2.3.0 suite ran
  on-screen in ~72s.
- **On Windows, headless:** completes but pathologically slow —
  `QT_QPA_PLATFORM=offscreen python -m pytest tests\` → **245 passed, 2 skipped
  in ~13 minutes** (vs ~70s expected).

## Root cause

GUI tests share **one** `QApplication` (every test file's `app` fixture is
`QApplication.instance() or QApplication([])`) and **mostly never dispose the
top-level widgets they build** (`MainWindow`, `SettingsDialog`, batch dialogs).
There is no shared cleanup. So widgets accumulate across the whole session into
the **hundreds of thousands**.

`apply_theme(app, ...)` (in `src/starpost/gui/theme.py`) calls
`app.setStyleSheet(...)`, which forces Qt to **re-polish every live widget in the
application**. That is cheap early in the suite and brutal late:

- Measured: `apply_theme` with ~1,180 live widgets = **0.12s**.
- In the full suite, the theme-heavy tests call it with the full accumulation, so
  a single call costs tens of seconds; tests that apply it repeatedly hit
  minutes.

### Evidence

`--durations` on the full offscreen run (slowest calls, everything else < 1s):

| Duration | Test |
|---|---|
| 251s | `tests/test_text_scale.py::test_dialog_cancel_reverts_live_preview` |
| 181s | `tests/test_widgets.py::test_apply_theme_syncs_combo_accent_colour` |
| 158s | `tests/test_text_scale.py::test_main_window_builds_at_enlarged_text_scale` |
| 52s  | `tests/test_text_scale.py::test_dialog_cancel_without_appearance_change_skips_restyle` |
| 49s  | `tests/test_text_scale.py::test_apply_theme_pushes_scaled_font_onto_app` |
| 49s  | `tests/test_text_scale.py::test_dialog_change_and_save_persists_text_scale` |

Decisive proof it is accumulation, not an inherently slow test:
`python -m pytest tests/test_text_scale.py` **in isolation = 3.06s total** (those
same tests: 0.01–0.87s each). Only when run after the rest of the suite (with all
its leaked widgets alive) do they balloon.

### Why it regressed in 2.4.0 (likely amplifier)

2.4.0 added a **frameless custom title bar** (`src/starpost/gui/views/title_bar.py`,
`CaptionButton`). This (a) adds more widgets to every window and (b) introduces
**`qproperty-…` QSS rules** in `theme.py` (e.g. `CaptionButton { qproperty-glyphColor: … }`),
which invoke per-widget property setters on every re-polish. More widgets per
window + costlier re-polish pushed the latent accumulation over the edge.

### Why it is not a product bug

The running app only ever has a **single** `MainWindow`, so `apply_theme` is
instant in production. The pathology exists purely in the test suite because it
accumulates windows a real session never would.

## The fix (recommended): adopt `pytest-qt` / `qtbot`

`qtbot` tracks the widgets a test registers and disposes them safely after each
test — cross-platform, without the native-crash problem of ad-hoc deletion.

1. Add the dev dependency in `pyproject.toml` under
   `[project.optional-dependencies] dev = [...]`: add `"pytest-qt>=4.4"`.
   Reinstall: `pip install -e ".[dev]"`.
2. `pytest-qt` provides a session `qapp` and a function-scoped `qtbot`. Remove the
   per-file `app` fixtures (or keep them returning `qapp`) and have each GUI test
   register the top-level widgets it creates:

   ```python
   def test_something(qtbot):
       win = MainWindow(settings)
       qtbot.addWidget(win)          # qtbot closes + schedules deletion at teardown
       ...
   ```

   `qtbot.addWidget` calls `widget.close()` and arranges disposal in a way that
   spins the event loop so `deleteLater` actually resolves — keeping the live
   widget count flat between tests.
3. Files that build top-level widgets and need updating (search for
   `MainWindow(`, `SettingsDialog(`, `BatchRunDialog(`, `ExportDialog(`, dialogs):
   `tests/test_main_window.py`, `tests/test_text_scale.py`, `tests/test_widgets.py`,
   `tests/test_screenplays_gui.py`, `tests/test_export_dialog.py`,
   `tests/test_plot_view.py`. (Many already call `deleteLater()` manually but it
   never gets processed — `qtbot.addWidget` replaces those ad-hoc calls.)

Expected result after the change: the full suite drops back to ~70s on both
platforms and no longer hangs on-screen on Windows.

## Pitfalls (why the naive fix fails — do not repeat these)

A plain autouse teardown that force-deletes top-level widgets and/or calls
`app.processEvents()` **aborts the interpreter on Windows** (`0xC0000409` /
"Fatal Python error: Aborted"). Confirmed causes:

- The **Run-batch dialog** (`test_main_window.py::test_run_batch_opens_dialog`,
  which does *not* call `deleteLater`) builds a **pyqtgraph** plot tree that
  crashes when destroyed mid-session.
- Dialogs owning a worker **`QThread`** abort with "QThread: Destroyed while
  thread is still running" if their owner is deleted while the thread runs.
- A cumulative `processEvents()` in teardown delivers queued cross-thread
  signals/timers to accumulated/half-alive objects and crashes ~58% through.

These native crashes do **not** happen on Linux, so develop the fix there. This
is also why `qtbot` (which closes widgets and pumps the loop in a controlled way)
is preferred over a hand-rolled teardown.

## Verification

On **Linux** (primary):

```bash
python -m pytest tests/ -q --durations=8
```

Expect: all pass, total ~70s, and the six tests listed above back to sub-second.

On **Windows** (confirm the regression is gone):

```powershell
# on-screen (was hanging): should now complete quickly
.\.venv\Scripts\python.exe -m pytest tests\ -q
# headless (was ~13 min): should now be ~70s
$env:QT_QPA_PLATFORM = "offscreen"; .\.venv\Scripts\python.exe -m pytest tests\ -q
```

Note: on Windows, force a fresh pytest temp base if a prior interrupted run left
a locked one — `--basetemp=<fresh dir>`. And kill any orphaned `python.exe`
processes from interrupted GUI runs before re-running (they linger and interfere).

## Optional secondary investigation

Profile whether the `qproperty-…` QSS on `CaptionButton` (added in 2.4.0,
`theme.py`) is disproportionately expensive to re-polish. If so, a cheaper
styling approach for the caption buttons would reduce `apply_theme` cost for the
real app too (minor, since production has one window) and further de-risk the
tests. This is secondary to the `qtbot` fix.

## Scope / guardrails

- This is a **test-suite** change (plus one dev dependency). **No product/runtime
  code change is required** for the primary fix.
- Do not alter what the tests assert. `qtbot.addWidget` replaces manual
  `deleteLater()` bookkeeping; keep each test's actual checks intact.
- The 2 skipped tests are POSIX-only file-permission tests
  (`@skipif(sys.platform == "win32")`) — leave them.
