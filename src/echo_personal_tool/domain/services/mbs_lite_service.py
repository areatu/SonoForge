"""MBS-lite: parametric LV contour from three landmarks."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    apex_point,
    point_line_distance,
    resample_open_arc_landmarks,
    smooth_open_arc,
)
from echo_personal_tool.domain.services.lv_shape_template import warp_lame_open_arc

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
    chamber: str = "LV",
    num_nodes: int = DEFAULT_NODE_COUNT,
) -> Contour:
    """Fit an open-arc contour from annulus and apex landmarks."""
    if chamber.upper() != "LV":
        msg = "fit_contour_from_landmarks supports LV only"
        raise ValueError(msg)

    _validate_landmarks(septal, lateral, apex)

    warped = warp_lame_open_arc(
        septal,
        lateral,
        apex,
        view=view,
        phase=phase,
        num_points=_TEMPLATE_POINT_COUNT,
    )
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


def infer_apex_from_open_arc(
    points: Sequence[tuple[float, float]],
    septal: tuple[float, float],
    lateral: tuple[float, float],
) -> tuple[float, float]:
    """Infer apex landmark as interior point farthest from MA chord."""
    return apex_point(points, (septal, lateral))


def refine_open_arc_contour(frame: np.ndarray, contour: Contour) -> Contour:
    """Smooth LV open-arc irregularities after manual node edits (R key)."""
    del frame  # smoothing is geometry-only; kept for API compatibility
    return _smooth_contour_points(contour)


def refine_model_contour(frame: np.ndarray, contour: Contour) -> Contour:
    """Alias for refine_open_arc_contour."""
    return refine_open_arc_contour(frame, contour)


def _smooth_contour_points(contour: Contour) -> Contour:
    if contour.mitral_annulus is None or len(contour.points) < 3:
        return contour

    septal, lateral = contour.mitral_annulus
    apex = contour.apex_landmark or infer_apex_from_open_arc(
        contour.points, septal, lateral
    )
    smoothed = smooth_open_arc(
        contour.points,
        contour.mitral_annulus,
        apex=apex,
    )
    num_nodes = contour.num_nodes or DEFAULT_NODE_COUNT
    contour.points = resample_open_arc_landmarks(
        smoothed,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=num_nodes,
    )
    contour.mitral_annulus = (septal, lateral)
    if contour.apex_landmark is None:
        contour.apex_landmark = apex
    return contour


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
