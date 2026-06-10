"""Teichholz cube formula volume calculations."""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import TeichholzResult


def volume_ml(dimension_mm: float) -> float:
    """Teichholz cube formula. dimension in mm, returns mL."""
    l_cm = dimension_mm / 10.0
    if l_cm <= 0:
        raise ValueError("dimension must be positive")
    return (7.0 / (2.4 + l_cm)) * (l_cm**3)


def from_linear_measurements(
    measurements: tuple[LinearMeasurement, ...],
) -> TeichholzResult | None:
    """Compute Teichholz EDV/ESV/LVEF from LVEDD and LVESD calipers."""
    lvedd_mm: float | None = None
    lvesd_mm: float | None = None

    for measurement in measurements:
        if measurement.millimeter_length is None:
            continue
        label = measurement.label.casefold()
        if label == "lvedd":
            lvedd_mm = measurement.millimeter_length
        elif label == "lvesd":
            lvesd_mm = measurement.millimeter_length

    if lvedd_mm is None or lvesd_mm is None:
        return None

    edv_ml = volume_ml(lvedd_mm)
    esv_ml = volume_ml(lvesd_mm)
    lvef_percent = (edv_ml - esv_ml) / edv_ml * 100.0
    return TeichholzResult(edv_ml=edv_ml, esv_ml=esv_ml, lvef_percent=lvef_percent)
