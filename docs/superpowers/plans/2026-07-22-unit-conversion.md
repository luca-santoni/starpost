# Unit Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users view report values and monitor plots converted into Default (no change), SI, or Imperial units, controlled by Settings dropdowns in the main UI and by per-plot / global-reports selectors in the Run-batch window.

**Architecture:** A new dependency-free `core/units.py` is the single source of truth: a registry mapping each known unit string to `(quantity, factor, offset)` plus a per-quantity canonical target for SI/Imperial. Conversion is a pure `raw → base → target` transform applied at display/export time only — the cached `SimResult` is never mutated. Reports convert in the aggregator/report-table; plots convert per-series inside `PlotView` at draw time.

**Tech Stack:** Python 3.11, PySide6, pyqtgraph, pandas, pytest, ruff, YAML settings.

## Global Constraints

- Brand is **StarPost**; package/command identifier is lowercase `starpost`.
- Line length 100, ruff target py311. Run `ruff check .` clean.
- Run the full suite with `python scripts/run_tests.py` (not bare `pytest`); a single file may use `python -m pytest tests/test_x.py`. Headless: prefix `QT_QPA_PLATFORM=offscreen`.
- Commit after every task. Log user-facing changes in `CHANGELOG.md` (newest first), matching existing style.
- No new third-party dependencies. Keep heavy imports (pandas, numpy, pyqtgraph, jinja2) off module top level unless already on the startup path — `core/units.py` must be pure-Python with no such imports.
- The cached `SimResult` is never rewritten; conversion is display/export only.
- The three unit-system values are the exact strings `"default"`, `"si"`, `"imperial"`. Any other value coerces to `"default"`.
- Conversion scope (per approved spec): main-UI **Reports table** (single + comparison) and **monitor plots**; Run-batch report tables and saved plots. **Out of scope** — the Export dialog, Data-tab / portable CSV, and scene/media outputs stay in raw units.
- No keyboard-shortcut changes, so `src/starpost/gui/shortcuts.py` and `docs/starpost_hotkeys.txt` are untouched.

---

### Task 1: Core units module

**Files:**
- Create: `src/starpost/core/units.py`
- Test: `tests/test_units.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class UnitSystem(str, Enum)` with `DEFAULT = "default"`, `SI = "si"`, `IMPERIAL = "imperial"`.
  - `VALID_SYSTEMS: frozenset[str]` = `{"default", "si", "imperial"}`.
  - `normalize_system(system) -> str` — returns a member of `VALID_SYSTEMS`, coercing anything else to `"default"`.
  - `conversion_factors(unit: str, system) -> tuple[float, float, str]` — returns `(factor, shift, target_unit)` such that `converted = raw * factor + shift`. Identity `(1.0, 0.0, unit)` when no conversion applies.
  - `convert_value(value: float | None, unit: str, system) -> tuple[float | None, str]`.
  - `convert_series(ys, unit: str, system) -> tuple[list[float], str]`.
  - `target_unit(unit: str, system) -> str`.
  - `quantity_for_unit(unit: str) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_units.py`:

```python
import math

import pytest

from starpost.core import units as u


def test_default_is_a_no_op():
    assert u.convert_value(12.0, "N", "default") == (12.0, "N")


def test_force_si_to_imperial():
    val, unit = u.convert_value(100.0, "N", "imperial")
    assert unit == "lbf"
    assert val == pytest.approx(22.4808943, rel=1e-6)


def test_force_imperial_unit_to_si():
    val, unit = u.convert_value(10.0, "lbf", "si")
    assert unit == "N"
    assert val == pytest.approx(44.48221615, rel=1e-6)


def test_pressure_pa_to_psi():
    val, unit = u.convert_value(6894.757293168, "Pa", "imperial")
    assert unit == "psi"
    assert val == pytest.approx(1.0, rel=1e-9)


def test_velocity_ms_to_fts():
    val, unit = u.convert_value(1.0, "m/s", "imperial")
    assert unit == "ft/s"
    assert val == pytest.approx(3.280839895, rel=1e-6)


def test_temperature_kelvin_to_fahrenheit_affine():
    val, unit = u.convert_value(300.0, "K", "imperial")
    assert unit == "degF"
    assert val == pytest.approx(80.33, abs=1e-2)


def test_temperature_round_trip_back_to_kelvin():
    f_val, _ = u.convert_value(300.0, "K", "imperial")   # -> degF
    k_val, unit = u.convert_value(f_val, "degF", "si")   # -> K
    assert unit == "K"
    assert k_val == pytest.approx(300.0, abs=1e-6)


def test_compound_moment_unit():
    val, unit = u.convert_value(1.35581794833, "N-m", "imperial")
    assert unit == "lbf-ft"
    assert val == pytest.approx(1.0, rel=1e-6)


def test_unknown_unit_passes_through():
    assert u.convert_value(5.0, "widgets", "si") == (5.0, "widgets")


def test_dimensionless_and_blank_pass_through():
    assert u.convert_value(0.42, "", "imperial") == (0.42, "")
    assert u.convert_value(0.42, "Cd", "imperial") == (0.42, "Cd")


def test_already_in_target_unit_is_identity():
    assert u.convert_value(50.0, "N", "si") == (50.0, "N")


def test_none_value_keeps_shape_and_reports_target_unit():
    val, unit = u.convert_value(None, "N", "imperial")
    assert val is None
    assert unit == "lbf"


def test_convert_series_scales_every_point():
    ys, unit = u.convert_series([0.0, 100.0], "N", "imperial")
    assert unit == "lbf"
    assert ys[0] == pytest.approx(0.0)
    assert ys[1] == pytest.approx(22.4808943, rel=1e-6)


def test_target_unit_only():
    assert u.target_unit("Pa", "imperial") == "psi"
    assert u.target_unit("Pa", "default") == "Pa"
    assert u.target_unit("widgets", "si") == "widgets"


def test_quantity_for_unit():
    assert u.quantity_for_unit("lbf") == "Force"
    assert u.quantity_for_unit("widgets") == ""


def test_normalize_system_coerces_bad_values():
    assert u.normalize_system("SI") == "si"
    assert u.normalize_system("nonsense") == "default"
    assert u.normalize_system(None) == "default"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_units.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'starpost.core.units'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/starpost/core/units.py`:

```python
"""Unit classification and conversion — the single source of truth for units.

Pure Python, no Qt / numpy / pandas imports (safe to import anywhere, incl. the
startup and pyqtgraph-free paths). Conversion is a display/export transform:
``converted = raw * factor + shift``. Callers pass one of the three system
strings ("default" | "si" | "imperial"); "default" and any unknown unit are
identity (the value and its unit pass through unchanged).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class UnitSystem(str, Enum):
    DEFAULT = "default"
    SI = "si"
    IMPERIAL = "imperial"


VALID_SYSTEMS = frozenset(s.value for s in UnitSystem)


def normalize_system(system) -> str:
    """A member of VALID_SYSTEMS, coercing anything else to "default"."""
    if isinstance(system, UnitSystem):
        return system.value
    text = str(system).strip().lower() if system is not None else ""
    return text if text in VALID_SYSTEMS else "default"


@dataclass(frozen=True)
class _UnitDef:
    quantity: str
    factor: float   # base = raw * factor + offset  (base is the SI unit)
    offset: float = 0.0   # non-zero only for affine (temperature) units


# unit string (exactly as STAR-CCM+ emits it) -> how to reach the SI base unit.
# Matched case-sensitively so kN (force) stays distinct from kn (knot).
_UNITS: dict[str, _UnitDef] = {
    # Force (base N)
    "N": _UnitDef("Force", 1.0), "kN": _UnitDef("Force", 1e3),
    "MN": _UnitDef("Force", 1e6), "dyn": _UnitDef("Force", 1e-5),
    "kgf": _UnitDef("Force", 9.80665), "lbf": _UnitDef("Force", 4.4482216152605),
    # Moment / torque (base N-m)
    "N-m": _UnitDef("Moment", 1.0), "N*m": _UnitDef("Moment", 1.0),
    "Nm": _UnitDef("Moment", 1.0),
    "lbf-ft": _UnitDef("Moment", 1.35581794833),
    "lbf*ft": _UnitDef("Moment", 1.35581794833),
    "lbf-in": _UnitDef("Moment", 0.112984829027),
    "lbf*in": _UnitDef("Moment", 0.112984829027),
    # Pressure (base Pa)
    "Pa": _UnitDef("Pressure", 1.0), "kPa": _UnitDef("Pressure", 1e3),
    "MPa": _UnitDef("Pressure", 1e6), "hPa": _UnitDef("Pressure", 1e2),
    "bar": _UnitDef("Pressure", 1e5), "mbar": _UnitDef("Pressure", 1e2),
    "atm": _UnitDef("Pressure", 101325.0), "psi": _UnitDef("Pressure", 6894.757293168),
    # Mass flow (base kg/s)
    "kg/s": _UnitDef("Mass Flow", 1.0), "g/s": _UnitDef("Mass Flow", 1e-3),
    "kg/h": _UnitDef("Mass Flow", 1.0 / 3600.0),
    "lb/s": _UnitDef("Mass Flow", 0.45359237),
    "lbm/s": _UnitDef("Mass Flow", 0.45359237),
    # Volumetric flow (base m^3/s)
    "m^3/s": _UnitDef("Volumetric Flow Rate", 1.0),
    "m3/s": _UnitDef("Volumetric Flow Rate", 1.0),
    "L/s": _UnitDef("Volumetric Flow Rate", 1e-3),
    "cfm": _UnitDef("Volumetric Flow Rate", 0.0004719474432),
    "gpm": _UnitDef("Volumetric Flow Rate", 6.30901964e-5),
    # Velocity (base m/s)
    "m/s": _UnitDef("Velocity", 1.0), "km/h": _UnitDef("Velocity", 1.0 / 3.6),
    "ft/s": _UnitDef("Velocity", 0.3048), "mph": _UnitDef("Velocity", 0.44704),
    # Temperature (base K) — affine
    "K": _UnitDef("Temperature", 1.0, 0.0),
    "degC": _UnitDef("Temperature", 1.0, 273.15),
    "C": _UnitDef("Temperature", 1.0, 273.15),
    "degF": _UnitDef("Temperature", 5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0),
    "F": _UnitDef("Temperature", 5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0),
    "R": _UnitDef("Temperature", 5.0 / 9.0, 0.0),
    # Mass (base kg)
    "kg": _UnitDef("Mass", 1.0), "g": _UnitDef("Mass", 1e-3),
    "mg": _UnitDef("Mass", 1e-6), "lb": _UnitDef("Mass", 0.45359237),
    "lbm": _UnitDef("Mass", 0.45359237),
    # Power (base W) / energy (base J)
    "W": _UnitDef("Power", 1.0), "kW": _UnitDef("Power", 1e3),
    "MW": _UnitDef("Power", 1e6), "hp": _UnitDef("Power", 745.699871582),
    "J": _UnitDef("Energy", 1.0), "kJ": _UnitDef("Energy", 1e3),
    "MJ": _UnitDef("Energy", 1e6), "BTU": _UnitDef("Energy", 1055.05585262),
    # Length (base m)
    "m": _UnitDef("Length", 1.0), "mm": _UnitDef("Length", 1e-3),
    "cm": _UnitDef("Length", 1e-2), "km": _UnitDef("Length", 1e3),
    "in": _UnitDef("Length", 0.0254), "ft": _UnitDef("Length", 0.3048),
    # Density (base kg/m^3)
    "kg/m^3": _UnitDef("Density", 1.0), "kg/m3": _UnitDef("Density", 1.0),
    "lb/ft^3": _UnitDef("Density", 16.018463374),
    # Angular velocity (base rad/s)
    "rad/s": _UnitDef("Angular Velocity", 1.0),
    "deg/s": _UnitDef("Angular Velocity", 0.0174532925199),
    "rpm": _UnitDef("Angular Velocity", 0.10471975512),
    # Frequency (base Hz) / time (base s) — SI and Imperial targets identical
    "Hz": _UnitDef("Frequency", 1.0), "kHz": _UnitDef("Frequency", 1e3),
    "s": _UnitDef("Time", 1.0), "ms": _UnitDef("Time", 1e-3),
    "min": _UnitDef("Time", 60.0), "hr": _UnitDef("Time", 3600.0),
}

# Canonical target unit for each quantity, per system.
_TARGETS: dict[str, dict[str, str]] = {
    "Force": {"si": "N", "imperial": "lbf"},
    "Moment": {"si": "N-m", "imperial": "lbf-ft"},
    "Pressure": {"si": "Pa", "imperial": "psi"},
    "Mass Flow": {"si": "kg/s", "imperial": "lb/s"},
    "Volumetric Flow Rate": {"si": "m^3/s", "imperial": "cfm"},
    "Velocity": {"si": "m/s", "imperial": "ft/s"},
    "Temperature": {"si": "K", "imperial": "degF"},
    "Mass": {"si": "kg", "imperial": "lb"},
    "Power": {"si": "W", "imperial": "hp"},
    "Energy": {"si": "J", "imperial": "BTU"},
    "Length": {"si": "m", "imperial": "ft"},
    "Density": {"si": "kg/m^3", "imperial": "lb/ft^3"},
    "Angular Velocity": {"si": "rad/s", "imperial": "rpm"},
    "Frequency": {"si": "Hz", "imperial": "Hz"},
    "Time": {"si": "s", "imperial": "s"},
}

_IDENTITY = (1.0, 0.0)


def quantity_for_unit(unit: str) -> str:
    """The physical quantity a unit measures ("lbf" -> "Force"), "" if unknown."""
    d = _UNITS.get((unit or "").strip())
    return d.quantity if d else ""


def conversion_factors(unit: str, system) -> tuple[float, float, str]:
    """(factor, shift, target_unit): converted = raw * factor + shift.

    Identity (1.0, 0.0, unit) when system is default, the unit is unknown, its
    quantity has no target for this system, or it is already the target unit."""
    key = (unit or "").strip()
    sys = normalize_system(system)
    if sys == "default":
        return (*_IDENTITY, key)
    src = _UNITS.get(key)
    if src is None:
        return (*_IDENTITY, key)
    tgt_name = _TARGETS.get(src.quantity, {}).get(sys)
    if not tgt_name or tgt_name == key:
        return (*_IDENTITY, key)
    tgt = _UNITS[tgt_name]
    # base = raw*f_u + o_u ; target = (base - o_t)/f_t
    factor = src.factor / tgt.factor
    shift = (src.offset - tgt.offset) / tgt.factor
    return (factor, shift, tgt_name)


def convert_value(value, unit: str, system) -> tuple:
    """(converted_value, target_unit). value None -> (None, target_unit)."""
    factor, shift, tgt = conversion_factors(unit, system)
    if value is None:
        return (None, tgt)
    return (value * factor + shift, tgt)


def convert_series(ys: Sequence[float], unit: str, system) -> tuple[list, str]:
    """convert_value applied across a series' y-values."""
    factor, shift, tgt = conversion_factors(unit, system)
    return ([v * factor + shift for v in ys], tgt)


def target_unit(unit: str, system) -> str:
    """The unit a value in ``unit`` becomes under ``system`` (``unit`` itself
    when no conversion applies)."""
    return conversion_factors(unit, system)[2]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_units.py -q && ruff check src/starpost/core/units.py tests/test_units.py`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/core/units.py tests/test_units.py
git commit -m "feat: core unit conversion registry (core/units.py)"
```

---

### Task 2: Settings fields

**Files:**
- Modify: `src/starpost/core/settings.py` (`Settings` dataclass, `from_dict`, `to_dict`)
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `starpost.core.units.normalize_system`.
- Produces: `Settings.report_unit_system: str = "default"` and `Settings.plot_unit_system: str = "default"`, both validated to `VALID_SYSTEMS` on load/save.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settings.py`:

```python
def test_unit_system_defaults_and_round_trip():
    s = Settings()
    assert s.report_unit_system == "default"
    assert s.plot_unit_system == "default"
    s.report_unit_system = "imperial"
    s.plot_unit_system = "si"
    restored = Settings.from_dict(s.to_dict())
    assert restored.report_unit_system == "imperial"
    assert restored.plot_unit_system == "si"


def test_unit_system_bad_value_coerces_to_default():
    restored = Settings.from_dict(
        {"report_unit_system": "furlongs", "plot_unit_system": 5}
    )
    assert restored.report_unit_system == "default"
    assert restored.plot_unit_system == "default"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings.py::test_unit_system_defaults_and_round_trip -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'report_unit_system'`.

- [ ] **Step 3: Write minimal implementation**

In `src/starpost/core/settings.py`, add two fields to the `Settings` dataclass (next to `export_plot_theme`, near line 224):

```python
    # Unit system for the live views ("default" | "si" | "imperial").
    report_unit_system: str = "default"   # main-UI Reports table
    plot_unit_system: str = "default"     # main-UI monitor plots
```

In `from_dict` (in the `cls(...)` call, alongside `export_plot_theme=...`), add:

```python
            report_unit_system=_norm_unit_system(d.get("report_unit_system")),
            plot_unit_system=_norm_unit_system(d.get("plot_unit_system")),
```

In `to_dict` (alongside `"export_plot_theme": ...`), add:

```python
            "report_unit_system": self.report_unit_system,
            "plot_unit_system": self.plot_unit_system,
```

Add a module-level helper near `clamp_text_scale` (top of the file) plus its import:

```python
from starpost.core.units import normalize_system as _norm_unit_system
```

(`normalize_system` already coerces bad values to `"default"`, so `_norm_unit_system` is just an alias import — do not redefine it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings.py -q && ruff check src/starpost/core/settings.py`
Expected: all pass, ruff clean. (`core/units` is pure-Python, so importing it at the top of `settings.py` adds no meaningful startup cost.)

- [ ] **Step 5: Commit**

```bash
git add src/starpost/core/settings.py tests/test_settings.py
git commit -m "feat: report_unit_system / plot_unit_system settings"
```

---

### Task 3: Reports conversion (aggregator + report table)

**Files:**
- Modify: `src/starpost/batch/aggregator.py` (`reports_wide_frame`, `reports_long_frame`)
- Modify: `src/starpost/gui/views/report_table.py` (`ReportTable`, `show_single`)
- Test: `tests/test_aggregator.py`, `tests/test_report_table.py` (create the latter if absent)

**Interfaces:**
- Consumes: `starpost.core.units.convert_value`.
- Produces:
  - `reports_wide_frame(results, selected=None, include_units=True, unit_system="default")` — values and embedded `[unit]` labels reflect `unit_system`.
  - `reports_long_frame(...)` — same new trailing `unit_system` parameter, passed through.
  - `ReportTable.set_unit_system(system: str)` — re-renders; `show_single` converts each report before building its frame.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_aggregator.py`:

```python
def test_wide_frame_converts_to_imperial():
    a = _sim("caseA", [("Drag Force", 100.0, "N")])
    df = reports_wide_frame([a], unit_system="imperial")
    assert "Drag Force [lbf]" in df.columns
    assert df.loc["caseA", "Drag Force [lbf]"] == pytest.approx(22.4808943, rel=1e-6)


def test_wide_frame_default_leaves_units_raw():
    a = _sim("caseA", [("Drag Force", 100.0, "N")])
    df = reports_wide_frame([a], unit_system="default")
    assert "Drag Force [N]" in df.columns
    assert df.loc["caseA", "Drag Force [N]"] == 100.0
```

Add `import pytest` to the top of `tests/test_aggregator.py` if it is not already imported.

Create `tests/test_report_table.py`:

```python
import pytest
from PySide6.QtWidgets import QApplication

from starpost.data.models import Report, SimResult
from starpost.gui.views.report_table import ReportTable


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _model_rows(table: ReportTable):
    model = table._table.model()
    cols = model.columnCount()
    return [
        [model.data(model.index(r, c)) for c in range(cols)]
        for r in range(model.rowCount())
    ]


def test_show_single_converts_value_and_unit(app):
    res = SimResult(sim_path="/x/a.sim", reports=[Report("Drag", 100.0, "N")])
    table = ReportTable(decimals=4)
    table.set_unit_system("imperial")
    table.show_single(res)
    rows = _model_rows(table)
    # Columns: Report, <value>, Units
    assert rows[0][0] == "Drag"
    assert rows[0][2] == "lbf"
    assert float(rows[0][1]) == pytest.approx(22.4809, abs=1e-3)


def test_show_single_default_is_raw(app):
    res = SimResult(sim_path="/x/a.sim", reports=[Report("Drag", 100.0, "N")])
    table = ReportTable(decimals=4)
    table.show_single(res)
    rows = _model_rows(table)
    assert rows[0][2] == "N"
    assert float(rows[0][1]) == pytest.approx(100.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_aggregator.py::test_wide_frame_converts_to_imperial tests/test_report_table.py -q`
Expected: FAIL — `reports_wide_frame() got an unexpected keyword argument 'unit_system'` and `ReportTable has no attribute set_unit_system`.

- [ ] **Step 3a: Implement aggregator conversion**

In `src/starpost/batch/aggregator.py`, add the import at the top:

```python
from starpost.core.units import convert_value
```

Change `reports_wide_frame`'s signature and body:

```python
def reports_wide_frame(
    results: list[SimResult],
    selected: Optional[set[str]] = None,
    include_units: bool = True,
    unit_system: str = "default",
) -> pd.DataFrame:
    """Wide report table: rows = sims, columns = "Report [units]" (units embedded
    only when ``include_units``). Values and embedded units are converted to
    ``unit_system`` ("default" | "si" | "imperial")."""
    units: dict[str, str] = {}
    rows: list[dict] = []
    for res in results:
        row: dict[str, object] = {"sim": res.sim_name}
        for rep in res.reports:
            if selected is not None and rep.name not in selected:
                continue
            value, unit = convert_value(rep.value, rep.units, unit_system)
            units.setdefault(rep.name, unit)
            row[rep.name] = value
        rows.append(row)

    df = pd.DataFrame(rows).set_index("sim") if rows else pd.DataFrame()
    if include_units:
        df = df.rename(
            columns={
                name: f"{name} [{units[name]}]" if units.get(name) else name
                for name in df.columns
            }
        )
    return df
```

Change `reports_long_frame` to accept and forward the parameter:

```python
def reports_long_frame(
    results: list[SimResult],
    selected: Optional[set[str]] = None,
    include_units: bool = True,
    unit_system: str = "default",
) -> pd.DataFrame:
    """Tall report table — the transpose of :func:`reports_wide_frame`."""
    wide = reports_wide_frame(results, selected, include_units, unit_system)
    if wide.empty:
        return pd.DataFrame(columns=["Report"])
    long = wide.T
    long.index.name = "Report"
    return long.reset_index()
```

- [ ] **Step 3b: Implement report-table conversion**

In `src/starpost/gui/views/report_table.py`:

Add to `ReportTable.__init__` (after `self._zero_threshold = zero_threshold`, near line 92):

```python
        self._unit_system = "default"
```

Add a setter next to `set_zero_threshold` (near line 116):

```python
    def set_unit_system(self, system: str) -> None:
        """Set the unit system used for the single-file view and re-render."""
        self._unit_system = system
        if self._df is not None and _SINGLE_COLUMNS.issubset(self._df.columns):
            # Comparison frames arrive pre-converted from the aggregator; only
            # the single-file frame is (re)built from raw reports here.
            pass
```

In `show_single` (near line 238) convert each report before building the frame. Replace the DataFrame construction:

```python
        from starpost.core.units import convert_value

        converted = [convert_value(r.value, r.units, self._unit_system) for r in reports]
        df = pd.DataFrame(
            [
                {"report": r.name, "value": v, "units": unit}
                for r, (v, unit) in zip(reports, converted)
            ],
            columns=["report", "value", "units"],
        )
```

Note: `set_unit_system` cannot re-render the single view by itself (it does not keep the source `SimResult`), so the main window calls `show_single` again after changing the system — see Task 5. The `pass` branch documents that comparison frames are already converted upstream.

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_aggregator.py tests/test_report_table.py -q && ruff check src/starpost/batch/aggregator.py src/starpost/gui/views/report_table.py`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/batch/aggregator.py src/starpost/gui/views/report_table.py tests/test_aggregator.py tests/test_report_table.py
git commit -m "feat: convert report values/units in aggregator and report table"
```

---

### Task 4: Plot conversion (PlotView)

**Files:**
- Modify: `src/starpost/gui/views/plot_view.py` (`_UNIT_QUANTITY` removal, `_quantity_for_unit`, `_y_label_for`, `PlotView.set_unit_system`, `_render_single`, `_render_comparison`)
- Test: `tests/test_plot_view.py`

**Interfaces:**
- Consumes: `starpost.core.units.conversion_factors`, `target_unit`, `quantity_for_unit`.
- Produces: `PlotView.set_unit_system(system: str)` (re-renders the current plot); `_y_label_for(names, system="default")` reflects converted units.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plot_view.py`:

```python
def test_y_label_reflects_converted_unit():
    names = ["Drag (N)"]
    assert _y_label_for(names) == "Force (N)"
    assert _y_label_for(names, "imperial") == "Force (lbf)"


def test_set_unit_system_converts_drawn_y_values(app):
    from starpost.data.models import MonitorPlot, PlotSeries

    pv = PlotView()
    plot = MonitorPlot(
        name="Drag", series=[PlotSeries(name="Drag (N)", x=[1, 2], y=[100.0, 200.0])]
    )
    pv.set_unit_system("imperial")
    pv.show_plots([plot])
    # The recorded (drawn) curve holds converted y-values.
    ys = list(pv._curves[-1]["y"])
    assert ys[0] == pytest.approx(22.4808943, rel=1e-6)
    assert ys[1] == pytest.approx(44.9617886, rel=1e-6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_plot_view.py::test_y_label_reflects_converted_unit tests/test_plot_view.py::test_set_unit_system_converts_drawn_y_values -q`
Expected: FAIL — `_y_label_for() takes 1 positional argument` / `PlotView has no attribute set_unit_system`.

- [ ] **Step 3a: Route quantity classification through core/units**

In `src/starpost/gui/views/plot_view.py`, delete the `_UNIT_QUANTITY` dict (lines ~105–144) and replace `_quantity_for_unit` (lines ~147–150) with a re-export:

```python
from starpost.core.units import (
    conversion_factors,
    quantity_for_unit as _quantity_for_unit,
    target_unit,
)
```

(Add this import near the existing `from starpost.gui.plot_style import ...` block. Keep `_quantity_for_unit` as the local name so the rest of the module is unchanged.)

- [ ] **Step 3b: Convert the Y-axis label**

Replace `_y_label_for` (near line 153):

```python
def _y_label_for(names: list[str], system: str = "default") -> str:
    """Y-axis label from the plotted series' units, converted to ``system``:
    "<Quantity> (<unit>)" when they share one known unit, the unit alone when
    unknown, "Value" when units are mixed or absent."""
    units = {
        target_unit(u, system)
        for u in (_series_unit(n) for n in names)
        if u
    }
    if len(units) != 1:
        return "Value"
    unit = next(iter(units))
    quantity = _quantity_for_unit(unit)
    return f"{quantity} ({unit})" if quantity else unit
```

- [ ] **Step 3c: Add the setter and convert drawn series**

In `PlotView.__init__` (near line 471, alongside other display state), add:

```python
        self._unit_system = "default"
```

Add a setter next to `set_smooth_width` (near line 694):

```python
    def set_unit_system(self, system: str) -> None:
        """Set the unit system applied to drawn plot data and re-render."""
        self._unit_system = system
        self._render()
```

(`self._render()` is the existing re-render entry point at line ~1078 that dispatches to `_render_single` / `_render_comparison`. Verify the method name with `grep -n "def _render\b" src/starpost/gui/views/plot_view.py` and use whatever it is called; the two `_render_*` methods are dispatched from it.)

Add a private helper near `_smoothed` (near line 712):

```python
    def _converted(self, name: str, y):
        """Scale a series' y-values into the active unit system (per-series, by
        the unit parsed from its name). Returns a numpy array."""
        factor, shift, _ = conversion_factors(_series_unit(name), self._unit_system)
        return np.asarray(y, dtype=float) * factor + shift
```

In `_render_single` (near line 1099), convert before smoothing. Change:

```python
                x, y = _series_arrays(s)
                specs.append((x, self._smoothed(y), s.name, color))
```

to:

```python
                x, y = _series_arrays(s)
                y = self._converted(s.name, y)
                specs.append((x, self._smoothed(y), s.name, color))
```

And update its `_reset` call to pass the system:

```python
        self._reset(title, any(p.y_log for p in plots), _y_label_for(drawn, self._unit_system))
```

In `_render_comparison` (near line 1157), apply the same two changes. Change:

```python
                    x, y = _series_arrays(s)
                    specs.append((x, self._smoothed(y), label, color))
```

to:

```python
                    x, y = _series_arrays(s)
                    y = self._converted(s.name, y)
                    specs.append((x, self._smoothed(y), label, color))
```

and:

```python
        self._reset(title, y_log, _y_label_for(drawn, self._unit_system))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_plot_view.py -q && ruff check src/starpost/gui/views/plot_view.py`
Expected: all pass, ruff clean. (Region stats and hover read on the recorded curves, which now hold converted values, so they follow automatically.)

- [ ] **Step 5: Commit**

```bash
git add src/starpost/gui/views/plot_view.py tests/test_plot_view.py
git commit -m "feat: per-series unit conversion in PlotView + converted Y label"
```

---

### Task 5: Wire main-UI settings dropdowns + apply to views

**Files:**
- Modify: `src/starpost/gui/views/settings_dialog.py` (`_build_reports_page`, `_build_plots_page`, load path near line 1580, save path near line 1653)
- Modify: `src/starpost/gui/main_window.py` (report-table construction near line 145, plot_view construction near line 210, `_apply_settings_to_views` near line 1742, report render near line 1438)
- Test: `tests/test_settings_dialog.py` (create if absent)

**Interfaces:**
- Consumes: `Settings.report_unit_system`, `Settings.plot_unit_system`, `ReportTable.set_unit_system`, `PlotView.set_unit_system`.
- Produces: two `QComboBox`es on the Settings Reports/Plots pages that load from and save to the settings.

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_dialog.py`:

```python
import pytest
from PySide6.QtWidgets import QApplication

from starpost.core.settings import Settings
from starpost.gui.views.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_unit_dropdowns_load_and_save(app):
    s = Settings()
    s.report_unit_system = "imperial"
    s.plot_unit_system = "si"
    dlg = SettingsDialog(s, None)
    # Loaded state reflects the settings.
    assert dlg._report_unit_system.currentData() == "imperial"
    assert dlg._plot_unit_system.currentData() == "si"
    # Change and save back into the settings object.
    dlg._report_unit_system.setCurrentIndex(
        dlg._report_unit_system.findData("default")
    )
    dlg._plot_unit_system.setCurrentIndex(
        dlg._plot_unit_system.findData("imperial")
    )
    dlg._save_into(s)  # see note in Step 3 about the exact save method name
    assert s.report_unit_system == "default"
    assert s.plot_unit_system == "imperial"
```

Before writing the assertion for the save call, confirm the dialog's write-back method: `grep -n "def _save\|def accept\|report_decimals = self" src/starpost/gui/views/settings_dialog.py`. Use the method that assigns widget values onto the `Settings` object (the block near line 1653 that does `s.report_decimals = self._decimals.value()`). Call the test's save through that method (it may be `accept`, `_collect`, or `_save_into` — match the real name).

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_settings_dialog.py -q`
Expected: FAIL — `SettingsDialog has no attribute _report_unit_system`.

- [ ] **Step 3: Implement the dropdowns**

In `settings_dialog.py`, define a small helper once (module level, near the top-level imports):

```python
def _unit_system_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("Default (no conversion)", "default")
    combo.addItem("SI", "si")
    combo.addItem("Imperial", "imperial")
    return combo
```

In `_build_reports_page` (near line 525), create the widget and add a row:

```python
        self._report_unit_system = _unit_system_combo()
```

```python
        form.addRow("Unit system", self._report_unit_system)
        us_hint = QLabel("Convert report values shown in the table to this system.")
        us_hint.setObjectName("hint")
        us_hint.setWordWrap(True)
        form.addRow("", us_hint)
```

In `_build_plots_page` (near line 560), create and add:

```python
        self._plot_unit_system = _unit_system_combo()
```

```python
        form.addRow("Unit system", self._plot_unit_system)
        pus_hint = QLabel("Convert monitor plot data shown on the plot to this system.")
        pus_hint.setObjectName("hint")
        pus_hint.setWordWrap(True)
        form.addRow("", pus_hint)
```

In the load path (the method that sets widgets from `s`, near line 1580, alongside `self._decimals.setValue(s.report_decimals)`):

```python
        ri = self._report_unit_system.findData(s.report_unit_system)
        self._report_unit_system.setCurrentIndex(ri if ri >= 0 else 0)
        pi = self._plot_unit_system.findData(s.plot_unit_system)
        self._plot_unit_system.setCurrentIndex(pi if pi >= 0 else 0)
```

In the save path (the method that writes widgets onto `s`, near line 1653, alongside `s.report_decimals = self._decimals.value()`):

```python
        s.report_unit_system = self._report_unit_system.currentData()
        s.plot_unit_system = self._plot_unit_system.currentData()
```

- [ ] **Step 4a: Wire the main window at construction**

In `main_window.py`, after `self.report_table = ReportTable(...)` (near line 145) add:

```python
        self.report_table.set_unit_system(settings.report_unit_system)
```

In the lazy `plot_view` property (near line 216, next to `pv.set_smooth_width(...)`) add:

```python
            pv.set_unit_system(s.plot_unit_system)
```

- [ ] **Step 4b: Push the systems on settings save**

In `_apply_settings_to_views` (near line 1742), after `self.report_table.set_zero_threshold(...)` add:

```python
        self.report_table.set_unit_system(self.settings.report_unit_system)
```

and after `self.plot_view.set_smooth_width(...)` (near line 1754) add:

```python
        self.plot_view.set_unit_system(self.settings.plot_unit_system)
```

`_apply_settings_to_views` already ends with `self._refresh_views()`, which re-runs `show_single` / `show_comparison`, so the report table's single view (which does not self-refresh) and the plots both redraw in the new system.

- [ ] **Step 4c: Convert the comparison report frame**

In `main_window.py` where the comparison frame is built (near line 1429), pass the system:

```python
            df = reports_wide_frame(results, selected, unit_system=self.settings.report_unit_system)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_settings_dialog.py tests/test_main_window.py -q && ruff check src/starpost/gui/views/settings_dialog.py src/starpost/gui/main_window.py`
Expected: all pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/starpost/gui/views/settings_dialog.py src/starpost/gui/main_window.py tests/test_settings_dialog.py
git commit -m "feat: main-UI unit-system dropdowns wired to reports and plots"
```

---

### Task 6: Batch saved-plot per-plot unit system

**Files:**
- Modify: `src/starpost/gui/views/batch_run_dialog.py` (`_capture_plot` near line 1789, `_apply_plot` near line 1838, Plots-tab control build, `_SavedPlotPropertiesDialog` near line 344)
- Modify: `src/starpost/batch/run.py` (`render_saved_plot` near line 87)
- Test: `tests/test_batch_run_dialog.py` (append; create if absent), `tests/test_batch_run.py` (append if present)

**Interfaces:**
- Consumes: `PlotView.set_unit_system`.
- Produces: saved-plot dict key `"unit_system"` (default `"default"`), round-tripped by `_capture_plot`/`_apply_plot` and applied by `render_saved_plot`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_batch_run_dialog.py` (mirror the fixture/setup already used there for constructing `BatchRunDialog`; if the file does not exist, create it using the same `app` fixture and constructor arguments as `tests/test_main_window.py` uses for the dialog):

```python
def test_saved_plot_captures_and_restores_unit_system(app, batch_dialog):
    dlg = batch_dialog
    dlg._plot_unit_system.setCurrentIndex(dlg._plot_unit_system.findData("imperial"))
    data = dlg._capture_plot()
    assert data["unit_system"] == "imperial"
    # Round-trips back into the control.
    dlg._plot_unit_system.setCurrentIndex(dlg._plot_unit_system.findData("default"))
    dlg._apply_plot(data)
    assert dlg._plot_unit_system.currentData() == "imperial"
```

(If `batch_dialog` is not an existing fixture, add one that constructs the dialog exactly as the app does — see `main_window._open_run_batch` near line 640 for the constructor arguments `data_sets`, `results`, `settings`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_batch_run_dialog.py::test_saved_plot_captures_and_restores_unit_system -q`
Expected: FAIL — `BatchRunDialog has no attribute _plot_unit_system`.

- [ ] **Step 3a: Add the per-plot control**

In `batch_run_dialog.py`, where the Plots-tab controls are built (the same place `self._plot_theme`, `self._plot_format` etc. are created — find with `grep -n "self._plot_theme = \|self._plot_format = " src/starpost/gui/views/batch_run_dialog.py`), add:

```python
        self._plot_unit_system = QComboBox()
        self._plot_unit_system.addItem("Default (no conversion)", "default")
        self._plot_unit_system.addItem("SI", "si")
        self._plot_unit_system.addItem("Imperial", "imperial")
        self._plot_unit_system.currentIndexChanged.connect(self._render_preview)
```

Add it to the Plots-tab form/layout next to the theme control (match the surrounding `addRow`/`addWidget` style used for `self._plot_theme`).

- [ ] **Step 3b: Capture and restore**

In `_capture_plot` (near line 1804), add to the returned dict:

```python
            "unit_system": self._plot_unit_system.currentData(),
```

In `_apply_plot` (near line 1843), restore it (before the monitor selection line):

```python
        ui = self._plot_unit_system.findData(data.get("unit_system") or "default")
        if ui >= 0:
            self._plot_unit_system.setCurrentIndex(ui)
```

- [ ] **Step 3c: Apply in the live preview**

Find where the preview `PlotView` is built/refreshed (`grep -n "self._preview = \|self._preview\.show_plots\|def _render_preview" src/starpost/gui/views/batch_run_dialog.py`). In `_render_preview`, before the `show_plots` call, add:

```python
        self._preview.set_unit_system(self._plot_unit_system.currentData())
```

- [ ] **Step 3d: Apply when rendering the saved plot**

In `src/starpost/batch/run.py` `render_saved_plot` (near line 102), before `view.show_plots(plots)`:

```python
    view.set_unit_system(plot_data.get("unit_system") or "default")
```

- [ ] **Step 3e: Show it in the saved-plot Properties dialog (optional but consistent)**

In `_SavedPlotPropertiesDialog` (near line 344), add a read-only row showing the captured unit system (`data.get("unit_system", "default")`), matching how the theme/format are displayed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_batch_run_dialog.py -q && ruff check src/starpost/gui/views/batch_run_dialog.py src/starpost/batch/run.py`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/gui/views/batch_run_dialog.py src/starpost/batch/run.py tests/test_batch_run_dialog.py
git commit -m "feat: per-plot unit system on saved batch plots"
```

---

### Task 7: Batch global reports unit system

**Files:**
- Modify: `src/starpost/core/settings.py` (`BatchProfile`: field, `save`, `load` near lines 481–530)
- Modify: `src/starpost/gui/views/batch_run_dialog.py` (Reports-tab control, `_build_config`/collect near line 1002, `_restore` from profile near line 1031)
- Modify: `src/starpost/batch/run.py` (report-table build near lines 320–390; `RunConfig` near line 63)
- Test: `tests/test_settings.py` (BatchProfile round-trip), `tests/test_batch_run.py`

**Interfaces:**
- Consumes: `reports_long_frame(..., unit_system=...)`.
- Produces: `BatchProfile.report_unit_system: str = "default"`; `RunConfig.report_unit_system: str = "default"`; a batch-window Reports dropdown feeding both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
def test_batch_profile_round_trips_report_unit_system(isolated_batch_profiles):
    from starpost.core.settings import BatchProfile

    bp = BatchProfile(name="p", report_unit_system="imperial")
    bp.save()
    assert BatchProfile.load("p").report_unit_system == "imperial"


def test_batch_profile_defaults_report_unit_system():
    from starpost.core.settings import BatchProfile

    assert BatchProfile(name="p").report_unit_system == "default"
```

If there is no `isolated_batch_profiles` fixture, add one mirroring `isolated_profiles` but patching `starpost.core.settings.batch_profiles_dir`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings.py::test_batch_profile_defaults_report_unit_system -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'report_unit_system'`.

- [ ] **Step 3a: Extend BatchProfile**

In `settings.py` `BatchProfile` (near line 487), add the field after `include_units`:

```python
    report_unit_system: str = "default"
```

In `BatchProfile.save` `data` dict (near line 500), add:

```python
            "report_unit_system": self.report_unit_system,
```

In `BatchProfile.load` `cls(...)` (near line 519), add (validated):

```python
            report_unit_system=_norm_unit_system(data.get("report_unit_system")),
```

(`_norm_unit_system` is the alias imported in Task 2.)

- [ ] **Step 3b: Extend RunConfig and the report build**

In `run.py`, add to `RunConfig` (near line 63, after `include_units`):

```python
    report_unit_system: str = "default"
```

In both `reports_long_frame(...)` calls (near lines 324 and 388), pass the system:

```python
                df = reports_long_frame(
                    [result], config.reports, config.include_units,
                    config.report_unit_system,
                )
```

```python
            df = reports_long_frame(
                combined_results, config.reports, config.include_units,
                config.report_unit_system,
            )
```

- [ ] **Step 3c: Batch-window control + config plumbing**

In `batch_run_dialog.py`, add a Reports-tab dropdown next to the report-format control (`grep -n "report_format\|_report_format" src/starpost/gui/views/batch_run_dialog.py` to locate it):

```python
        self._report_unit_system = QComboBox()
        self._report_unit_system.addItem("Default (no conversion)", "default")
        self._report_unit_system.addItem("SI", "si")
        self._report_unit_system.addItem("Imperial", "imperial")
```

Where the dialog builds its `RunConfig`/`BatchProfile` (the `saved_plots=self._saved_entries(...)` block near line 1002, and the profile-save path), include:

```python
            report_unit_system=self._report_unit_system.currentData(),
```

Where it restores a `BatchProfile` into the controls (`_restore_*`, near line 1031), add:

```python
        ri = self._report_unit_system.findData(
            getattr(profile, "report_unit_system", "default")
        )
        if ri >= 0:
            self._report_unit_system.setCurrentIndex(ri)
```

- [ ] **Step 4: Write a run-level conversion test**

Append to `tests/test_batch_run.py` (match its existing config/result construction helpers):

```python
def test_run_report_table_converts_units(tmp_path):
    from starpost.batch.aggregator import reports_long_frame
    from starpost.data.models import Report, SimResult

    res = SimResult(sim_path="/x/a.sim", reports=[Report("Drag", 100.0, "N")])
    df = reports_long_frame([res], {"Drag"}, True, "imperial")
    assert "Drag [lbf]" in df["Report"].tolist()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_settings.py tests/test_batch_run.py -q && ruff check src/starpost/core/settings.py src/starpost/batch/run.py src/starpost/gui/views/batch_run_dialog.py`
Expected: all pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/starpost/core/settings.py src/starpost/batch/run.py src/starpost/gui/views/batch_run_dialog.py tests/test_settings.py tests/test_batch_run.py
git commit -m "feat: global reports unit system in Run-batch"
```

---

### Task 8: Full suite, docs, and real-display verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/StarPost_Documentation.md` (Settings → Reports/Plots and Run-batch sections)

**Interfaces:**
- Consumes: everything above. Produces: user-facing docs + a green full suite.

- [ ] **Step 1: Run the full suite**

Run: `python scripts/run_tests.py`
Expected: all files pass. If any GUI file is slow/hangs, that indicates a leaked-widget issue — re-check the new setters do not construct extra top-level widgets.

- [ ] **Step 2: Lint the whole tree**

Run: `ruff check .`
Expected: clean.

- [ ] **Step 3: Real-display verification (per the verify skill)**

Use the `verify` skill to drive a real (offscreen) `MainWindow`: load a cached/sample result, open Settings, set Reports and Plots unit system to Imperial, and confirm the Reports table shows `lbf`/`psi` units and the plot Y-axis label reads e.g. `Force (lbf)`. Capture a screenshot. This covers the window-level wiring that `QTest`-only checks can miss (see the `gui-input-changes-need-real-display-verification` memory).

- [ ] **Step 4: Update the changelog**

Prepend to `CHANGELOG.md` (matching the existing newest-first style):

```markdown
## Unreleased

### Added
- Unit conversion for reports and monitor plots. Settings → Reports and
  Settings → Plots each gain a **Unit system** dropdown (Default / SI /
  Imperial) applied to the live views. The Run-batch window adds a global
  reports unit system and a per-plot unit system saved with each plot.
```

- [ ] **Step 5: Update the user documentation**

In `docs/StarPost_Documentation.md`, note the new Reports/Plots **Unit system** setting and the Run-batch reports/per-plot unit selectors, in the style of the surrounding sections.

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md docs/StarPost_Documentation.md
git commit -m "docs: unit conversion changelog + documentation"
```

---

## Self-Review

**Spec coverage:**
- Default/SI/Imperial three-way choice → Task 1 (`_TARGETS`, strict base SI / engineering Imperial), Task 5/6/7 dropdowns. ✓
- Main-UI Settings dropdowns for reports and plots → Task 5. ✓
- Reports conversion = live table only (single + comparison), not exports/portable → Tasks 3 & 5; aggregator/portable exports untouched by default (`unit_system` defaults to `"default"`). ✓
- Plots convert per-series with converted Y label → Task 4. ✓
- Run-batch: global reports selector → Task 7; per-plot selector saved with the plot → Task 6. ✓
- Units are part of the saved plot when added → Task 6 `_capture_plot`/`_apply_plot`. ✓
- Non-destructive (cached `SimResult` untouched) → all conversions read `Report`/`PlotSeries` and transform copies. ✓
- Pass-through unknown/dimensionless/blank → Task 1 identity path + tests. ✓
- Temperature affine → Task 1 offset handling + round-trip test. ✓
- No shortcut changes → confirmed; `shortcuts.py`/`starpost_hotkeys.txt` untouched.

**Placeholder scan:** No TBD/TODO. Two steps direct the implementer to confirm an exact existing method/attribute name via `grep` before writing (`PlotView._render` dispatcher, the settings-dialog save method, batch preview attribute) — these are name-verification steps, not missing content; the code to write is shown in full.

**Type consistency:** `unit_system` is the string `"default"|"si"|"imperial"` everywhere (settings, aggregator, `RunConfig`, saved-plot dict, PlotView/ReportTable setters). `conversion_factors` → `(factor, shift, target_unit)` used identically by `convert_value`, `convert_series`, `target_unit`, and `PlotView._converted`. `reports_wide_frame`/`reports_long_frame` share the same trailing `unit_system` parameter position.
