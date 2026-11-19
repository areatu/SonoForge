"""UCUM unit codes and explicit unit conversion (#625).

Pure domain module (standard library only).  Every display unit the app can
print maps to exactly one UCUM code; conversion between display units goes
through an explicit factor table — never through silent rounding — and the
canonical UCUM unit per physical quantity is what outbound messages carry.

UCUM is case-sensitive; the codes below are the canonical UCUM strings
(``mm[Hg]`` for mmHg, ``/min`` for beats per minute, ``cm2`` for cm², …).
"""

from __future__ import annotations

from dataclasses import dataclass

#: FHIR / HL7 UCUM system identifier.
UCUM_SYSTEM = "http://unitsofmeasure.org"


class ConversionError(ValueError):
    """Raised when a value cannot be represented/converted to the target unit."""


@dataclass(frozen=True)
class UnitSpec:
    """One display unit: its UCUM code, the quantity it belongs to and the factor to canonical."""

    ucum: str
    quantity: str
    to_canonical: float  # multiply a value in this unit by this to get the canonical unit


#: Display unit → UCUM spec.  Linear app default is mm (cm and m/s stay as
#: separate units); Doppler CW is m/s, PW/TDI is cm/s (the Doppler display decision).
_DISPLAY_UNITS: dict[str, UnitSpec] = {
    "mm": UnitSpec("mm", "length", 1.0),
    "cm": UnitSpec("cm", "length", 10.0),  # canonical length is mm
    "m/s": UnitSpec("m/s", "velocity", 1.0),  # canonical velocity is m/s
    "cm/s": UnitSpec("cm/s", "velocity", 0.01),
    "ms": UnitSpec("ms", "time", 1.0),  # canonical time is ms
    "s": UnitSpec("s", "time", 1000.0),
    "cm²": UnitSpec("cm2", "area", 1.0),  # canonical area is cm²
    "mm²": UnitSpec("mm2", "area", 0.01),
    "mL": UnitSpec("mL", "volume", 1.0),  # canonical volume is mL
    "L": UnitSpec("L", "volume", 1000.0),
    "g": UnitSpec("g", "mass", 1.0),
    "kg": UnitSpec("kg", "mass", 1000.0),
    "m²": UnitSpec("m2", "bsa", 1.0),
    "mm/m²": UnitSpec("mm/m2", "indexed_length", 1.0),
    "mL/m²": UnitSpec("mL/m2", "indexed_volume", 1.0),
    "cm²/m²": UnitSpec("cm2/m2", "indexed_area", 1.0),
    "g/m²": UnitSpec("g/m2", "indexed_mass", 1.0),
    "mmHg": UnitSpec("mm[Hg]", "pressure", 1.0),
    "mmHg/s": UnitSpec("mm[Hg]/s", "pressure_rate", 1.0),
    "bpm": UnitSpec("/min", "rate", 1.0),
    "/min": UnitSpec("/min", "rate", 1.0),
    "%": UnitSpec("%", "percent", 1.0),
    "": UnitSpec("1", "ratio", 1.0),  # dimensionless
    "1": UnitSpec("1", "ratio", 1.0),
    "cm (VTI)": UnitSpec("cm", "vti", 1.0),
}

#: Canonical UCUM unit per quantity — what outbound OBX-6 / FHIR unit carry.
_CANONICAL: dict[str, str] = {
    "length": "mm",
    "orifice": "cm",  # orifice diameters feed area formulas, app keeps cm
    "pisa_radius": "cm",
    "vti": "cm",
    "velocity": "m/s",
    "time": "ms",
    "area": "cm2",
    "volume": "mL",
    "mass": "g",
    "bsa": "m2",
    "indexed_length": "mm/m2",
    "indexed_volume": "mL/m2",
    "indexed_mass": "g/m2",
    "indexed_area": "cm2/m2",
    "pressure": "mm[Hg]",
    "pressure_rate": "mm[Hg]/s",
    "rate": "/min",
    "ratio": "1",
    "percent": "%",
}


def ucum_for_display_unit(unit: str) -> str:
    """Return the UCUM code of a display *unit* (raises :class:`ConversionError` if unknown)."""
    spec = _DISPLAY_UNITS.get(unit.strip())
    if spec is None:
        raise ConversionError(f"unknown display unit {unit!r}")
    return spec.ucum


def canonical_ucum_unit(quantity: str) -> str:
    """Return the canonical UCUM unit for a physical *quantity*."""
    unit = _CANONICAL.get(quantity)
    if unit is None:
        raise ConversionError(f"unknown quantity {quantity!r}")
    return unit


def convert_value(value: str, from_unit: str, to_unit: str, *, decimals: int | None = None) -> str:
    """Convert a numeric *value* string between two display units, explicitly.

    ``from_unit``/``to_unit`` must be known display units of the same
    quantity; the conversion is exact arithmetic on the parsed float and
    formatted with *decimals* (or without trailing-zero trimming otherwise).
    """
    source = _DISPLAY_UNITS.get(from_unit.strip())
    target = _DISPLAY_UNITS.get(to_unit.strip())
    if source is None or target is None:
        raise ConversionError(f"unknown unit {from_unit!r} -> {to_unit!r}")
    if source.quantity != target.quantity:
        raise ConversionError(f"unit mismatch {from_unit!r} -> {to_unit!r}")
    try:
        number = float(value.strip().replace(",", "."))
    except ValueError as exc:
        raise ConversionError(f"not a number: {value!r}") from exc
    converted = number * source.to_canonical / target.to_canonical
    if decimals is not None:
        return f"{converted:.{decimals}f}"
    text = f"{converted:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def to_canonical_ucum(value: str, display_unit: str, quantity: str, *, decimals: int | None = None) -> tuple[str, str]:
    """Convert *value* to the canonical UCUM unit of *quantity*; return ``(value, ucum)``."""
    canonical = canonical_ucum_unit(quantity)
    converted = convert_value(value, display_unit, canonical, decimals=decimals)
    return converted, ucum_for_display_unit(canonical)
