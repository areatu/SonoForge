"""MBS-lite: parametric LV contour from three landmarks."""

from __future__ import annotations

import math

import numpy as np

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.services.active_contour_refine import refine_open_arc
from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    point_line_distance,
    resample_open_arc,
)
from echo_personal_tool.domain.services.lv_shape_template import (
    ArcWarpProfile,
    warp_profile_for_view,
)

_MIN_ANNULUS_LENGTH_PX = 10.0
_MIN_APEX_DISTANCE_PX = 3.0
_TEMPLATE_POINT_COUNT = 81


def fit_contour_from_landmarks(
    *,
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    phase: str,
    view: str = "A4C",
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> Contour:
    """Fit an open-arc LV contour from mitral annulus and apex landmarks."""
    _validate_landmarks(septal, lateral, apex)

    warped = _warp_truncated_oval_arc(
        septal,
        lateral,
        apex,
        view=view,
        num_points=_TEMPLATE_POINT_COUNT,
    )
    resampled = resample_open_arc(warped, num_nodes=num_nodes)
    return Contour(
        phase=phase,
        view=view,
        mitral_annulus=(septal, lateral),
        points=resampled,
        source="model",
        num_nodes=num_nodes,
    )


def refine_open_arc_contour(frame: np.ndarray, contour: Contour) -> Contour:
    """Opt-in active contour refine on an existing open-arc contour."""
    return _refine_contour_points(frame, contour)


def refine_model_contour(frame: np.ndarray, contour: Contour) -> Contour:
    """Alias for refine_open_arc_contour."""
    return refine_open_arc_contour(frame, contour)


def _refine_contour_points(
    frame: np.ndarray,
    contour: Contour,
    *,
    template_points: list[tuple[float, float]] | None = None,
) -> Contour:
    if contour.mitral_annulus is None:
        return contour

    template = template_points if template_points is not None else list(contour.points)
    try:
        refined = refine_open_arc(
            frame,
            contour.points,
            contour.mitral_annulus,
            template_points=template,
        )
        contour.points = resample_open_arc(refined, num_nodes=contour.num_nodes)
    except ValueError:
        pass
    return contour


def _warp_truncated_oval_arc(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    view: str = "A4C",
    num_points: int,
    profile: ArcWarpProfile | None = None,
) -> list[tuple[float, float]]:
    """Sinusoidal dome over MA chord: septal → apex (mid) → lateral."""
    if num_points < 3:
        msg = "num_points must be at least 3"
        raise ValueError(msg)

    warp_profile = profile or warp_profile_for_view(view)
    mid_x = 0.5 * (septal[0] + lateral[0])
    mid_y = 0.5 * (septal[1] + lateral[1])
    offset_x = apex[0] - mid_x
    offset_y = apex[1] - mid_y
    warped: list[tuple[float, float]] = []
    for index in range(num_points):
        t = index / (num_points - 1)
        base_x = (1.0 - t) * septal[0] + t * lateral[0]
        base_y = (1.0 - t) * septal[1] + t * lateral[1]
        lift = _lift_height(t, warp_profile)
        warped.append((base_x + lift * offset_x, base_y + lift * offset_y))
    return warped


def _lift_height(t: float, profile: ArcWarpProfile) -> float:
    peak = max(0.05, min(0.95, 0.5 + profile.peak_bias))
    if t <= peak:
        phase = 0.5 * t / peak
    else:
        phase = 0.5 + 0.5 * (t - peak) / (1.0 - peak)
    return profile.apex_lift_scale * math.sin(math.pi * phase)


def _validate_landmarks(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
) -> None:
    annulus_length = math.hypot(lateral[0] - septal[0], lateral[1] - septal[1])
    if annulus_length < _MIN_ANNULUS_LENGTH_PX:
        msg = f"mitral annulus length must be at least {_MIN_ANNULUS_LENGTH_PX}px"
        raise ValueError(msg)

    apex_distance = point_line_distance(apex, septal, lateral)
    if apex_distance < _MIN_APEX_DISTANCE_PX:
        msg = f"apex must be at least {_MIN_APEX_DISTANCE_PX}px from mitral annulus"
        raise ValueError(msg)
