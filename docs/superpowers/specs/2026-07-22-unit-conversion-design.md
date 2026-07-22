# Unit conversion for reports and plots

**Date:** 2026-07-22
**Status:** Approved design, pending implementation plan

## Goal

Let the user view report values and monitor plots converted into a consistent
unit system. Three choices everywhere conversion is offered:

- **Default** — no conversion; show the raw units STAR-CCM+ extracted.
- **SI** — strict base SI (N, Pa, m, kg, K, m/s, W, …).
- **Imperial** — engineering Imperial (lbf, psi, ft, lb, °F, ft/s, hp, …).

Conversion is a **display/export transform**, never a mutation of stored data:
the cached `SimResult` always holds the raw extracted values, honouring the
"STAR-CCM+ runs once, everything after is cached" invariant. Selecting a
different system re-renders from the same cached data.

## Where conversion applies

| Surface | Control | Granularity |
|---|---|---|
| Main-UI Reports table (single + comparison) | Settings dropdown `report_unit_system` | Global |
| Main-UI monitor plots | Settings dropdown `plot_unit_system` | Global |
| Run-batch report tables | Batch window dropdown | Global (per batch run) |
| Run-batch saved plots | Per-plot dropdown, captured into the saved plot | Per plot |

**Explicitly out of scope** (stay in raw units): the Export dialog's report
tables, the Data tab / portable CSV, and scene/media outputs. This matches the
decision that the main-UI reports dropdown affects only the live Reports table.

## Approach

Approach A — an internal, dependency-free unit table. No `pint` or other
library: the set of quantities that appear in CFD reports/monitors is small and
well known, STAR-CCM+'s unit notations (`N-m`, `m^3/s`, `lbf-ft`) are
idiosyncratic enough that a library would need a translation layer anyway, and a
new dependency conflicts with the repo's startup-latency and PyInstaller
constraints. The existing `_UNIT_QUANTITY` map in `plot_view.py` already
classifies units by quantity and becomes the seed for the registry.

Two principles:

1. **Non-destructive.** `SimResult` is never rewritten. Conversion happens on
   the way out to a table or a plot.
2. **Pass-through.** Any unit not in the registry — including dimensionless
   coefficients (`Cd`, `Cl`), blank units, and exotic units — is shown
   unchanged under every system. A value already in the target unit resolves to
   itself.

## Section 1 — Core module `core/units.py`

A new pure-Python module, the single source of truth for units. The
`_UNIT_QUANTITY` map moves here; `plot_view.py` / `plot_style.py` import from
here so classification and conversion cannot drift apart. The module has no Qt
or pyqtgraph imports, so it is safe to import from the pyqtgraph-free
`plot_style` path.

### Data

```python
class UnitSystem(str, Enum):
    DEFAULT = "default"
    SI = "si"
    IMPERIAL = "imperial"

@dataclass(frozen=True)
class UnitDef:
    quantity: str      # "Force", "Pressure", "Temperature", …
    factor: float      # base = raw * factor + offset
    offset: float = 0.0   # non-zero only for affine (temperature) units

# unit string (as STAR-CCM+ emits it) -> UnitDef
_UNITS: dict[str, UnitDef]

# quantity -> canonical target unit per system
_TARGETS: dict[str, dict[str, str]]   # {"Force": {"si": "N", "imperial": "lbf"}, …}
```

`base = raw * factor + offset` reaches the quantity's SI base unit. Reverse:
`target = (base - target_offset) / target_factor`. For a pure scale unit
`offset == 0`, so both directions are single multiplies.

### Canonical target table

Base unit is the SI unit of each quantity (used internally as the pivot).

| Quantity | Base | SI target | Imperial target |
|---|---|---|---|
| Force | N | N | lbf |
| Moment | N-m | N-m | lbf-ft |
| Pressure | Pa | Pa | psi |
| Mass Flow | kg/s | kg/s | lb/s |
| Volumetric Flow Rate | m^3/s | m^3/s | cfm |
| Velocity | m/s | m/s | ft/s |
| Temperature | K | K | degF |
| Mass | kg | kg | lb |
| Power | W | W | hp |
| Energy | J | J | BTU |
| Length | m | m | ft |
| Density | kg/m^3 | kg/m^3 | lb/ft^3 |
| Angular Velocity | rad/s | rad/s | rpm |
| Frequency | Hz | Hz | Hz |
| Time | s | s | s |

Quantities whose SI and Imperial target are identical (Frequency, Time) are
effectively pass-through for both systems but are listed so the registry stays
explicit. The registry seeds every unit already present in `_UNIT_QUANTITY`
plus the target units above; the exact factor list is filled in during
implementation against reference constants (e.g. 1 lbf = 4.4482216152605 N,
1 psi = 6894.757293168 Pa, K↔°F affine).

### Public API

```python
def convert_value(value: float | None, unit: str, system: UnitSystem
                  ) -> tuple[float | None, str]:
    """(converted_value, target_unit). Returns the input unchanged when
    system is DEFAULT, value is None, the unit is unknown/blank, or the
    quantity has no target for this system."""

def convert_series(ys: Sequence[float], unit: str, system: UnitSystem
                   ) -> tuple[list[float], str]:
    """convert_value applied across a plot series' y-values."""

def quantity_for_unit(unit: str) -> str:
    """Relocated classifier ('lbf' -> 'Force', '' if unknown), used by the
    Y-axis labeller."""
```

Unit lookup strips surrounding whitespace and matches the registry keys
case-sensitively (so `kN` (force) stays distinct from `kn` (knot)), matching
the existing `_UNIT_QUANTITY` behaviour.

## Section 2 — Settings & saved-plot data

### `Settings` (persisted YAML)

Two new fields, validated in `from_dict`/`to_dict` to the three allowed values
(anything else coerces to `"default"`):

```python
report_unit_system: str = "default"   # live Reports table
plot_unit_system: str = "default"     # all live monitor plots (global)
```

### Saved plot (`_capture_plot` dict)

Add `"unit_system"` to the captured dict. `_apply_plot` restores it into the
per-plot control; `render_saved_plot` applies it. Saved plots written before
this feature lack the key and default to `"default"`.

### `BatchProfile`

Add `report_unit_system: str = "default"`, round-tripped in
`save`/`load`, feeding the batch report tables.

## Section 3 — Reports wiring (main UI)

- `report_table.py` receives the active unit system (from `main_window`, which
  owns `Settings`). In `show_single`, each report's `(value, units)` passes
  through `convert_value` before the DataFrame is built: the value column shows
  the converted number, the units column the converted unit. The comparison
  view builds its `"Name [unit]"` row labels from converted values the same way.
- Sorting, decimal formatting, and zero-hiding operate on the converted values,
  which is correct because those are what the user sees.
- Settings dialog: a **Reports unit system** dropdown (Default / SI / Imperial).
  Changing it saves the setting and refreshes the Reports table.

## Section 4 — Plots wiring

### Main UI (global)

- `PlotView`'s render entry points take a `unit_system`. At draw time each
  series' unit is read from its name via `_series_unit` and its y-array is
  converted with `convert_series`. Conversion is **per series**, so a rare
  mixed-quantity plot converts each series by its own quantity.
- The Y-axis label (`_y_label_for`) is computed from the converted units, so it
  reads e.g. `Force (lbf)` after conversion.
- Hover read-outs and the Shift+drag region-statistics table compute on the
  drawn (converted) array, so they follow automatically.
- Settings dialog: a **Plots unit system** dropdown; changing it redraws the
  visible plots.

### Batch (per-plot)

- The Plots tab of the Run-batch dialog gains a per-plot unit-system dropdown.
  `_capture_plot` stores the selection, `_apply_plot` restores it, and
  `render_saved_plot` converts each series before drawing the `PlotView`.
- The batch window's single global **Reports unit system** dropdown feeds
  `aggregator.reports_wide_frame` / the long-frame builder so the batch report
  tables convert, independent of the main-UI setting.

## Section 5 — Testing & docs

- **`tests/test_units.py`** — the core:
  - Scale conversions: force (N↔lbf), pressure (Pa↔psi), velocity (m/s↔ft/s).
  - Temperature affine both directions with a known pivot (e.g. 300 K → 80.33 °F
    → back to 300 K within tolerance).
  - Compound units (`N-m` → `lbf-ft`).
  - Pass-through: unknown unit, blank unit, dimensionless coefficient.
  - `DEFAULT` is a no-op; converting a value already in the target unit is
    idempotent.
- **Settings** round-trip test for the two new fields, including a bad value
  coercing to `"default"`.
- **Reports** test: the table converts value + unit under SI and Imperial.
- **Plots** test: `convert_series` scales y-data and `_y_label_for` reflects the
  converted unit.
- **Batch** test: the saved-plot dict round-trips `unit_system`; `BatchProfile`
  round-trips `report_unit_system`.
- **`CHANGELOG.md`** entry in the existing style.
- No keyboard-shortcut changes, so `docs/starpost_hotkeys.txt` and its test are
  untouched.

## Non-goals

- Converting exports, portable CSV, or scene/media outputs.
- User-editable conversion tables or custom target units.
- Per-report unit overrides in the main UI (reports are global there).
- Converting the X axis of plots (iteration/time stays as-is).
