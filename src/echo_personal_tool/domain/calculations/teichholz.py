"""Teichholz cube formula volume calculations."""

from __future__ import annotations

import math

from echo_personal_tool.domain.calculations.teichholz_formulas import (
    ejection_fraction_percent,
    fractional_shortening_percent,
    volume_from_cm_ml,
    volume_ml,
)
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import TeichholzResult

# The formulas live in ``teichholz_formulas`` (a leaf the calculator registry can
# import without reaching the models); every name stays importable from here.
__all__ = [
    "ejection_fraction_percent",
    "fractional_shortening_percent",
    "from_linear_measurements",
    "volume_from_cm_ml",
    "volume_ml",
]


def from_linear_measurements(
    measurements: tuple[LinearMeasurement, ...],
) -> TeichholzResult | None:
    """Compute Teichholz EDV/ESV/LVEF from LVEDD and LVESD calipers."""
    lvedd_mm: float | None = None
    lvesd_mm: float | None = None

    LVEDD_ALIASES = {
        "lvedd",
        "lvidd",
        "lv_edd",
        "lv_end_diastolic_diameter",
    }
    LVESD_ALIASES = {
        "lvesd",
        "lvids",
        "lv_esd",
        "lv_end_systolic_diameter",
    }

    for measurement in measurements:
        if measurement.millimeter_length is None:
            continue
        label = measurement.label.strip().casefold()
        if label in LVEDD_ALIASES:
            lvedd_mm = measurement.millimeter_length
        elif label in LVESD_ALIASES:
            lvesd_mm = measurement.millimeter_length

    if (
        lvedd_mm is None
        or lvesd_mm is None
        or not math.isfinite(lvedd_mm)
        or not math.isfinite(lvesd_mm)
        or lvedd_mm <= 0
        or lvesd_mm <= 0
        or lvesd_mm >= lvedd_mm
    ):
        return None

    edv_ml = volume_ml(lvedd_mm)
    esv_ml = volume_ml(lvesd_mm)
    lvef_percent = (edv_ml - esv_ml) / edv_ml * 100.0
    sv_ml = edv_ml - esv_ml
    return TeichholzResult(edv_ml=edv_ml, esv_ml=esv_ml, lvef_percent=lvef_percent, sv_ml=sv_ml)
