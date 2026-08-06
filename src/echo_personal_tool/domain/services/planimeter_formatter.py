"""Collect generic area/volume planimeter results from contours."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.planimeter import (
    GENERIC_AREA_CHAMBER,
    GENERIC_VOLUME_CHAMBER,
    closed_polygon_area_cm2,
    closed_polygon_volume_ml,
    format_area_result,
    format_volume_result,
)
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.measurements import PlanimeterResult


def planimeter_results_from_contours(
    contours: tuple[Contour, ...],
    pixel_spacing: tuple[float, float] | None,
    *,
    spacing_calibrated: bool,
) -> tuple[PlanimeterResult, ...]:
    if pixel_spacing is None:
        return ()
    results: list[PlanimeterResult] = []
    for contour in contours:
        chamber = contour.chamber.upper()
        label = contour.measurement_label or chamber
        if chamber == GENERIC_AREA_CHAMBER:
            area_cm2 = closed_polygon_area_cm2(contour, pixel_spacing)
            if area_cm2 is not None:
                results.append(PlanimeterResult(label=label, kind="area", value=area_cm2, unit="cm²"))
        elif chamber == GENERIC_VOLUME_CHAMBER:
            volume_ml = closed_polygon_volume_ml(contour, pixel_spacing)
            if volume_ml is not None:
                unit = "mL" if spacing_calibrated else "px³"
                results.append(PlanimeterResult(label=label, kind="volume", value=volume_ml, unit=unit))
    return tuple(results)


def format_planimeter_overlay_line(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    spacing_calibrated: bool,
) -> str:
    chamber = contour.chamber.upper()
    if chamber == GENERIC_AREA_CHAMBER:
        return format_area_result(contour, pixel_spacing, spacing_calibrated=spacing_calibrated)
    if chamber == GENERIC_VOLUME_CHAMBER:
        return format_volume_result(contour, pixel_spacing, spacing_calibrated=spacing_calibrated)
    return ""
