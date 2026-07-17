---
name: verify
description: How to run and drive StarPost headlessly to verify GUI changes end-to-end (offscreen QApplication, real MainWindow, synthetic clicks, screenshots).
---

# Verifying StarPost GUI changes

No display is needed: the app runs fully under `QT_QPA_PLATFORM=offscreen`, and
`QWidget.grab().save("shot.png")` captures pixel-accurate screenshots there.

## Launch recipe

Write a small driver script and run it with the project venv
(`PYTHONPATH=src` from the working copy so an editable install elsewhere
doesn't shadow it):

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python driver.py
```

The driver replicates `starpost.app.main()` minus `exec()`:

```python
app = QApplication(sys.argv)
app.setStyle(ToolTipResetStyle())
install_combo_accent(app)
install_click_deselect(app)
settings = Settings()          # NOT Settings.load() — see isolation below
apply_theme(app, settings.appearance.mode, settings.appearance.accent,
            settings.appearance.resolved_checkmark(), settings.appearance.text_scale)
win = MainWindow(settings); win.resize(1400, 900); win.show()
```

**Isolate per-user state first** (before any starpost import runs code), the
same way `tests/` do, so the run never touches real config or the file-list
cache:

```python
import starpost.utils.paths as paths
paths.platformdirs.user_config_dir = lambda *a, **k: str(tmp / "config")
paths.platformdirs.user_cache_dir = lambda *a, **k: str(tmp / "cache")
```

## Populating without STAR-CCM+

Never let a drive path reach `StarRunner` (it shells out to `starccm+`).

- Files tree: `win.file_list._add_paths([Path("/cases/a.sim"), ...])`.
- Results: `win.store.put(SimResult(sim_path=..., reports=[Report(...)]))`.
- Reports table: `win.report_table.show_single(result)` — but call
  `QApplication.processEvents()` **before** it, or the startup refresh timer
  (which runs on the first event-loop turn and sees no checked data set)
  clears the model you just set.
- Double-click on a file emits `win.file_list.open_requested` → extraction;
  `disconnect()` it and connect a stub before synthesizing double-clicks.

## Driving

`QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, modifier, pos)`
with `pos = view.visualItemRect(item).center()` (tables:
`view.visualRect(model.index(r, c)).center()`). After each gesture call
`QApplication.processEvents()` — it also fires `QTimer.singleShot(0)` work.
Capture evidence with `win.grab().save(...)` between steps.

## Gotchas

- "This plugin does not support propagateSizeHints()" on stderr is normal
  offscreen noise; ignore it.
- Don't drive scene rendering, screenplay recording, or batch runs — all
  shell out to STAR-CCM+ (not installed on dev machines / not on PATH).
- **QTest is not a real mouse.** `QTest.mouseClick` sends events directly to
  the target widget: no `MouseButtonDblClick` synthesis for rapid click pairs,
  and no window-level delivery (a real display passes every mouse event
  through application event filters twice — once for the top-level
  QWidgetWindow, then for the widget). Both differences have hidden real bugs
  that QTest-driven tests passed. For input-handling changes, verify on the
  real display too: this machine runs X11 with `DISPLAY=:0`; inject genuine
  clicks with `python-xlib` (installed in the venv):

  ```python
  from Xlib import X, display as xdisplay
  from Xlib.ext import xtest
  xd = xdisplay.Display(":0")
  xd.screen().root.warp_pointer(gx, gy); xd.sync()
  xtest.fake_input(xd, X.ButtonPress, 1); xd.sync()
  xtest.fake_input(xd, X.ButtonRelease, 1); xd.sync()
  ```

  Spin the Qt loop while waiting (`app.processEvents()` in a sleep loop) —
  the events arrive asynchronously. The app window appears on the user's
  screen and the pointer really moves: keep the run short and warn the user.
