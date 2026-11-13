"""Generic closed-area and Simpson-volume planimetry."""

from __future__ import annotations

import math

from echo_personal_tool.domain.calculations.lvef_simpson import (
    simpson_volume_ml_from_closed_polygon,
    simpson_volume_px3_from_closed_polygon,
)
from echo_personal_tool.domain.measurement_catalog import format_measurement
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.contour_geometry import polygon_area_mm2
from echo_personal_tool.domain.translation import tr

GENERIC_AREA_CHAMBER = "AREA"
GENERIC_VOLUME_CHAMBER = "VOL"


def is_planimeter_polygon(contour: Contour) -> bool:
    return contour.chamber.upper() in {GENERIC_AREA_CHAMBER, GENERIC_VOLUME_CHAMBER}


def next_area_label(contours: tuple[Contour, ...]) -> str:
    count = sum(1 for contour in contours if contour.chamber.upper() == GENERIC_AREA_CHAMBER)
    return tr("domain.planimeter.area_label", count=str(count + 1))


def next_volume_label(contours: tuple[Contour, ...]) -> str:
    count = sum(1 for contour in contours if contour.chamber.upper() == GENERIC_VOLUME_CHAMBER)
    return tr("domain.planimeter.volume_label", count=str(count + 1))


def _valid_spacing(pixel_spacing: tuple[float, float]) -> bool:
    """Spacing must be finite and positive before it can define a physical area."""
    row_spacing, col_spacing = pixel_spacing
    return all(math.isfinite(value) and value > 0.0 for value in (row_spacing, col_spacing))


def _closed_polygon_base_area(contour: Contour) -> float | None:
    """Shoelace area in the contour's own (pixel) coordinate system."""
    if contour.is_open_arc or len(contour.points) < 3:
        return None
    area_px2 = polygon_area_mm2(contour.points, (1.0, 1.0))
    if not math.isfinite(area_px2) or area_px2 <= 0.0:
        return None
    return area_px2


def closed_polygon_area_px2(contour: Contour) -> float | None:
    """Closed-polygon area in square pixels, without a physical scale."""
    return _closed_polygon_base_area(contour)


def closed_polygon_area_cm2(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    """Closed-polygon area in cm²; only a valid spacing reaches this branch."""
    if not _valid_spacing(pixel_spacing):
        return None
    if contour.is_open_arc or len(contour.points) < 3:
        return None
    area_mm2 = polygon_area_mm2(contour.points, pixel_spacing)
    if not math.isfinite(area_mm2) or area_mm2 <= 0.0:
        return None
    return area_mm2 / 100.0


def closed_polygon_volume_px3(contour: Contour) -> float | None:
    """Closed-polygon Simpson volume in cubic pixels, without a physical scale."""
    if contour.is_open_arc or len(contour.points) < 3:
        return None
    return simpson_volume_px3_from_closed_polygon(contour)


def closed_polygon_volume_ml(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    """Closed-polygon Simpson volume in mL; only a valid spacing reaches this branch."""
    if not _valid_spacing(pixel_spacing):
        return None
    if contour.is_open_arc or len(contour.points) < 3:
        return None
    volume_ml = simpson_volume_ml_from_closed_polygon(contour, pixel_spacing)
    if volume_ml is None or not math.isfinite(volume_ml):
        return None
    return volume_ml


def format_area_result(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    spacing_calibrated: bool,
) -> str:
    label = contour.measurement_label or tr("domain.planimeter.default_area")
    if pixel_spacing is None:
        return f"{label}: —"
    if spacing_calibrated:
        area_cm2 = closed_polygon_area_cm2(contour, pixel_spacing)
        if area_cm2 is None:
            return f"{label}: —"
        return f"{label}: {format_measurement('planimeter.area', area_cm2, 'cm²')} cm²"
    area_px2 = closed_polygon_area_px2(contour)
    return (
        f"{label}: {format_measurement('planimeter.area', area_px2, 'px²')} px²"
        if area_px2 is not None
        else f"{label}: —"
    )


def format_volume_result(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    spacing_calibrated: bool,
) -> str:
    label = contour.measurement_label or tr("domain.planimeter.default_volume")
    if pixel_spacing is None:
        return f"{label}: —"
    if spacing_calibrated:
        volume_ml = closed_polygon_volume_ml(contour, pixel_spacing)
        if volume_ml is None:
            return f"{label}: —"
        return f"{label}: {format_measurement('planimeter.volume', volume_ml, 'mL')} mL"
    volume_px3 = closed_polygon_volume_px3(contour)
    return (
        f"{label}: {format_measurement('planimeter.volume', volume_px3, 'px³')} px³"
        if volume_px3 is not None
        else f"{label}: —"
    )
