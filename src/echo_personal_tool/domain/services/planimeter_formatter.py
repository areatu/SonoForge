"""Collect generic area/volume planimeter results from contours."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.planimeter import (
    GENERIC_AREA_CHAMBER,
    GENERIC_VOLUME_CHAMBER,
    closed_polygon_area_cm2,
    closed_polygon_area_px2,
    closed_polygon_volume_ml,
    closed_polygon_volume_px3,
    format_area_result,
    format_volume_result,
)
from echo_personal_tool.domain.measurement_catalog import format_measurement
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.measurements import PlanimeterResult, lineage_from_contour
from echo_personal_tool.domain.translation import tr


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
        # The contour is the primary source of the area and it carries the
        # clip and frame it was traced on — pass that lineage on (task 4).
        lineage = lineage_from_contour(contour)
        if chamber == GENERIC_AREA_CHAMBER:
            if spacing_calibrated:
                area = closed_polygon_area_cm2(contour, pixel_spacing)
                unit = "cm²"
            else:
                area = closed_polygon_area_px2(contour)
                unit = "px²"
            if area is not None:
                results.append(PlanimeterResult(label=label, kind="area", value=area, unit=unit, contour=lineage))
        elif chamber == GENERIC_VOLUME_CHAMBER:
            if spacing_calibrated:
                volume = closed_polygon_volume_ml(contour, pixel_spacing)
                unit = "mL"
            else:
                volume = closed_polygon_volume_px3(contour)
                unit = "px³"
            if volume is not None:
                results.append(PlanimeterResult(label=label, kind="volume", value=volume, unit=unit, contour=lineage))
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


def planimeter_progress_text(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    spacing_calibrated: bool,
) -> str | None:
    """Provisional area/volume line for the still-open polygon (#546)."""
    if pixel_spacing is None:
        return None
    chamber = contour.chamber.upper()
    if chamber == GENERIC_AREA_CHAMBER:
        if spacing_calibrated:
            area = closed_polygon_area_cm2(contour, pixel_spacing)
            return (
                None
                if area is None
                else tr("viewer.area_progress", value=format_measurement("planimeter.area", area, "cm²"))
            )
        area_px2 = closed_polygon_area_px2(contour)
        return (
            None
            if area_px2 is None
            else tr("viewer.area_progress_px", value=format_measurement("planimeter.area", area_px2, "px²"))
        )
    if chamber == GENERIC_VOLUME_CHAMBER:
        if spacing_calibrated:
            volume = closed_polygon_volume_ml(contour, pixel_spacing)
            return (
                None
                if volume is None
                else tr("viewer.volume_progress", value=format_measurement("planimeter.volume", volume, "mL"))
            )
        volume_px3 = closed_polygon_volume_px3(contour)
        return (
            None
            if volume_px3 is None
            else tr("viewer.volume_progress_px", value=format_measurement("planimeter.volume", volume_px3, "px³"))
        )
    return None
