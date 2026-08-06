"""LV endocardial contour via cubic spline through 6 control points (S-образная перегородка)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import CubicSpline

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    resample_open_arc_landmarks,
)


@dataclass(frozen=True)
class LvBezierParams:
    # Базальная часть перегородки — смещение в сторону полости ЛЖ (+perp).
    # Больше = сильнее изгиб влево у основания. 0.02–0.08.
    septal_base_frac: float = 0.04

    # Глобальный сдвиг всей септальной стороны влево (к ПЖ).
    # Добавляется к обоим септальным точкам как −perp * chord_sa * shift.
    # Больше = шире верхушка ЛЖ, сильнее вырез перегородки. 0.02–0.10.
    septal_shift_frac: float = 0.08

    # Апикальная часть перегородки — смещение в сторону ПЖ (−perp).
    # Больше = сильнее изгиб вправо ближе к верхушке. 0.04–0.12.
    septal_apex_frac: float = 0.09

    # Позиция базальной точки на хорде septal→apex. 0.15–0.35.
    # 0.2 = ближе к MA → плавный S-изгиб от основания.
    septal_base_t: float = 0.20

    # Позиция апикальной точки на хорде septal→apex. 0.50–0.75.
    # 0.6 = ближе к apex → перегиб в средней трети.
    septal_apex_t: float = 0.60

    # Латеральная стенка — смещение перпендикулярно хорде apex→lateral.
    # Больше = сильнее выгиб наружу. 0.02–0.10.
    lateral_bow_frac: float = 0.15

    # Позиция латеральной точки на хорде apex→lateral. 0.25–0.50.
    # 0.35 = ближе к MA → плавнее скругление apex.
    lateral_t: float = 0.5

    num_template_points: int = 81


_TEMPLATE_POINT_COUNT = 81
_MIN_CHORD_PX = 1e-9

LV_BEZIER_ED_DEFAULTS = LvBezierParams(
    septal_base_frac=0.04,
    septal_shift_frac=0.08,
    septal_apex_frac=0.09,
    septal_base_t=0.20,
    septal_apex_t=0.60,
    lateral_bow_frac=0.15,
    lateral_t=0.5,
)

LV_BEZIER_ES_DEFAULTS = LvBezierParams(
    septal_base_frac=0.08,
    septal_shift_frac=0.06,
    septal_apex_frac=0.0,
    septal_base_t=0.30,
    septal_apex_t=0.60,
    lateral_bow_frac=0.10,
    lateral_t=0.5,
)


def _params_for_phase(phase: str) -> LvBezierParams:
    if phase.upper() == "ES":
        return LV_BEZIER_ES_DEFAULTS
    return LV_BEZIER_ED_DEFAULTS


def _perp_toward(
    p: tuple[float, float],
    q: tuple[float, float],
    r: tuple[float, float],
) -> tuple[float, float]:
    """Unit perpendicular to chord p→q, pointing toward the side of r."""
    dx = q[0] - p[0]
    dy = q[1] - p[1]
    chord = math.hypot(dx, dy)
    if chord <= _MIN_CHORD_PX:
        return (0.0, 1.0)
    cross = dx * (r[1] - p[1]) - dy * (r[0] - p[0])
    if cross >= 0.0:
        perp_x, perp_y = -dy, dx
    else:
        perp_x, perp_y = dy, -dx
    perp_len = math.hypot(perp_x, perp_y)
    if perp_len <= _MIN_CHORD_PX:
        return (0.0, 1.0)
    return (perp_x / perp_len, perp_y / perp_len)


def _build_control_points(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    septal_base_frac: float,
    septal_apex_frac: float,
    septal_shift_frac: float,
    septal_base_t: float,
    septal_apex_t: float,
    lateral_bow_frac: float,
    lateral_t: float,
) -> list[tuple[float, float]]:
    """6 control points: P0=septal, P_base(к ЛЖ), P_apex(к ПЖ), P2=apex, P3, P4=lateral."""
    chord_sa = math.hypot(apex[0] - septal[0], apex[1] - septal[1])
    dir_sa = _perp_toward(septal, apex, lateral)

    shift_x = -dir_sa[0] * chord_sa * septal_shift_frac
    shift_y = -dir_sa[1] * chord_sa * septal_shift_frac

    # Базальная перегородка: +perp → в сторону полости ЛЖ + глобальный сдвиг к ПЖ
    p_base_x = (
        (1.0 - septal_base_t) * septal[0] + septal_base_t * apex[0] + dir_sa[0] * chord_sa * septal_base_frac + shift_x
    )
    p_base_y = (
        (1.0 - septal_base_t) * septal[1] + septal_base_t * apex[1] + dir_sa[1] * chord_sa * septal_base_frac + shift_y
    )

    # Апикальная перегородка: −perp → в сторону ПЖ + глобальный сдвиг к ПЖ
    p_apex_x = (
        (1.0 - septal_apex_t) * septal[0] + septal_apex_t * apex[0] - dir_sa[0] * chord_sa * septal_apex_frac + shift_x
    )
    p_apex_y = (
        (1.0 - septal_apex_t) * septal[1] + septal_apex_t * apex[1] - dir_sa[1] * chord_sa * septal_apex_frac + shift_y
    )

    # Латеральная стенка: −perp → наружу
    chord_al = math.hypot(lateral[0] - apex[0], lateral[1] - apex[1])
    dir_al = _perp_toward(apex, lateral, septal)
    p3_x = (1.0 - lateral_t) * apex[0] + lateral_t * lateral[0] - dir_al[0] * chord_al * lateral_bow_frac
    p3_y = (1.0 - lateral_t) * apex[1] + lateral_t * lateral[1] - dir_al[1] * chord_al * lateral_bow_frac

    return [
        septal,
        (p_base_x, p_base_y),
        (p_apex_x, p_apex_y),
        apex,
        (p3_x, p3_y),
        lateral,
    ]


def _sample_cubic_spline(
    pts: list[tuple[float, float]],
    num_points: int,
) -> list[tuple[float, float]]:
    if num_points < 2:
        return list(pts)

    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])

    t = np.zeros(len(pts))
    for i in range(1, len(pts)):
        t[i] = t[i - 1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])

    if t[-1] <= _MIN_CHORD_PX:
        return list(pts)

    t /= t[-1]

    cs_x = CubicSpline(t, xs, bc_type="natural")
    cs_y = CubicSpline(t, ys, bc_type="natural")

    t_sample = np.linspace(0.0, 1.0, num_points)
    return [(float(cs_x(ti)), float(cs_y(ti))) for ti in t_sample]


def fit_lv_bezier_contour(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    view: str = "A4C",
    phase: str = "ED",
    chamber: str = "LV",
    num_nodes: int = DEFAULT_NODE_COUNT,
    params: LvBezierParams | None = None,
) -> Contour:
    """Fit LV contour via cubic spline through 6 control points.

    Points: P0=septal  P_base(←ЛЖ)  P_apex(→ПЖ)  P2=apex  P3  P4=lateral
    """
    p = params or _params_for_phase(phase)

    cpts = _build_control_points(
        septal,
        lateral,
        apex,
        septal_base_frac=p.septal_base_frac,
        septal_apex_frac=p.septal_apex_frac,
        septal_shift_frac=p.septal_shift_frac,
        septal_base_t=p.septal_base_t,
        septal_apex_t=p.septal_apex_t,
        lateral_bow_frac=p.lateral_bow_frac,
        lateral_t=p.lateral_t,
    )

    warped = _sample_cubic_spline(cpts, p.num_template_points)

    resampled = resample_open_arc_landmarks(
        warped,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=num_nodes,
    )

    return Contour(
        phase=phase,
        view=view,
        chamber=chamber,
        mitral_annulus=(septal, lateral),
        apex_landmark=apex,
        points=resampled,
        source="model",
        num_nodes=num_nodes,
    )


def build_lv_bezier_template_for_contour(
    contour: Contour,
    *,
    params: LvBezierParams | None = None,
) -> list[tuple[float, float]]:
    """Regenerate LV Bézier template resampled to contour node count."""
    if contour.mitral_annulus is None:
        return list(contour.points)
    septal, lateral = contour.mitral_annulus
    apex = contour.apex_landmark or _infer_apex(contour)

    p = params or _params_for_phase(contour.phase)
    cpts = _build_control_points(
        septal,
        lateral,
        apex,
        septal_base_frac=p.septal_base_frac,
        septal_apex_frac=p.septal_apex_frac,
        septal_shift_frac=p.septal_shift_frac,
        septal_base_t=p.septal_base_t,
        septal_apex_t=p.septal_apex_t,
        lateral_bow_frac=p.lateral_bow_frac,
        lateral_t=p.lateral_t,
    )

    warped = _sample_cubic_spline(cpts, p.num_template_points)

    return resample_open_arc_landmarks(
        warped,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=len(contour.points),
    )


def _infer_apex(contour: Contour) -> tuple[float, float]:
    from echo_personal_tool.domain.services.contour_geometry import apex_point

    if contour.mitral_annulus is None:
        return (0.0, 0.0)
    return apex_point(contour.points, contour.mitral_annulus)
