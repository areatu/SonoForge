"""Simpson biplane/monoplane LVEF calculations."""

from __future__ import annotations

import math

from echo_personal_tool.domain.models import Contour, LvefResult
from echo_personal_tool.domain.services.contour_geometry import long_axis_endpoints

_VALID_PHASES = {"ed", "es"}
_VALID_VIEWS = {"A4C", "A2C"}


def calculate(
    contours: tuple[Contour, ...],
    pixel_spacing: tuple[float, float] | None,
) -> LvefResult | None:
    """Compute Simpson LV volumes and LVEF from contour polygons."""
    if pixel_spacing is None:
        return None

    row_spacing, col_spacing = pixel_spacing
    if row_spacing <= 0.0 or col_spacing <= 0.0:
        return None

    grouped: dict[
        str,
        dict[
            str,
            tuple[
                tuple[tuple[float, float], ...],
                tuple[tuple[float, float], tuple[float, float]] | None,
            ],
        ],
    ] = {
        "A4C": {},
        "A2C": {},
    }

    for contour in contours:
        phase = contour.phase.casefold()
        view = contour.view.casefold().upper()
        if phase not in _VALID_PHASES or view not in _VALID_VIEWS:
            continue
        grouped[view][phase] = _contour_to_mm(contour, pixel_spacing)

    per_view_volumes: dict[str, tuple[float, float]] = {}
    for view, phases in grouped.items():
        ed_contour = phases.get("ed")
        es_contour = phases.get("es")
        if ed_contour is None or es_contour is None:
            continue

        ed_points_mm, ed_annulus_mm = ed_contour
        es_points_mm, es_annulus_mm = es_contour
        edv_ml = _simpson_volume_ml(ed_points_mm, ed_annulus_mm)
        esv_ml = _simpson_volume_ml(es_points_mm, es_annulus_mm)
        if edv_ml <= 0.0 or esv_ml <= 0.0:
            continue
        per_view_volumes[view] = (edv_ml, esv_ml)

    if not per_view_volumes:
        return None

    edv_ml = sum(volume[0] for volume in per_view_volumes.values()) / len(per_view_volumes)
    esv_ml = sum(volume[1] for volume in per_view_volumes.values()) / len(per_view_volumes)
    if edv_ml <= 0.0:
        return None

    method = "simpson_biplan" if len(per_view_volumes) == 2 else "simpson_monoplan"
    lvef_percent = (edv_ml - esv_ml) / edv_ml * 100.0
    return LvefResult(
        edv_ml=edv_ml,
        esv_ml=esv_ml,
        lvef_percent=lvef_percent,
        method=method,
    )


def _contour_to_mm(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> tuple[
    tuple[tuple[float, float], ...],
    tuple[tuple[float, float], tuple[float, float]] | None,
]:
    """Convert contour points from pixels to millimeters."""
    row_spacing, col_spacing = pixel_spacing
    points_mm = tuple(
        (float(col) * col_spacing, float(row) * row_spacing)
        for col, row in contour.points
    )
    annulus_mm = None
    if contour.mitral_annulus is not None:
        annulus_mm = (
            (
                float(contour.mitral_annulus[0][0]) * col_spacing,
                float(contour.mitral_annulus[0][1]) * row_spacing,
            ),
            (
                float(contour.mitral_annulus[1][0]) * col_spacing,
                float(contour.mitral_annulus[1][1]) * row_spacing,
            ),
        )
    return points_mm, annulus_mm


def _simpson_volume_ml(
    contour_points_mm: tuple[tuple[float, float], ...],
    mitral_annulus_mm: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> float:
    """Approximate a contour volume using 20 Simpson disks."""
    if len(contour_points_mm) < 3:
        return 0.0

    if mitral_annulus_mm is not None:
        base, tip = long_axis_endpoints(list(contour_points_mm), mitral_annulus_mm)
        long_axis_mm = math.hypot(tip[0] - base[0], tip[1] - base[1])
        if long_axis_mm <= 0.0:
            return 0.0

        disk_height_mm = long_axis_mm / 20.0
        axis_dx = tip[0] - base[0]
        axis_dy = tip[1] - base[1]
        disk_diameters_mm = []
        for index in range(20):
            alpha = (index + 0.5) / 20.0
            center = (
                base[0] + alpha * axis_dx,
                base[1] + alpha * axis_dy,
            )
            disk_diameters_mm.append(
                _find_width_perpendicular_to_axis(
                    contour_points_mm,
                    base,
                    tip,
                    center,
                )
            )
        diameter_mm = max(disk_diameters_mm, default=0.0)
        if diameter_mm <= 0.0:
            return 0.0

        disk_volume_mm3 = 0.0
        for index in range(20):
            disk_volume_mm3 += (math.pi / 4.0) * diameter_mm * diameter_mm * disk_height_mm

        return disk_volume_mm3 / 1000.0

    y_values = [point[1] for point in contour_points_mm]
    min_y = min(y_values)
    max_y = max(y_values)
    long_axis_mm = max_y - min_y
    if long_axis_mm <= 0.0:
        return 0.0

    disk_height_mm = long_axis_mm / 20.0
    disk_volume_mm3 = 0.0
    for index in range(20):
        y_mid = min_y + (index + 0.5) * disk_height_mm
        diameter_mm = _find_width_at_y(contour_points_mm, y_mid)
        disk_volume_mm3 += (math.pi / 4.0) * disk_height_mm * diameter_mm * diameter_mm

    return disk_volume_mm3 / 1000.0


def _find_width_at_y(contour_points_mm: tuple[tuple[float, float], ...], y_mm: float) -> float:
    """Find the horizontal span of a polygon at a given y coordinate."""
    if len(contour_points_mm) < 2:
        return 0.0

    intersections: list[float] = []
    wrapped_points = contour_points_mm[1:] + contour_points_mm[:1]
    for (x1, y1), (x2, y2) in zip(contour_points_mm, wrapped_points, strict=True):
        if y1 == y2:
            continue
        if (y1 <= y_mm < y2) or (y2 <= y_mm < y1):
            x_mm = x1 + (y_mm - y1) * (x2 - x1) / (y2 - y1)
            intersections.append(x_mm)

    if len(intersections) < 2:
        return 0.0

    return max(intersections) - min(intersections)


def _find_width_perpendicular_to_axis(
    polygon: tuple[tuple[float, float], ...],
    axis_base: tuple[float, float],
    axis_tip: tuple[float, float],
    center: tuple[float, float],
) -> float:
    """Find the polygon span along the line perpendicular to the long axis."""
    if len(polygon) < 2:
        return 0.0

    axis_dx = axis_tip[0] - axis_base[0]
    axis_dy = axis_tip[1] - axis_base[1]
    axis_length = math.hypot(axis_dx, axis_dy)
    if axis_length <= 0.0:
        return 0.0

    unit_x = axis_dx / axis_length
    unit_y = axis_dy / axis_length
    perp_x = -unit_y
    perp_y = unit_x

    def cross(ax: float, ay: float, bx: float, by: float) -> float:
        return ax * by - ay * bx

    intersections: list[float] = []
    wrapped_points = polygon[1:] + polygon[:1]
    for (x1, y1), (x2, y2) in zip(polygon, wrapped_points, strict=True):
        edge_dx = x2 - x1
        edge_dy = y2 - y1
        denom = cross(perp_x, perp_y, edge_dx, edge_dy)
        if abs(denom) <= 1e-12:
            continue

        rel_x = x1 - center[0]
        rel_y = y1 - center[1]
        s = cross(rel_x, rel_y, edge_dx, edge_dy) / denom
        t = cross(rel_x, rel_y, perp_x, perp_y) / denom
        if -1e-9 <= t <= 1.0 + 1e-9:
            intersections.append(s)

    if len(intersections) < 2:
        return 0.0

    return max(intersections) - min(intersections)
