"""Simpson biplane/monoplane LVEF calculations."""

from __future__ import annotations

import dataclasses
import math

from echo_personal_tool.domain.models import Contour, LvefResult, LvViewMetrics
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

    grouped_contours: dict[str, dict[str, Contour]] = {"A4C": {}, "A2C": {}}
    grouped_mm: dict[
        str,
        dict[
            str,
            tuple[
                tuple[tuple[float, float], ...],
                tuple[tuple[float, float], tuple[float, float]] | None,
            ],
        ],
    ] = {"A4C": {}, "A2C": {}}

    for contour in contours:
        if contour.chamber.upper() != "LV":
            continue
        if contour.review_pending:
            continue
        phase = contour.phase.casefold()
        view = contour.view.casefold().upper()
        if phase not in _VALID_PHASES or view not in _VALID_VIEWS:
            continue
        grouped_contours[view][phase] = contour
        grouped_mm[view][phase] = _contour_to_mm(contour, pixel_spacing)

    a4c = _build_view_metrics(grouped_mm["A4C"], grouped_contours["A4C"], pixel_spacing)
    a2c = _build_view_metrics(grouped_mm["A2C"], grouped_contours["A2C"], pixel_spacing)
    if a4c is None and a2c is None:
        return None

    per_view_volumes: dict[str, tuple[float, float]] = {}
    for view, metrics in (("A4C", a4c), ("A2C", a2c)):
        if metrics is None:
            continue
        if metrics.edv_ml is not None and metrics.esv_ml is not None:
            per_view_volumes[view] = (metrics.edv_ml, metrics.esv_ml)

    lvef_percent: float | None = None
    method: str | None = None
    if per_view_volumes:
        edv_ml = sum(volume[0] for volume in per_view_volumes.values()) / len(per_view_volumes)
        esv_ml = sum(volume[1] for volume in per_view_volumes.values()) / len(per_view_volumes)
        if edv_ml > 0.0:
            lvef_percent = (edv_ml - esv_ml) / edv_ml * 100.0
            method = "simpson_biplan" if len(per_view_volumes) == 2 else "simpson_monoplan"

    return LvefResult(a4c=a4c, a2c=a2c, lvef_percent=lvef_percent, method=method)


def format_contour_overlay(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    spacing_calibrated: bool = True,
) -> str:
    """Format frame overlay line: view phase · length · volume."""
    view = contour.view
    phase = contour.phase.upper()
    chamber = contour.chamber.upper()
    if contour.review_pending:
        return f"{chamber} {view} {phase}: проверьте контур (ASE) · R — уточнить · Enter — принять"
    if pixel_spacing is None:
        return f"{chamber} {view} {phase} · Длина: — · Объём: —"
    length = _contour_length_mm(contour, pixel_spacing)
    volume = _contour_volume_ml(contour, pixel_spacing)
    if spacing_calibrated:
        length_text = f"{length:.1f} mm" if length is not None else "—"
        volume_text = f"{volume:.1f} mL" if volume is not None else "—"
    else:
        length_text = f"{length:.1f} px" if length is not None else "—"
        volume_text = f"{volume:.1f} px³" if volume is not None else "—"
    return f"{chamber} {view} {phase} · Длина: {length_text} · Объём: {volume_text}"


_MIN_LV_AUTO_ANNULUS_PX = 20.0
_MIN_LV_AUTO_LONG_AXIS_PX = 15.0
_MIN_LV_AUTO_ARC_SPAN_PX = 8.0
_MIN_LV_AUTO_ANNULUS_MM = 5.0
_MIN_ARC_DEPTH_RATIO = 0.15


def _contour_self_intersects(points: list[tuple[float, float]]) -> bool:
    """Check if the open-arc contour self-intersects (excluding consecutive segments)."""
    n = len(points)
    if n < 4:
        return False
    segments = [(points[i], points[i + 1]) for i in range(n - 1)]
    for i in range(len(segments)):
        (ax, ay), (bx, by) = segments[i]
        for j in range(i + 2, len(segments)):
            # Skip adjacent segments (they share an endpoint)
            if j == i + 1:
                continue
            (cx, cy), (dx, dy) = segments[j]
            denom = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
            if abs(denom) < 1e-10:
                continue
            t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / denom
            u = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / denom
            if 0.0 < t < 1.0 and 0.0 < u < 1.0:
                return True
    return False


def _contour_annulus_length_px(contour: Contour) -> float:
    if contour.mitral_annulus is None:
        return 0.0
    septal, lateral = contour.mitral_annulus
    return math.hypot(lateral[0] - septal[0], lateral[1] - septal[1])


def _contour_long_axis_px(contour: Contour) -> float:
    if contour.mitral_annulus is None or len(contour.points) < 3:
        return 0.0
    septal, lateral = contour.mitral_annulus
    apex = contour.apex_landmark
    if apex is None:
        base, tip = long_axis_endpoints(list(contour.points), contour.mitral_annulus)
        return math.hypot(tip[0] - base[0], tip[1] - base[1])
    ma_mid = ((septal[0] + lateral[0]) / 2.0, (septal[1] + lateral[1]) / 2.0)
    return math.hypot(apex[0] - ma_mid[0], apex[1] - ma_mid[1])


def _contour_arc_span_px(contour: Contour) -> float:
    points = contour.points
    if len(points) < 2:
        return 0.0
    max_span = 0.0
    for index, first in enumerate(points):
        for second in points[index + 1 :]:
            span = math.hypot(second[0] - first[0], second[1] - first[1])
            if span > max_span:
                max_span = span
    return max_span


def _contour_arc_depth_px(contour: Contour) -> float:
    """Depth of the arc: max perpendicular distance from MA chord to arc points."""
    if contour.mitral_annulus is None or len(contour.points) < 3:
        return 0.0
    septal, lateral = contour.mitral_annulus
    # MA chord direction
    dx = lateral[0] - septal[0]
    dy = lateral[1] - septal[1]
    chord_len = math.hypot(dx, dy)
    if chord_len < 1e-6:
        return 0.0
    # Unit normal to chord
    nx, ny = -dy / chord_len, dx / chord_len
    max_depth = 0.0
    for pt in contour.points:
        # Distance from point to MA chord line
        dist = abs(nx * (pt[0] - septal[0]) + ny * (pt[1] - septal[1]))
        if dist > max_depth:
            max_depth = dist
    return max_depth


def _contour_centroid(contour: Contour) -> tuple[float, float] | None:
    """Centroid of the closed contour polygon."""
    if len(contour.points) < 3:
        return None
    xs = [p[0] for p in contour.points]
    ys = [p[1] for p in contour.points]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def explain_lv_auto_reject_reason(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
    *,
    mask_pixels: int | None = None,
    roi_xyxy: tuple[float, float, float, float] | None = None,
) -> str | None:
    """Return a short Russian reason when an ONNX contour should not enter review.

    Quality gate v2 adds spacing-aware and geometry checks.
    """
    if contour.mitral_annulus is None or len(contour.points) < 3:
        return "контур не построен"
    annulus_px = _contour_annulus_length_px(contour)
    long_axis_px = _contour_long_axis_px(contour)
    arc_span_px = _contour_arc_span_px(contour)
    if arc_span_px < _MIN_LV_AUTO_ARC_SPAN_PX:
        return "контур маски схлопнулся при построении (маска есть, но граница не извлечена — сообщите разработчику)"
    if annulus_px < _MIN_LV_AUTO_ANNULUS_PX:
        return "не найдено митральное кольцо (проверьте вид A4C и кадр ED/ES)"
    if long_axis_px < _MIN_LV_AUTO_LONG_AXIS_PX:
        return "короткая ось ЛЖ слишком мала — выберите другой кадр"

    # v2: spacing-aware MA length check
    if pixel_spacing is not None:
        row_spacing, col_spacing = pixel_spacing
        if row_spacing > 0 and col_spacing > 0:
            annulus_mm = annulus_px * ((row_spacing + col_spacing) / 2.0)
            if annulus_mm < _MIN_LV_AUTO_ANNULUS_MM:
                return (
                    f"митральное кольцо слишком мало ({annulus_mm:.1f} мм < {_MIN_LV_AUTO_ANNULUS_MM} мм) — "
                    "проверьте вид A4C и калибровку"
                )

    # v2: arc depth ratio check
    arc_depth = _contour_arc_depth_px(contour)
    if annulus_px > 0 and arc_depth / annulus_px < _MIN_ARC_DEPTH_RATIO:
        return (
            f"контур слишком плоский (глубина {arc_depth:.0f}px / кольцо {annulus_px:.0f}px "
            f"< {_MIN_ARC_DEPTH_RATIO:.0%}) — возможно ES или не тот view"
        )

    # v2: centroid outside ROI check
    if roi_xyxy is not None:
        centroid = _contour_centroid(contour)
        if centroid is not None:
            rx0, ry0, rx1, ry1 = roi_xyxy
            if not (rx0 <= centroid[0] <= rx1 and ry0 <= centroid[1] <= ry1):
                return "центр контура вне ROI — проверьте выделение сектора"

    # v3: self-intersection check
    if _contour_self_intersects(contour.points):
        return "контур самопересекается — попробуйте другой кадр или перерисуйте"

    return None


def contour_meets_lv_auto_quality(
    contour: Contour,
    pixel_spacing: tuple[float, float] | None,
) -> bool:
    """Accept ONNX contour for review based on pixel geometry (spacing-independent)."""
    return explain_lv_auto_reject_reason(contour, pixel_spacing) is None


def _contour_length_mm(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    if contour.mitral_annulus is None:
        return None
    points_mm, annulus_mm = _contour_to_mm(contour, pixel_spacing)
    base, tip = long_axis_endpoints(list(points_mm), annulus_mm)
    length = math.hypot(tip[0] - base[0], tip[1] - base[1])
    return length if length > 0.0 else None


def simpson_volume_ml_from_contour(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    """Public Simpson disk volume for any open-arc contour."""
    return _contour_volume_ml(contour, pixel_spacing)


def simpson_volume_ml_from_closed_polygon(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    """Simpson disk volume from a closed polygon (vertical slice method)."""
    if len(contour.points) < 3:
        return None
    row_spacing, col_spacing = pixel_spacing
    points_mm = tuple((float(col) * col_spacing, float(row) * row_spacing) for col, row in contour.points)
    volume = _simpson_volume_ml(points_mm, None)
    return volume if volume > 0.0 else None


def _contour_volume_ml(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> float | None:
    points_mm, annulus_mm = _contour_to_mm(contour, pixel_spacing)
    volume = _simpson_volume_ml(points_mm, annulus_mm)
    return volume if volume > 0.0 else None


def _build_view_metrics(
    phases: dict[
        str,
        tuple[
            tuple[tuple[float, float], ...],
            tuple[tuple[float, float], tuple[float, float]] | None,
        ],
    ],
    contours_by_phase: dict[str, Contour],
    pixel_spacing: tuple[float, float],
) -> LvViewMetrics | None:
    metrics = LvViewMetrics()
    has_any = False

    ed_contour = contours_by_phase.get("ed")
    if ed_contour is not None:
        length = _contour_length_mm(ed_contour, pixel_spacing)
        volume = _contour_volume_ml(ed_contour, pixel_spacing)
        if length is not None:
            metrics = dataclasses.replace(metrics, length_ed_mm=length)
            has_any = True
        if volume is not None:
            metrics = dataclasses.replace(metrics, edv_ml=volume)
            has_any = True

    es_contour = contours_by_phase.get("es")
    if es_contour is not None:
        length = _contour_length_mm(es_contour, pixel_spacing)
        volume = _contour_volume_ml(es_contour, pixel_spacing)
        if length is not None:
            metrics = dataclasses.replace(metrics, length_es_mm=length)
            has_any = True
        if volume is not None:
            metrics = dataclasses.replace(metrics, esv_ml=volume)
            has_any = True

    return metrics if has_any else None


def _contour_to_mm(
    contour: Contour,
    pixel_spacing: tuple[float, float],
) -> tuple[
    tuple[tuple[float, float], ...],
    tuple[tuple[float, float], tuple[float, float]] | None,
]:
    """Convert contour points from pixels to millimeters."""
    row_spacing, col_spacing = pixel_spacing
    polygon_points = contour.closed_polygon_points()
    points_mm = tuple((float(col) * col_spacing, float(row) * row_spacing) for col, row in polygon_points)
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
        if not disk_diameters_mm or max(disk_diameters_mm) <= 0.0:
            return 0.0

        disk_volume_mm3 = 0.0
        for index in range(20):
            diameter_mm = disk_diameters_mm[index]
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
