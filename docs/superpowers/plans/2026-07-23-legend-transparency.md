# Legend Background Transparency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users set the opacity of the plot legend's background box (default 20%), as a persisted Plots-tab setting and as an override slider in the Export and Run batch dialogs.

**Architecture:** Follow the existing legend-property pattern (`legend_scale`/`legend_offset`) that flows Settings → live `PlotView` → Export dialog → Run batch dialog → batch render. Opacity is the alpha of the legend's background box brush, coloured to match the plot background so it reads in both themes. Unlike `legend_scale`, opacity also gets a persisted default on `Settings`.

**Tech Stack:** Python 3.11, PySide6 (Qt), pyqtgraph, pytest, ruff.

## Global Constraints

- Line length 100; ruff target py311. Run `ruff check .` clean.
- Run the full suite with `python scripts/run_tests.py` (GUI tests share one `QApplication`); single files may use `python -m pytest`. On headless machines prefix GUI runs with `QT_QPA_PLATFORM=offscreen`.
- Brand is written **StarPost**; lowercase `starpost` only for package/path/command.
- Tests must not write real user config/cache — the autouse fixture monkeypatching `paths.platformdirs` handles this; do not bypass it.
- Log user-facing changes in `CHANGELOG.md` (newest first) under `## [Unreleased]`.
- Opacity is stored as a fraction in `[0.0, 1.0]`; UI controls use an integer 0–100 (percent). Conversions: fraction→slider `round(frac * 100)`, slider→fraction `value / 100.0`. Default fraction is `0.2`.

---

### Task 1: Settings model field + default YAML

**Files:**
- Modify: `src/starpost/core/settings.py` (dataclass field ~line 197; `from_dict` ~line 328; `to_dict` ~line 392)
- Modify: `config/default_settings.yaml` (after `hover_y_decimals`, ~line 82)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings.legend_opacity: float` (fraction 0–1, default 0.2), round-tripped via `to_dict`/`from_dict` and clamped to `[0.0, 1.0]` on load.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings.py`:

```python
def test_legend_opacity_default():
    s = Settings.from_dict({})
    assert s.legend_opacity == 0.2


def test_legend_opacity_round_trip():
    s = Settings.from_dict({"legend_opacity": 0.5})
    d = s.to_dict()
    assert d["legend_opacity"] == 0.5
    assert Settings.from_dict(d).legend_opacity == 0.5


def test_legend_opacity_clamped_on_load():
    assert Settings.from_dict({"legend_opacity": 1.7}).legend_opacity == 1.0
    assert Settings.from_dict({"legend_opacity": -0.3}).legend_opacity == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_settings.py -k legend_opacity -v`
Expected: FAIL — `AttributeError`/`KeyError` (no `legend_opacity` field yet).

- [ ] **Step 3: Add the dataclass field**

In `src/starpost/core/settings.py`, in the `Settings` dataclass next to the other plot fields (after `moving_average_width: int = 10` around line 197):

```python
    legend_opacity: float = 0.2  # opacity of the plot legend's background box (0–1)
```

- [ ] **Step 4: Parse it in `from_dict` (clamped)**

In `from_dict`, alongside the other plot keys (after the `moving_average_width=...` line ~328):

```python
            legend_opacity=min(1.0, max(0.0, float(d.get("legend_opacity", 0.2)))),
```

- [ ] **Step 5: Serialize it in `to_dict`**

In `to_dict`, alongside the other plot keys (after `"moving_average_width": self.moving_average_width,` ~line 392):

```python
            "legend_opacity": self.legend_opacity,
```

- [ ] **Step 6: Seed the default in the YAML**

In `config/default_settings.yaml`, after the `hover_y_decimals: 4` line (~82):

```yaml

# Opacity of the box drawn behind the plot legend (0.0 = fully transparent,
# 1.0 = solid). Lower values let plot curves show through the legend.
legend_opacity: 0.2
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_settings.py -k legend_opacity -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add src/starpost/core/settings.py config/default_settings.yaml tests/test_settings.py
git commit -m "feat: add legend_opacity setting (default 0.2)"
```

---

### Task 2: PlotView legend background brush

**Files:**
- Modify: `src/starpost/gui/views/plot_view.py` (`__init__` ~line 444 and ~586; `apply_theme` ~line 590)
- Test: `tests/test_plot_view.py`

**Interfaces:**
- Consumes: `self._legend` (a `pg.LegendItem`), `self._bg` (hex colour string, e.g. `"#1e1e1e"` / `"#ffffff"`).
- Produces:
  - `PlotView.set_legend_opacity(frac: float) -> None` — clamps `frac` to `[0,1]`, stores it, and repaints the legend box.
  - `PlotView._apply_legend_brush() -> None` — sets the legend background brush to `self._bg` at the stored alpha.
  - `self._legend_opacity: float` attribute (default 0.2).
  - The legend brush alpha readable via `self._legend.brush().color().alpha()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plot_view.py`:

```python
def test_set_legend_opacity_sets_brush_alpha():
    pv = PlotView()
    pv.set_legend_opacity(0.2)
    assert pv._legend.brush().color().alpha() == 51  # round(0.2 * 255)
    pv.set_legend_opacity(1.0)
    assert pv._legend.brush().color().alpha() == 255


def test_set_legend_opacity_clamps():
    pv = PlotView()
    pv.set_legend_opacity(5.0)
    assert pv._legend.brush().color().alpha() == 255
    pv.set_legend_opacity(-1.0)
    assert pv._legend.brush().color().alpha() == 0


def test_apply_theme_preserves_opacity_and_retints_box():
    pv = PlotView()
    pv.set_legend_opacity(0.4)
    pv.apply_theme("light")
    c = pv._legend.brush().color()
    assert c.alpha() == round(0.4 * 255)
    assert (c.red(), c.green(), c.blue()) == (255, 255, 255)  # light bg
    pv.apply_theme("dark")
    c = pv._legend.brush().color()
    assert c.alpha() == round(0.4 * 255)
    assert (c.red(), c.green(), c.blue()) == (30, 30, 30)  # dark bg #1e1e1e
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_plot_view.py -k legend_opacity -v`
Expected: FAIL — `AttributeError: 'PlotView' object has no attribute 'set_legend_opacity'`.

- [ ] **Step 3: Initialise the attribute in `__init__`**

In `src/starpost/gui/views/plot_view.py`, next to the legend-scale init (after `self._legend_scale = 1.0  # legend size multiplier (export menu slider)`, ~line 444):

```python
        self._legend_opacity = 0.2  # alpha of the legend's background box (0–1)
```

- [ ] **Step 4: Apply the brush once after the background colour is set**

In `__init__`, after `self._plot.setBackground(self._bg)` and `self._style_stats_label()` (~line 586–587), add:

```python
        self._apply_legend_brush()
```

- [ ] **Step 5: Add the setter and brush helper**

Add these methods next to `set_legend_scale` (after it, ~line 613):

```python
    def set_legend_opacity(self, frac: float) -> None:
        """Set the opacity of the legend's background box (0 = transparent,
        1 = solid). The box is tinted to the plot background so curves show
        through it; the value carries through to the exported image."""
        self._legend_opacity = min(1.0, max(0.0, float(frac)))
        self._apply_legend_brush()

    def _apply_legend_brush(self) -> None:
        """Paint the legend's background box in the current plot-background
        colour at the chosen opacity. Re-applied on theme change so the box
        matches the (possibly new) background while keeping its opacity."""
        color = pg.mkColor(self._bg)
        color.setAlpha(round(self._legend_opacity * 255))
        self._legend.setBrush(pg.mkBrush(color))
```

- [ ] **Step 6: Re-tint on theme change**

In `apply_theme`, after `self._plot.setBackground(self._bg)` (~line 595), add:

```python
        self._apply_legend_brush()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_plot_view.py -k legend_opacity -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add src/starpost/gui/views/plot_view.py tests/test_plot_view.py
git commit -m "feat: legend background box opacity in PlotView"
```

---

### Task 3: Plots settings-tab control

**Files:**
- Modify: `src/starpost/gui/views/settings_dialog.py` (build ~line 586–631; init-from-settings ~line 1617; reset mirror ~line 1277; form→settings ~line 1700)
- Test: `tests/test_settings_dialog.py`

**Interfaces:**
- Consumes: `Settings.legend_opacity` (Task 1).
- Produces: a `QSpinBox` `self._legend_opacity` (0–100, suffix `%`) on the Plots page; reads/writes `settings.legend_opacity` as a fraction.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings_dialog.py` (mirrors the existing `SettingsDialog(s)` → mutate → `dlg._on_accept()` pattern; `Settings`, `SettingsDialog`, and the `app` fixture are already in that file):

```python
def test_legend_opacity_loads_and_collects(app):
    s = Settings()
    s.legend_opacity = 0.5
    dlg = SettingsDialog(s)
    assert dlg._legend_opacity.value() == 50
    dlg._legend_opacity.setValue(35)
    dlg._on_accept()
    assert s.legend_opacity == 0.35
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_settings_dialog.py -k legend_opacity -v`
Expected: FAIL — `AttributeError: ... has no attribute '_legend_opacity'`.

- [ ] **Step 3: Build the spinbox in `_build_plots_page`**

In `src/starpost/gui/views/settings_dialog.py`, after the `self._moving_average_width` block (~line 586–588), add:

```python
        self._legend_opacity = QSpinBox()
        self._legend_opacity.setRange(0, 100)
        self._legend_opacity.setSuffix("%")
        self._legend_opacity.setValue(20)
```

- [ ] **Step 4: Add the row + hint to the form**

In the same method, after the moving-average `form.addRow(...)`/hint block (after line 638), add:

```python
        form.addRow("Legend opacity", self._legend_opacity)
        lo_hint = QLabel(
            "Opacity of the box behind the plot legend; lower is more "
            "see-through, so curves show through it."
        )
        lo_hint.setObjectName("hint")
        lo_hint.setWordWrap(True)
        form.addRow("", lo_hint)
```

- [ ] **Step 5: Load from settings (init)**

In the init-from-settings block, after `self._moving_average_width.setValue(s.moving_average_width)` (~line 1619):

```python
        self._legend_opacity.setValue(round(s.legend_opacity * 100))
```

- [ ] **Step 6: Mirror on reset-to-defaults**

In the reset mirror block, after `self._moving_average_width.setValue(d.moving_average_width)` (~line 1277):

```python
        self._legend_opacity.setValue(round(d.legend_opacity * 100))
```

- [ ] **Step 7: Write back to settings (collect)**

In the form→settings block, after `s.moving_average_width = self._moving_average_width.value()` (~line 1700):

```python
        s.legend_opacity = self._legend_opacity.value() / 100.0
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_settings_dialog.py -k legend_opacity -v`
Expected: PASS. `_on_accept` writes `self._legend_opacity.value() / 100.0` into `s.legend_opacity`.

- [ ] **Step 9: Commit**

```bash
git add src/starpost/gui/views/settings_dialog.py tests/test_settings_dialog.py
git commit -m "feat: Legend opacity control on the Plots settings tab"
```

---

### Task 4: Apply the setting to the live main-window plot

**Files:**
- Modify: `src/starpost/gui/main_window.py` (startup builder ~line 217–221; `_apply_settings_to_views` ~line 1788–1798)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `Settings.legend_opacity` (Task 1), `PlotView.set_legend_opacity` (Task 2).
- Produces: the main window's `self.plot_view` reflects `settings.legend_opacity` at build time and whenever settings are applied.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_window.py` (mirrors the file's `win = mw.MainWindow(Settings())` pattern; `mw`, `Settings`, and the `app` fixture are already used in that file). Accessing `win.plot_view` triggers the lazy build:

```python
def test_settings_legend_opacity_applied_to_plot_view(app):
    win = mw.MainWindow(Settings())
    win.settings.legend_opacity = 0.6
    win._apply_settings_to_views()
    assert win.plot_view._legend_opacity == 0.6
    win.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -k legend_opacity -v`
Expected: FAIL — `_legend_opacity` still at the default 0.2, not 0.6.

- [ ] **Step 3: Apply on the settings-apply path**

In `_apply_settings_to_views`, after `self.plot_view.set_smooth_width(self.settings.moving_average_width)` (~line 1798):

```python
        self.plot_view.set_legend_opacity(self.settings.legend_opacity)
```

- [ ] **Step 4: Apply on the lazy build path**

In the plot-view builder, after `pv.set_smooth_width(s.moving_average_width)` (~line 221):

```python
            pv.set_legend_opacity(s.legend_opacity)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -k legend_opacity -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/starpost/gui/main_window.py tests/test_main_window.py
git commit -m "feat: apply legend_opacity setting to the live plot"
```

---

### Task 5: Export dialog opacity slider

**Files:**
- Modify: `src/starpost/gui/views/export_dialog.py` (preview config ~line 553; slider build ~line 673; form ~line 724; handler near ~line 736; plot_data assembly)
- Test: `tests/test_export_dialog.py`

**Interfaces:**
- Consumes: `self._settings.legend_opacity`, `self._preview.set_legend_opacity` (Task 2).
- Produces: `self._legend_opacity` slider (0–100) seeded from settings. (The Export dialog exports the live `self._preview` widget directly via `self._preview.export(...)` — there is no `plot_data` dict here, so the slider handler + initial seed fully determine the exported legend.)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_export_dialog.py` (mirrors the file's existing inline `ExportDialog(...)` construction; the slider and preview live on the Plots tab, so switch to it and pump events before asserting):

```python
def test_export_dialog_seeds_legend_opacity_from_settings(app):
    from starpost.core.settings import Settings
    from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, SimResult
    from starpost.gui.views.export_dialog import ExportDialog

    s = Settings()
    s.legend_opacity = 0.5
    result = SimResult(
        sim_path="/c/a.sim",
        plots=[MonitorPlot("G", [PlotSeries("A", [1, 2, 3], [1, 2, 3])],
                           kind=PlotKind.FORCE)],
    )
    dlg = ExportDialog(
        data_names=["a"], checked_names=["a"],
        monitor_groups={"G": ["A"]}, checked_groups=["G"],
        checked_monitors={"G": ["A"]}, results=[result], settings=s,
    )
    try:
        dlg.show()
        dlg._tabs.setCurrentWidget(dlg._plots_tab)  # builds + seeds the preview
        for _ in range(6):
            app.processEvents()
        assert dlg._legend_opacity.value() == 50
        assert dlg._preview._legend_opacity == 0.5
    finally:
        dlg.deleteLater()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_export_dialog.py -k legend_opacity -v`
Expected: FAIL — no `_legend_opacity` attribute.

- [ ] **Step 3: Build the slider**

In `export_dialog.py`, after the `self._legend_scale` slider block (~line 673–677):

```python
        # Legend opacity: 0 (fully transparent box) to 100 (solid), seeded from
        # the saved Plots setting so it matches the main window's legend.
        self._legend_opacity = QSlider(Qt.Orientation.Horizontal)
        self._legend_opacity.setRange(0, 100)
        _lo = self._settings.legend_opacity if self._settings else 0.2
        self._legend_opacity.setValue(round(_lo * 100))
        self._legend_opacity.setToolTip("Opacity of the box behind the plot legend")
        self._legend_opacity.valueChanged.connect(self._on_legend_opacity_changed)
```

- [ ] **Step 4: Add the form row**

After `form.addRow("Legend scale", self._legend_scale)` (~line 724):

```python
        form.addRow("Legend opacity", self._legend_opacity)
```

- [ ] **Step 5: Add the handler**

After `_on_legend_scale_changed` (~line 736–737):

```python
    def _on_legend_opacity_changed(self, value: int) -> None:
        self._preview.set_legend_opacity(value / 100.0)
```

- [ ] **Step 6: Seed the preview initially**

In the preview-config block, after `self._preview.apply_theme(s.export_plot_theme)` (~line 553):

```python
        self._preview.set_legend_opacity(s.legend_opacity)
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_export_dialog.py -k legend_opacity -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/starpost/gui/views/export_dialog.py tests/test_export_dialog.py
git commit -m "feat: legend opacity slider in the Export dialog"
```

---

### Task 6: Run batch dialog opacity slider + capture + properties

**Files:**
- Modify: `src/starpost/gui/views/batch_run_dialog.py` (`_configure_preview` ~line 1792; slider build ~line 1706; form ~line 1734; `_capture_plot` dict ~line 1847; `_apply_plot` ~line 1896; preview handler ~line 2194; saved-plot properties helpers ~line 358 and row ~line 381)
- Test: `tests/test_batch_run_dialog.py`

**Interfaces:**
- Consumes: `self._settings.legend_opacity`, `self._preview.set_legend_opacity` (Task 2).
- Produces: `self._legend_opacity` slider; `plot_data["legend_opacity"]` (fraction 0–1) written by `_capture_plot` and restored by `_apply_plot`; a read-only "Legend opacity" row in `_SavedPlotPropertiesDialog`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_batch_run_dialog.py` (mirrors the existing `test_saved_plot_captures_and_restores_unit_system`, using the file's `batch_dialog` fixture and its `_capture_plot`/`_apply_plot` methods):

```python
def test_saved_plot_captures_and_restores_legend_opacity(app, batch_dialog):
    dlg = batch_dialog
    dlg._legend_opacity.setValue(50)
    data = dlg._capture_plot()
    assert data["legend_opacity"] == 0.5
    dlg._legend_opacity.setValue(0)
    dlg._apply_plot(data)
    assert dlg._legend_opacity.value() == 50
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_batch_run_dialog.py -k legend_opacity -v`
Expected: FAIL — no `_legend_opacity` attribute.

- [ ] **Step 3: Build the slider**

In `batch_run_dialog.py`, after the `self._legend_scale` slider block (~line 1706–1710):

```python
        # Legend opacity: 0 (transparent box) to 100 (solid), seeded from the
        # saved Plots setting — same control as the Export dialog.
        self._legend_opacity = QSlider(Qt.Orientation.Horizontal)
        self._legend_opacity.setRange(0, 100)
        _lo = self._settings.legend_opacity if self._settings else 0.2
        self._legend_opacity.setValue(round(_lo * 100))
        self._legend_opacity.setToolTip("Opacity of the box behind the plot legend")
        self._legend_opacity.valueChanged.connect(self._preview_set_legend_opacity)
```

- [ ] **Step 4: Add the form row**

After `form.addRow("Legend scale", self._legend_scale)` (~line 1734):

```python
        form.addRow("Legend opacity", self._legend_opacity)
```

- [ ] **Step 5: Seed the preview initially**

In `_configure_preview`, after `self._preview.apply_theme(s.export_plot_theme)` (~line 1792):

```python
        self._preview.set_legend_opacity(s.legend_opacity)
```

- [ ] **Step 6: Write into `_capture_plot`**

In the `_capture_plot` dict, after the `"legend_scale": ...` entry (~line 1847):

```python
            "legend_opacity": self._legend_opacity.value() / 100.0,
```

- [ ] **Step 7: Restore in `_apply_plot`**

After the `legend_scale` restore block (~line 1896–1897):

```python
        if data.get("legend_opacity") is not None:
            self._legend_opacity.setValue(round(data["legend_opacity"] * 100))
```

- [ ] **Step 8: Add the preview handler**

After `_preview_set_legend_scale` (~line 2194–2195):

```python
    def _preview_set_legend_opacity(self, value) -> None:
        self._preview.set_legend_opacity(value / 100.0)
```

- [ ] **Step 9: Add the properties-dialog helper + row**

In `_SavedPlotPropertiesDialog`, next to the `_scale`/`_px` helpers (~line 358–363), add:

```python
        def _pct(v) -> str:
            return f"{round(v * 100)}%" if v is not None else "—"
```

Then after the `form.addRow("Legend scale:", ...)` row (~line 381):

```python
        form.addRow("Legend opacity:", QLabel(_pct(data.get("legend_opacity"))))
```

- [ ] **Step 10: Run the test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_batch_run_dialog.py -k legend_opacity -v`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/starpost/gui/views/batch_run_dialog.py tests/test_batch_run_dialog.py
git commit -m "feat: legend opacity slider + capture in the Run batch dialog"
```

---

### Task 7: Batch render honours the captured opacity

**Files:**
- Modify: `src/starpost/batch/run.py` (`_PLOT_APPLIERS` loop ~line 113–120)
- Test: `tests/test_batch_run.py`

**Interfaces:**
- Consumes: `plot_data["legend_opacity"]` (Task 6), `PlotView.set_legend_opacity` (Task 2).
- Produces: `render_saved_plot` applies the captured `legend_opacity` when rendering.

The applier loop lives inside `render_saved_plot(result, plot_data, settings, path)` (`run.py:113`), which builds and closes its own internal `PlotView` — so the test drives `render_saved_plot` end-to-end and asserts it renders (exercising the new setter without crashing) rather than inspecting the internal brush. The brush alpha itself is already covered by Task 2.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_batch_run.py` (mirrors the `batch_dialog` fixture's `SimResult`/`MonitorPlot` construction; `settings=None` is fine — `render_saved_plot` guards it):

```python
def test_render_saved_plot_accepts_legend_opacity(tmp_path):
    from PySide6.QtWidgets import QApplication
    from starpost.batch.run import render_saved_plot
    from starpost.data.models import MonitorPlot, PlotKind, PlotSeries, SimResult

    QApplication.instance() or QApplication([])
    result = SimResult(
        sim_path="/c/a.sim",
        plots=[MonitorPlot("Forces", [PlotSeries("Drag", [1, 2], [10.0, 9.0])],
                           kind=PlotKind.FORCE)],
    )
    out = tmp_path / "p.png"
    ok = render_saved_plot(
        result,
        {"monitors": {"Forces": ["Drag"]}, "legend_opacity": 0.5, "format": "png"},
        None,
        out,
    )
    assert ok is True
    assert out.exists()
```

This passes once the applier tuple is wired: before the tuple exists, `legend_opacity` is silently ignored (test still passes trivially), so to make the test meaningfully *fail first*, temporarily assert the setter is reached — instead, verify the wiring by the grep in Step 2 and rely on the render succeeding. (The tuple is a one-line generic addition; Task 2 already proves the setter's effect.)

- [ ] **Step 2: Confirm current state and run the test**

Run: `grep -n "for key, setter in\|legend_scale\", view.set_legend_scale\|legend_opacity" src/starpost/batch/run.py`
Then: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_batch_run.py -k legend_opacity -v`
Expected: the render test PASSES already (opacity ignored); the grep shows no `legend_opacity` tuple yet.

- [ ] **Step 3: Add the applier tuple**

In `src/starpost/batch/run.py`, in the `for key, setter in (...)` loop (after `("legend_scale", view.set_legend_scale),` ~line 114):

```python
        ("legend_opacity", view.set_legend_opacity),
```

- [ ] **Step 4: Run the test again to confirm it still passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_batch_run.py -k legend_opacity -v`
Expected: PASS — and the grep from Step 2 now shows the `legend_opacity` tuple, confirming the wiring.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/batch/run.py tests/test_batch_run.py
git commit -m "feat: batch render applies captured legend_opacity"
```

---

### Task 8: Changelog + full-suite verification

**Files:**
- Modify: `CHANGELOG.md` (`## [Unreleased]` → `### New Features`)

- [ ] **Step 1: Add the changelog entry**

Under `## [Unreleased]` → `### New Features` in `CHANGELOG.md` (newest first), add:

```markdown
- **Legend transparency** — the box behind a plot legend can now be made
  see-through so curves show through it. Set the default under
  Settings ▸ Plots ▸ *Legend opacity* (default 20%), and override it per
  export with the *Legend opacity* slider in the Export and Run batch dialogs.
```

- [ ] **Step 2: Run ruff**

Run: `ruff check .`
Expected: no errors.

- [ ] **Step 3: Run the full test suite**

Run: `python scripts/run_tests.py`
Expected: all tests pass (headless: the runner already isolates each file; set `QT_QPA_PLATFORM=offscreen` if needed).

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for legend transparency"
```

---

## Manual verification (after all tasks)

Use the `verify` skill's headless recipe (offscreen `QApplication`, real `MainWindow`) to confirm end-to-end:
1. Open Settings ▸ Plots, set Legend opacity to 20% — the main plot's legend box is faintly see-through.
2. Raise it to 100% — the box becomes solid; lower to 0% — the box disappears while labels stay visible.
3. Open the Export dialog — the slider matches the setting; dragging it updates the preview legend.
4. Open Run batch, add a saved plot, reopen its Properties — "Legend opacity" shows the captured percent; the rendered image matches.
