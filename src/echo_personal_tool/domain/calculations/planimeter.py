"""Generic closed-area and Simpson-volume planimetry."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.lvef_simpson import (
    simpson_volume_ml_from_closed_polygon,
)
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.services.contour_geometry import polygon_area_mm2
from echo_personal_tool.infrastructure.i18n import tr

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


def closed_polygon_area_cm2(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    if contour.is_open_arc or len(contour.points) < 3:
        return None
    area_mm2 = polygon_area_mm2(contour.points, pixel_spacing)
    if area_mm2 <= 0.0:
        return None
    return area_mm2 / 100.0


def closed_polygon_volume_ml(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    if contour.is_open_arc or len(contour.points) < 3:
        return None
    return simpson_volume_ml_from_closed_polygon(contour, pixel_spacing)


def format_area_result(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    spacing_calibrated: bool,
) -> str:
    label = contour.measurement_label or tr("domain.planimeter.default_area")
    if pixel_spacing is None:
        return f"{label}: —"
    area_cm2 = closed_polygon_area_cm2(contour, pixel_spacing)
    if area_cm2 is None:
        return f"{label}: —"
    if spacing_calibrated:
        return f"{label}: {area_cm2:.2f} cm²"
    area_px2 = closed_polygon_area_cm2(contour, (1.0, 1.0))
    return f"{label}: {area_px2:.0f} px²" if area_px2 is not None else f"{label}: —"


def format_volume_result(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    spacing_calibrated: bool,
) -> str:
    label = contour.measurement_label or tr("domain.planimeter.default_volume")
    if pixel_spacing is None:
        return f"{label}: —"
    volume_ml = closed_polygon_volume_ml(contour, pixel_spacing)
    if volume_ml is None:
        return f"{label}: —"
    if spacing_calibrated:
        return f"{label}: {volume_ml:.1f} mL"
    return f"{label}: {volume_ml:.0f} px³"
