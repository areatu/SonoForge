"""RV FAC open-arc template: crescent via two quadratic Bézier segments."""

from __future__ import annotations

import math

from echo_personal_tool.domain.services.contour_geometry import (
    _resample_polyline,
    point_line_distance,
)

RV_FAC_NODE_COUNT = 16
_MIN_DEPTH_PX = 3.0

# Septal wall S→A: slight bow toward LV; free wall A→L: outward bulge.
_SEPTAL_CTRL_FRAC = 0.20
_FREE_WALL_CTRL_FRAC = -0.10


def _bezier_arc_dir_toward(
    p: tuple[float, float],
    q: tuple[float, float],
    r: tuple[float, float],
) -> tuple[float, float]:
    """Unit perpendicular to chord p→q, pointing toward the side of r."""
    dx = q[0] - p[0]
    dy = q[1] - p[1]
    chord_len = math.hypot(dx, dy)
    if chord_len <= 1e-9:
        return (0.0, 1.0)
    cross = dx * (r[1] - p[1]) - dy * (r[0] - p[0])
    if cross >= 0.0:
        perp_x, perp_y = -dy, dx
    else:
        perp_x, perp_y = dy, -dx
    perp_len = math.hypot(perp_x, perp_y)
    if perp_len <= 1e-9:
        return (0.0, 1.0)
    return (perp_x / perp_len, perp_y / perp_len)


def _quadratic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    n: int,
) -> list[tuple[float, float]]:
    """Sample n equally-spaced points on quadratic Bézier (p0, p1, p2)."""
    if n < 2:
        msg = "n must be at least 2"
        raise ValueError(msg)
    points: list[tuple[float, float]] = []
    for index in range(n):
        t = index / (n - 1)
        s = 1.0 - t
        points.append(
            (
                s * s * p0[0] + 2.0 * s * t * p1[0] + t * t * p2[0],
                s * s * p0[1] + 2.0 * s * t * p1[1] + t * t * p2[1],
            )
        )
    return points


def warp_rv_crescent_open_arc(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    num_points: int = 81,
) -> list[tuple[float, float]]:
    """RV crescent open arc: S→A (septal) + A→L (free wall), two quadratics.

    Apex is the junction of both arcs (3rd landmark). Rotation-invariant.
    """
    if num_points < 3:
        msg = "num_points must be at least 3"
        raise ValueError(msg)

    ma_dx = lateral[0] - septal[0]
    ma_dy = lateral[1] - septal[1]
    ma_len = math.hypot(ma_dx, ma_dy)
    if ma_len <= 0.0:
        msg = "tricuspid annulus length must be positive"
        raise ValueError(msg)

    depth = point_line_distance(apex, septal, lateral)
    if depth < _MIN_DEPTH_PX:
        msg = "apex must be off TV annulus"
        raise ValueError(msg)

    s_pt, l_pt, a_pt = septal, lateral, apex

    chord_sa = math.hypot(a_pt[0] - s_pt[0], a_pt[1] - s_pt[1])
    mid_sa = ((s_pt[0] + a_pt[0]) / 2.0, (s_pt[1] + a_pt[1]) / 2.0)
    # Septal wall: bow toward LV = opposite cavity (lateral) side.
    dir_sa = _bezier_arc_dir_toward(s_pt, a_pt, l_pt)
    ctrl_sa = (
        mid_sa[0] - dir_sa[0] * chord_sa * _SEPTAL_CTRL_FRAC,
        mid_sa[1] - dir_sa[1] * chord_sa * _SEPTAL_CTRL_FRAC,
    )

    chord_al = math.hypot(l_pt[0] - a_pt[0], l_pt[1] - a_pt[1])
    mid_al = ((a_pt[0] + l_pt[0]) / 2.0, (a_pt[1] + l_pt[1]) / 2.0)
    toward_septal = _bezier_arc_dir_toward(a_pt, l_pt, s_pt)
    dir_al = (-toward_septal[0], -toward_septal[1])
    ctrl_al = (
        mid_al[0] + dir_al[0] * chord_al * _FREE_WALL_CTRL_FRAC,
        mid_al[1] + dir_al[1] * chord_al * _FREE_WALL_CTRL_FRAC,
    )

    n1 = max(3, num_points // 2)
    n2 = max(3, num_points - n1 + 1)
    arc1 = _quadratic_bezier(s_pt, ctrl_sa, a_pt, n1)
    arc2 = _quadratic_bezier(a_pt, ctrl_al, l_pt, n2)

    warped = arc1 + arc2[1:]
    warped = _resample_polyline(warped, num_nodes=num_points)
    warped[0] = s_pt
    warped[-1] = l_pt
    return warped


def warp_rv_quarter_sine_open_arc(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    num_points: int = 81,
) -> list[tuple[float, float]]:
    """Backward-compatible alias for the crescent template."""
    return warp_rv_crescent_open_arc(
        septal,
        lateral,
        apex,
        num_points=num_points,
    )
