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
