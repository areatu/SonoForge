"""Unit boundaries for measurement values shown without a physical scale (#546).

Calibrated values live in clinical units: cm² for areas and mL for volumes.
Uncalibrated calculations run with unit spacing (1 mm/px), where the numeric
value of a square millimetre equals one square pixel and the numeric value of
a cubic millimetre equals 1/1000 of a cubic pixel.  The display boundary must
restore the pixel value before it changes the label; renaming alone would
report 100 px² as 1 px² and 1000 px³ as 1 px³.
"""

from __future__ import annotations

#: One cm² is 100 mm², i.e. 100 px² when the calculation used 1 mm/px.
PX2_PER_UNIT_SPACING_CM2 = 100.0
#: One mL is 1000 mm³, i.e. 1000 px³ when the calculation used 1 mm/px.
PX3_PER_UNIT_SPACING_ML = 1000.0


def area_for_display(value: float | None, *, calibrated: bool) -> float | None:
    """Return an area in the unit that ``calibrated`` selects for display."""
    if value is None:
        return None
    return value if calibrated else value * PX2_PER_UNIT_SPACING_CM2


def volume_for_display(value: float | None, *, calibrated: bool) -> float | None:
    """Return a volume in the unit that ``calibrated`` selects for display."""
    if value is None:
        return None
    return value if calibrated else value * PX3_PER_UNIT_SPACING_ML


def area_unit(*, calibrated: bool) -> str:
    return "cm²" if calibrated else "px²"


def volume_unit(*, calibrated: bool) -> str:
    return "mL" if calibrated else "px³"
