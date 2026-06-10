"""Simpson biplane/monoplane LVEF calculations."""

from __future__ import annotations

import math

from echo_personal_tool.domain.models import Contour, LvefResult

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

    grouped: dict[str, dict[str, tuple[tuple[float, float], ...]]] = {
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
        ed_points = phases.get("ed")
        es_points = phases.get("es")
        if ed_points is None or es_points is None:
            continue

        edv_ml = _simpson_volume_ml(ed_points)
        esv_ml = _simpson_volume_ml(es_points)
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
) -> tuple[tuple[float, float], ...]:
    """Convert contour points from pixels to millimeters."""
    row_spacing, col_spacing = pixel_spacing
    return tuple(
        (float(col) * col_spacing, float(row) * row_spacing)
        for col, row in contour.points
    )


def _simpson_volume_ml(contour_points_mm: tuple[tuple[float, float], ...]) -> float:
    """Approximate a contour volume using 20 Simpson disks."""
    if len(contour_points_mm) < 3:
        return 0.0

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
