"""Left atrial volume by ASE area-length method."""

from __future__ import annotations

import math

from echo_personal_tool.domain.models import Contour, LinearMeasurement
from echo_personal_tool.domain.models.measurements import LaVolumeResult
from echo_personal_tool.domain.services.contour_geometry import polygon_area_mm2

# ASE/EACVI: V (mL) = (8 × A²) / (3π × L), A in cm², L in cm
_AREA_LENGTH_FACTOR = 8.0 / (3.0 * math.pi)


def volume_ml(area_cm2: float, length_cm: float) -> float:
    """Compute LA volume from planimetered area and length."""
    if area_cm2 <= 0.0 or length_cm <= 0.0:
        return 0.0
    return _AREA_LENGTH_FACTOR * area_cm2 * area_cm2 / length_cm


def from_measurements(
    contours: tuple[Contour, ...],
    linear_measurements: tuple[LinearMeasurement, ...],
    pixel_spacing: tuple[float, float] | None,
) -> LaVolumeResult | None:
    """Derive LA area-length volume from an LA contour and LAL caliper."""
    if pixel_spacing is None:
        return None

    row_spacing, col_spacing = pixel_spacing
    if row_spacing <= 0.0 or col_spacing <= 0.0:
        return None

    la_contour = next(
        (contour for contour in contours if contour.chamber.upper() == "LA"),
        None,
    )
    area_cm2: float | None = None
    if la_contour is not None and len(la_contour.points) >= 3:
        area_mm2 = polygon_area_mm2(la_contour.points, pixel_spacing)
        if area_mm2 > 0.0:
            area_cm2 = area_mm2 / 100.0

    length_cm: float | None = None
    for measurement in linear_measurements:
        if measurement.label.upper() != "LAL":
            continue
        if measurement.millimeter_length is None or measurement.millimeter_length <= 0.0:
            continue
        length_cm = measurement.millimeter_length / 10.0
        break

    if area_cm2 is None and length_cm is None:
        return None

    volume: float | None = None
    if area_cm2 is not None and length_cm is not None:
        volume = volume_ml(area_cm2, length_cm)
        if volume <= 0.0:
            volume = None

    return LaVolumeResult(
        volume_ml=volume,
        area_cm2=area_cm2,
        length_cm=length_cm,
    )
