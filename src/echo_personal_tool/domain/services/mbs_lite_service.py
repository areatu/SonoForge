"""MBS-lite: parametric LV contour from three landmarks."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace

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
from echo_personal_tool.domain.services.lv_bezier_contour import (
    build_lv_bezier_template_for_contour,
    fit_lv_bezier_contour,
)
from echo_personal_tool.domain.services.rv_shape_template import (
    RV_FAC_NODE_COUNT,
    warp_rv_crescent_open_arc,
)
from echo_personal_tool.domain.services.stepped_border_refine import (
    format_stepped_refine_status,
    next_refine_step,
    run_stepped_refine_pass,
)

_MIN_ANNULUS_LENGTH_PX = 10.0
_MIN_APEX_DISTANCE_PX = 3.0
_TEMPLATE_POINT_COUNT = 81

# LA / RA open-arc template: short diameter = long diameter × ratio (default 85%).
# Long diameter = MA midpoint → apex; short axis is perpendicular to that line.
_ATRIAL_ELLIPSE_SHORT_AXIS_RATIO = 0.85


def _adaptive_superellipse_n(aspect_ratio: float) -> float:
    """Compute superellipse exponent from short/long axis ratio.

    aspect_ratio ~0.4 -> n=2.0 (ellipse)
    aspect_ratio ~0.85 -> n=3.5 (rounded rectangle)
    """
    return 2.0 + 2.0 * max(0.0, min(1.0, (aspect_ratio - 0.4) / 0.45))


def _warp_elliptical_open_arc(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    num_points: int = 81,
    short_axis_ratio: float = _ATRIAL_ELLIPSE_SHORT_AXIS_RATIO,
) -> list[tuple[float, float]]:
    """Sample open arc as a half-ellipse for LA/RA Simpson (atrial length axis)."""
    if num_points < 3:
        msg = "num_points must be at least 3"
        raise ValueError(msg)
    if not 0.0 < short_axis_ratio <= 1.0:
        msg = "short_axis_ratio must be in (0, 1]"
        raise ValueError(msg)

    ma_dx = lateral[0] - septal[0]
    ma_dy = lateral[1] - septal[1]
    ma_length = math.hypot(ma_dx, ma_dy)
    if ma_length <= 0.0:
        msg = "mitral annulus length must be positive"
        raise ValueError(msg)

    mid_x = (septal[0] + lateral[0]) / 2.0
    mid_y = (septal[1] + lateral[1]) / 2.0
    long_dx = apex[0] - mid_x
    long_dy = apex[1] - mid_y
    long_length = math.hypot(long_dx, long_dy)
    if long_length <= 0.0:
        msg = "apex must be off the mitral annulus line"
        raise ValueError(msg)

    long_x = long_dx / long_length
    long_y = long_dy / long_length
    short_u_x = ma_dx / ma_length
    short_u_y = ma_dy / ma_length
    short_half = (long_length * short_axis_ratio) / 2.0

    warped: list[tuple[float, float]] = []
    for index in range(num_points):
        t = index / (num_points - 1)
        theta = math.pi * (1.0 - t)
        offset_short = short_half * math.cos(theta)
        offset_long = long_length * math.sin(theta)
        warped.append(
            (
                mid_x + offset_short * short_u_x + offset_long * long_x,
                mid_y + offset_short * short_u_y + offset_long * long_y,
            )
        )
    warped[0] = septal
    warped[-1] = lateral
    return warped


def _warp_superellipse_open_arc(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    num_points: int = 81,
    short_axis_ratio: float = _ATRIAL_ELLIPSE_SHORT_AXIS_RATIO,
    n: float | None = None,
) -> list[tuple[float, float]]:
    """Sample open arc as a half-superellipse for LA/RA.

    When n=2 this is equivalent to a half-ellipse. Higher n produces
    rounded-rectangle shapes that better match typical atrial geometry.
    If *n* is None, the exponent is chosen adaptively from the aspect ratio.
    """
    if num_points < 3:
        msg = "num_points must be at least 3"
        raise ValueError(msg)
    if not 0.0 < short_axis_ratio <= 1.0:
        msg = "short_axis_ratio must be in (0, 1]"
        raise ValueError(msg)

    ma_dx = lateral[0] - septal[0]
    ma_dy = lateral[1] - septal[1]
    ma_length = math.hypot(ma_dx, ma_dy)
    if ma_length <= 0.0:
        msg = "mitral annulus length must be positive"
        raise ValueError(msg)

    mid_x = (septal[0] + lateral[0]) / 2.0
    mid_y = (septal[1] + lateral[1]) / 2.0
    long_dx = apex[0] - mid_x
    long_dy = apex[1] - mid_y
    long_length = math.hypot(long_dx, long_dy)
    if long_length <= 0.0:
        msg = "apex must be off the mitral annulus line"
        raise ValueError(msg)

    long_x = long_dx / long_length
    long_y = long_dy / long_length
    short_u_x = ma_dx / ma_length
    short_u_y = ma_dy / ma_length
    short_half = (long_length * short_axis_ratio) / 2.0

    if n is None:
        aspect_ratio = (short_half * 2.0) / long_length
        n = _adaptive_superellipse_n(aspect_ratio)

    exp = 2.0 / n

    warped: list[tuple[float, float]] = []
    for index in range(num_points):
        t = index / (num_points - 1)
        theta = math.pi * (1.0 - t)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        # |cos(theta)|^exp with sign preservation
        offset_short = short_half * math.copysign(abs(cos_t) ** exp, cos_t)
        offset_long = long_length * math.copysign(abs(sin_t) ** exp, sin_t)
        warped.append(
            (
                mid_x + offset_short * short_u_x + offset_long * long_x,
                mid_y + offset_short * short_u_y + offset_long * long_y,
            )
        )
    warped[0] = septal
    warped[-1] = lateral
    return warped


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
    chamber_key = chamber.upper()
    if chamber_key not in {"LV", "LA", "RA", "RV"}:
        msg = "fit_contour_from_landmarks supports LV, LA, RA, and RV only"
        raise ValueError(msg)

    _validate_landmarks(septal, lateral, apex)

    node_count = RV_FAC_NODE_COUNT if chamber_key == "RV" else num_nodes

    if chamber_key == "LV":
        warped = fit_lv_bezier_contour(
            septal,
            lateral,
            apex,
            view=view,
            phase=phase,
            chamber=chamber,
            num_nodes=_TEMPLATE_POINT_COUNT,
        ).points
    elif chamber_key == "RV":
        warped = warp_rv_crescent_open_arc(
            septal,
            lateral,
            apex,
            num_points=_TEMPLATE_POINT_COUNT,
        )
    else:
        warped = _warp_superellipse_open_arc(
            septal,
            lateral,
            apex,
            num_points=_TEMPLATE_POINT_COUNT,
            short_axis_ratio=_ATRIAL_ELLIPSE_SHORT_AXIS_RATIO,
        )
    resampled = resample_open_arc_landmarks(
        warped,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=node_count,
    )
    return Contour(
        phase=phase,
        view=view,
        chamber=chamber,
        mitral_annulus=(septal, lateral),
        apex_landmark=apex,
        points=resampled,
        source="model",
        num_nodes=node_count,
    )


def infer_apex_from_open_arc(
    points: Sequence[tuple[float, float]],
    septal: tuple[float, float],
    lateral: tuple[float, float],
) -> tuple[float, float]:
    """Infer apex landmark as interior point farthest from MA chord."""
    return apex_point(points, (septal, lateral))


def build_atrial_ellipse_template_for_contour(contour: Contour) -> list[tuple[float, float]]:
    """Regenerate atrial superellipse template resampled to contour node count."""
    if contour.mitral_annulus is None:
        return list(contour.points)
    septal, lateral = contour.mitral_annulus
    apex = contour.apex_landmark or infer_apex_from_open_arc(contour.points, septal, lateral)
    warped = _warp_superellipse_open_arc(
        septal,
        lateral,
        apex,
        num_points=_TEMPLATE_POINT_COUNT,
        short_axis_ratio=_ATRIAL_ELLIPSE_SHORT_AXIS_RATIO,
    )
    return resample_open_arc_landmarks(
        warped,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=len(contour.points),
    )


def build_rv_quarter_sine_template_for_contour(contour: Contour) -> list[tuple[float, float]]:
    """Regenerate RV quarter-sine template resampled to contour node count."""
    if contour.mitral_annulus is None:
        return list(contour.points)
    septal, lateral = contour.mitral_annulus
    apex = contour.apex_landmark or infer_apex_from_open_arc(contour.points, septal, lateral)
    warped = warp_rv_crescent_open_arc(
        septal,
        lateral,
        apex,
        num_points=_TEMPLATE_POINT_COUNT,
    )
    return resample_open_arc_landmarks(
        warped,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=len(contour.points),
    )


def refine_open_arc_contour(
    frame: np.ndarray,
    contour: Contour,
    *,
    display_levels: tuple[float, float] | None = None,
    cine: bool = False,
) -> tuple[Contour, str]:
    """Refine open-arc: directed edge snap for ai/manual; active contour for model."""
    if contour.mitral_annulus is None or len(contour.points) < 3:
        return contour, "geometry"

    septal, lateral = contour.mitral_annulus
    apex = contour.apex_landmark or infer_apex_from_open_arc(contour.points, septal, lateral)
    original_points = list(contour.points)

    if frame is not None and frame.size > 0 and contour.source in {"ai", "manual"}:
        next_step = next_refine_step(contour.refine_step, source=contour.source)
        locked = frozenset(contour.refine_locked_indices)
        result = run_stepped_refine_pass(
            frame,
            original_points,
            annulus=(septal, lateral),
            locked_indices=locked,
            step=next_step,
            display_levels=display_levels,
            cine=cine,
            smooth_blend=0.25 if cine else None,
            smooth_iterations=2 if cine else None,
        )
        interior_count = max(0, len(original_points) - 2)
        status = format_stepped_refine_status(
            step=result.step,
            locked_count=len(result.locked_indices),
            interior_count=interior_count,
            newly_locked=result.newly_locked,
        )
        if _refined_is_sane(
            original_points,
            result.points,
            septal,
            lateral,
            source=contour.source,
        ):
            new_apex = apex if contour.apex_landmark is None else contour.apex_landmark
            contour = replace(
                contour,
                points=result.points,
                refine_step=result.step,
                refine_locked_indices=tuple(sorted(result.locked_indices)),
                mitral_annulus=(septal, lateral),
                apex_landmark=new_apex,
            )
            return contour, status
        return contour, f"{status} (rejected)"

    template = _refine_internal_template(contour)
    try:
        if frame is not None and frame.size > 0:
            refined_points = refine_open_arc(
                frame,
                original_points,
                contour.mitral_annulus,
                template_points=template,
                config=_active_contour_config_for_contour(contour, cine=cine),
                display_levels=display_levels,
            )
            if _refined_is_sane(
                original_points,
                refined_points,
                septal,
                lateral,
                source=contour.source,
            ):
                new_apex = apex if contour.apex_landmark is None else contour.apex_landmark
                contour = replace(
                    contour,
                    points=resample_open_arc_landmarks(
                        refined_points,
                        septal=septal,
                        lateral=lateral,
                        apex=apex,
                        num_nodes=contour.num_nodes or len(contour.points),
                    ),
                    mitral_annulus=(septal, lateral),
                    apex_landmark=new_apex,
                )
                return contour, "gradient"
    except (ValueError, FloatingPointError):
        pass

    return _smooth_contour_points(contour), "geometry"


def _refine_internal_template(contour: Contour) -> list[tuple[float, float]]:
    """Active-contour prior: ONNX/manual shape; template warp for model-fit contours."""
    if contour.source != "model":
        return list(contour.points)
    chamber = contour.chamber.upper()
    if chamber == "LV":
        return build_lv_bezier_template_for_contour(contour)
    if chamber in {"LA", "RA"}:
        return build_atrial_ellipse_template_for_contour(contour)
    if chamber == "RV":
        return build_rv_quarter_sine_template_for_contour(contour)
    return list(contour.points)


def _active_contour_config_for_contour(
    contour: Contour,
    *,
    cine: bool = False,
) -> ActiveContourConfig:
    if contour.source == "manual":
        return ActiveContourConfig(
            search_radius_px=12.0,
            k_int=0.2,
            k_ext=1.0,
            k_smooth=0.15,
            step_size=0.3,
            max_iterations=40,
        )
    if cine:
        return ActiveContourConfig(
            search_radius_px=6.0,
            k_int=0.5,
            k_ext=0.4,
            k_smooth=0.3,
            step_size=0.25,
            max_iterations=40,
        )
    return ActiveContourConfig(k_smooth=0.2, max_iterations=50)


def _refined_is_sane(
    original: Sequence[tuple[float, float]],
    refined: Sequence[tuple[float, float]],
    septal: tuple[float, float],
    lateral: tuple[float, float],
    *,
    source: str = "",
) -> bool:
    if len(refined) != len(original):
        return False
    if refined[0] != septal and math.hypot(refined[0][0] - septal[0], refined[0][1] - septal[1]) > 2.0:
        return False
    if refined[-1] != lateral and math.hypot(refined[-1][0] - lateral[0], refined[-1][1] - lateral[1]) > 2.0:
        return False
    orig_area = _polyline_length(original)
    new_area = _polyline_length(refined)
    if orig_area <= 0.0:
        return True
    ratio = new_area / orig_area
    min_ratio = 0.45 if source in {"ai", "manual"} else 0.5
    max_ratio = 2.5 if source in {"ai", "manual"} else 2.0
    if not (min_ratio <= ratio <= max_ratio):
        return False
    orig_depth = _open_arc_depth(original, septal, lateral)
    new_depth = _open_arc_depth(refined, septal, lateral)
    if orig_depth > 5.0 and new_depth < 0.82 * orig_depth:
        return False
    return True


def refine_model_contour(frame: np.ndarray, contour: Contour) -> tuple[Contour, str]:
    """Alias for refine_open_arc_contour."""
    return refine_open_arc_contour(frame, contour)


def _polyline_length(points: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    for index in range(1, len(points)):
        dx = points[index][0] - points[index - 1][0]
        dy = points[index][1] - points[index - 1][1]
        total += math.hypot(dx, dy)
    return total


def _open_arc_depth(
    points: Sequence[tuple[float, float]],
    septal: tuple[float, float],
    lateral: tuple[float, float],
) -> float:
    if len(points) < 3:
        return 0.0
    return max(point_line_distance(point, septal, lateral) for point in points[1:-1])


def _smooth_contour_points(contour: Contour) -> Contour:
    if contour.mitral_annulus is None or len(contour.points) < 3:
        return contour

    septal, lateral = contour.mitral_annulus
    apex = contour.apex_landmark or infer_apex_from_open_arc(contour.points, septal, lateral)
    smoothed = smooth_open_arc(
        contour.points,
        contour.mitral_annulus,
        apex=apex,
    )
    num_nodes = contour.num_nodes or DEFAULT_NODE_COUNT
    new_apex = apex if contour.apex_landmark is None else contour.apex_landmark
    contour = replace(
        contour,
        points=resample_open_arc_landmarks(
            smoothed,
            septal=septal,
            lateral=lateral,
            apex=apex,
            num_nodes=num_nodes,
        ),
        mitral_annulus=(septal, lateral),
        apex_landmark=new_apex,
    )
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
