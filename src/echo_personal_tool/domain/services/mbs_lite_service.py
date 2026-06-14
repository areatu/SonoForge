"""MBS-lite: parametric LV contour from three landmarks."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.services.active_contour_refine import (
    ActiveContourConfig,
    refine_open_arc,
)
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


def build_lame_template_for_contour(contour: Contour) -> list[tuple[float, float]]:
    """Regenerate Lamé template resampled to contour node count."""
    if contour.mitral_annulus is None:
        return list(contour.points)
    septal, lateral = contour.mitral_annulus
    apex = contour.apex_landmark or infer_apex_from_open_arc(
        contour.points, septal, lateral
    )
    warped = warp_lame_open_arc(
        septal,
        lateral,
        apex,
        view=contour.view,
        phase=contour.phase,
        num_points=_TEMPLATE_POINT_COUNT,
    )
    return resample_open_arc_landmarks(
        warped,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=len(contour.points),
    )


def refine_open_arc_contour(frame: np.ndarray, contour: Contour) -> tuple[Contour, str]:
    """Refine open-arc border: gradient active contour with Laplacian fallback."""
    if contour.mitral_annulus is None or len(contour.points) < 3:
        return contour, "geometry"

    septal, lateral = contour.mitral_annulus
    apex = contour.apex_landmark or infer_apex_from_open_arc(
        contour.points, septal, lateral
    )
    template = (
        build_lame_template_for_contour(contour)
        if contour.chamber.upper() == "LV"
        else list(contour.points)
    )

    try:
        if frame is not None and frame.size > 0:
            refined_points = refine_open_arc(
                frame,
                contour.points,
                contour.mitral_annulus,
                template_points=template,
                config=ActiveContourConfig(),
            )
            if _refined_is_sane(contour.points, refined_points, septal, lateral):
                contour.points = resample_open_arc_landmarks(
                    refined_points,
                    septal=septal,
                    lateral=lateral,
                    apex=apex,
                    num_nodes=contour.num_nodes or len(contour.points),
                )
                contour.mitral_annulus = (septal, lateral)
                if contour.apex_landmark is None:
                    contour.apex_landmark = apex
                return contour, "gradient"
    except (ValueError, FloatingPointError):
        pass

    return _smooth_contour_points(contour), "geometry"


def refine_model_contour(frame: np.ndarray, contour: Contour) -> tuple[Contour, str]:
    """Alias for refine_open_arc_contour."""
    return refine_open_arc_contour(frame, contour)


def _refined_is_sane(
    original: Sequence[tuple[float, float]],
    refined: Sequence[tuple[float, float]],
    septal: tuple[float, float],
    lateral: tuple[float, float],
) -> bool:
    if len(refined) != len(original):
        return False
    if refined[0] != septal and math.hypot(
        refined[0][0] - septal[0], refined[0][1] - septal[1]
    ) > 2.0:
        return False
    if refined[-1] != lateral and math.hypot(
        refined[-1][0] - lateral[0], refined[-1][1] - lateral[1]
    ) > 2.0:
        return False
    orig_area = _polyline_length(original)
    new_area = _polyline_length(refined)
    if orig_area <= 0.0:
        return True
    ratio = new_area / orig_area
    return 0.5 <= ratio <= 2.0


def _polyline_length(points: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    for index in range(1, len(points)):
        dx = points[index][0] - points[index - 1][0]
        dy = points[index][1] - points[index - 1][1]
        total += math.hypot(dx, dy)
    return total


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
    length = math.hypot(lateral[0] - septal[0], lateral[1] - septal[1])
    if length < _MIN_ANNULUS_LENGTH_PX:
        msg = "mitral annulus length must be positive"
        raise ValueError(msg)
    if point_line_distance(apex, septal, lateral) < _MIN_APEX_DISTANCE_PX:
        msg = "apex must be off the mitral annulus line"
        raise ValueError(msg)
