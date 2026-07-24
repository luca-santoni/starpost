# Legend background transparency

**Date:** 2026-07-23
**Status:** Approved design

## Summary

Add a user-controllable opacity for the plot legend's background box, so plot
curves can show through the legend. The value is a persisted default on the
Plots settings tab and an override in both the single-plot Export dialog and the
Run batch dialog. Default is **20% opacity** (α ≈ 51/255): a faint, mostly
see-through box.

Only the legend's background box is affected. Label text and colour swatches
stay fully opaque and readable.

## Motivation

The legend can obscure curves behind it. Users want to fade the box so data
underneath stays visible, and to set a sensible default once rather than adjust
it per export.

## Approach

Follow the existing legend-property pattern already used for `legend_scale` and
`legend_offset`, which flows: Settings → live plot view → Export dialog → Run
batch dialog → batch render. The one addition beyond that pattern: opacity gets a
**persisted default** in `Settings` (unlike `legend_scale`, which has none),
because it is requested on the Plots settings tab.

"Opacity" controls the alpha of the legend's background box brush. The box is
coloured to match the plot background (translucent white in light mode,
translucent dark in dark mode), so it reads correctly in both themes.

## Components and data flow

### 1. Model — `core/settings.py`
- New field on `Settings`: `legend_opacity: float = 0.2` (fraction 0–1).
- `from_dict`: read `legend_opacity`, default `0.2`, clamp to `[0.0, 1.0]`.
- `to_dict`: serialize `legend_opacity`.
- Seed `legend_opacity: 0.2` into `config/default_settings.yaml`.

### 2. Plot rendering — `gui/views/plot_view.py`
- Store `self._legend_opacity = 0.2` in `__init__`.
- Add `set_legend_opacity(frac: float) -> None`: clamp to `[0,1]`, store, apply.
- Add private `_apply_legend_brush() -> None`:
  `self._legend.setBrush(pg.mkBrush(<bg rgb>, alpha=round(frac * 255)))`,
  where `<bg rgb>` derives from the current `self._bg` background colour.
- Call `_apply_legend_brush()` from both `set_legend_opacity` and `apply_theme`
  (so the box re-tints to the new background colour on a theme switch while
  keeping the chosen opacity). The brush lives on the legend item, so it
  persists across `_render()` without re-setting each render.

### 3. Settings UI — `gui/views/settings_dialog.py` (Plots page)
- Add a `QSpinBox`, range 0–100, suffix `%`, default 20, labelled
  "Legend opacity".
- Add a hint label: "Opacity of the box behind the plot legend; lower = more
  see-through."
- Wire into the dialog's load (settings → spinbox, value = `round(frac*100)`)
  and collect (spinbox → settings, `frac = value/100`) alongside the other plot
  fields.

### 4. Live application — `gui/main_window.py`
- In `_apply_settings_to_views()` add
  `self.plot_view.set_legend_opacity(self.settings.legend_opacity)`, and apply it
  on the startup settings-apply path too, so a settings change updates the main
  plot immediately (not only on export).

### 5. Export dialog — `gui/views/export_dialog.py`
- Add a slider (0–100) next to "Legend scale", seeded from
  `settings.legend_opacity` (value = `round(frac*100)`), tooltip e.g.
  "Opacity of the legend background box".
- On change, call `self._preview.set_legend_opacity(value / 100)`.
- Write the value into the exported `plot_data` under `legend_opacity` (as a
  fraction 0–1).

### 6. Run batch dialog — `gui/views/batch_run_dialog.py`
- Add the same slider next to its "Legend scale", seeded from
  `settings.legend_opacity`, wired to `self._preview.set_legend_opacity`.
- Save the value into the plot capture's `plot_data["legend_opacity"]`.
- Restore it in `_apply_plot_data` (slider = `round(frac*100)`; missing key →
  default 0.2).
- Show it read-only in the saved-plot properties view (as a `%`), alongside the
  existing "Legend scale" row.

### 7. Batch render — `batch/run.py`
- Add `("legend_opacity", view.set_legend_opacity)` to the `_PLOT_APPLIERS`
  loop, so exported and batch-rendered images honour the captured value.

## Error handling and edge cases

- Clamp to `[0.0, 1.0]` (fraction) / `[0, 100]` (slider/spinbox) on load and
  input.
- A missing `legend_opacity` key in older settings or older `plot_data` →
  default `0.2`.
- Slider ↔ fraction conversion uses simple `value/100` and `round(frac*100)`
  helpers, mirroring the existing `_legend_factor` / `_legend_slider` idiom in
  the Export and Run batch dialogs.

## Testing

- `tests/test_settings.py`: round-trip `legend_opacity` — default value, a custom
  value, clamping of an out-of-range value, and missing-key default.
- Plot view test: `set_legend_opacity` sets the legend background brush alpha;
  `apply_theme` preserves the chosen opacity while changing the box colour.
- Batch render / plot-data test: `legend_opacity` present in `plot_data` reaches
  the rendered legend's brush.
- Update `CHANGELOG.md` (newest first) with the user-facing change.

## Out of scope (YAGNI)

- Per-series legend fade.
- Legend border / pen opacity (only the fill box is controlled).
- Animating the opacity change.
