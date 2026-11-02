"""Unit tests for MBS-lite contour fitting."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.services.contour_geometry import DEFAULT_NODE_COUNT
from echo_personal_tool.domain.services.lv_bezier_contour import (
    build_lv_bezier_template_for_contour,
)
from echo_personal_tool.domain.services.mbs_lite_service import (
    _ATRIAL_ELLIPSE_SHORT_AXIS_RATIO,
    _warp_elliptical_open_arc,
    fit_contour_from_landmarks,
    infer_apex_from_open_arc,
    refine_model_contour,
    refine_open_arc_contour,
)
from echo_personal_tool.domain.services.rv_shape_template import RV_FAC_NODE_COUNT


def test_fit_contour_from_landmarks_basic() -> None:
    septal = (10.0, 40.0)
    lateral = (50.0, 40.0)
    apex = (30.0, 10.0)

    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
    )

    assert contour.is_open_arc
    assert contour.source == "model"
    assert contour.mitral_annulus == (septal, lateral)
    assert len(contour.points) == DEFAULT_NODE_COUNT
    assert contour.points[0] == pytest.approx(septal, abs=1e-3)
    assert contour.points[-1] == pytest.approx(lateral, abs=1e-3)


def test_fit_contour_dome_is_not_triangle() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
    )
    quarter = contour.points[len(contour.points) // 4]
    triangle_x = 0.25 * apex[0]
    triangle_y = 0.25 * apex[1]
    assert quarter[0] > triangle_x + 3.0
    assert quarter[1] > triangle_y + 2.0
    assert 0.0 < quarter[0] < 100.0
    assert quarter[1] > 0.0


def test_fit_contour_apex_is_user_landmark() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (35.0, 55.0)

    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
    )
    assert contour.apex_landmark == apex
    closest = min(
        contour.points,
        key=lambda point: (point[0] - apex[0]) ** 2 + (point[1] - apex[1]) ** 2,
    )
    assert math.hypot(closest[0] - apex[0], closest[1] - apex[1]) < 5.0


def test_fit_contour_apex_near_user_landmark() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)

    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
    )
    apex_on_arc = max(contour.points, key=lambda point: point[1])
    apex_dist = math.hypot(apex_on_arc[0] - apex[0], apex_on_arc[1] - apex[1])
    assert apex_dist < 5.0


def test_fit_contour_rejects_short_annulus() -> None:
    with pytest.raises(ValueError, match="mitral annulus length"):
        fit_contour_from_landmarks(
            septal=(0.0, 0.0),
            lateral=(5.0, 0.0),
            apex=(2.0, 20.0),
            phase="ED",
        )


def test_fit_contour_rejects_apex_on_annulus() -> None:
    with pytest.raises(ValueError, match="apex must be"):
        fit_contour_from_landmarks(
            septal=(0.0, 0.0),
            lateral=(50.0, 0.0),
            apex=(25.0, 0.0),
            phase="ED",
        )


def test_fit_contour_la_matches_elliptical_template() -> None:
    from echo_personal_tool.domain.services.contour_geometry import resample_open_arc_landmarks

    septal = (10.0, 40.0)
    lateral = (50.0, 40.0)
    apex = (30.0, 10.0)
    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ES",
        view="A4C",
        chamber="LA",
    )
    elliptical = _warp_elliptical_open_arc(
        septal,
        lateral,
        apex,
        num_points=81,
        short_axis_ratio=_ATRIAL_ELLIPSE_SHORT_AXIS_RATIO,
    )
    expected = resample_open_arc_landmarks(
        elliptical,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=DEFAULT_NODE_COUNT,
    )
    mid_index = len(contour.points) // 2
    assert contour.points[mid_index] == pytest.approx(expected[mid_index], abs=0.5)


def test_fit_contour_rv_matches_crescent_template() -> None:
    from echo_personal_tool.domain.services.contour_geometry import resample_open_arc_landmarks
    from echo_personal_tool.domain.services.rv_shape_template import warp_rv_crescent_open_arc

    septal = (80.0, 20.0)
    lateral = (20.0, 20.0)
    apex = (50.0, 70.0)
    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
        view="A4C",
        chamber="RV",
    )
    expected_arc = warp_rv_crescent_open_arc(septal, lateral, apex, num_points=81)
    expected = resample_open_arc_landmarks(
        expected_arc,
        septal=septal,
        lateral=lateral,
        apex=apex,
        num_nodes=RV_FAC_NODE_COUNT,
    )
    assert len(contour.points) == RV_FAC_NODE_COUNT
    mid_index = len(contour.points) // 2
    assert contour.points[mid_index] == pytest.approx(expected[mid_index], abs=0.5)


def test_infer_apex_from_open_arc_uses_max_ma_distance() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=(50.0, 60.0),
        phase="ED",
    )
    inferred = infer_apex_from_open_arc(contour.points, septal, lateral)
    assert inferred[1] > 30.0


def test_refine_open_arc_contour_smooths_jagged_arc() -> None:
    frame = np.zeros((120, 120), dtype=np.float64)
    septal = (20.0, 90.0)
    lateral = (90.0, 90.0)
    apex = (55.0, 25.0)
    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
    )
    jagged = list(contour.points)
    for index in range(2, len(jagged) - 2, 2):
        x, y = jagged[index]
        jagged[index] = (x + 6.0, y - 4.0)
    contour = replace(contour, points=jagged)
    apex_before = apex

    refined, mode = refine_open_arc_contour(frame, contour)

    assert mode in {"gradient", "geometry"}
    assert refined.points[0] == pytest.approx(septal, abs=1e-3)
    assert refined.points[-1] == pytest.approx(lateral, abs=1e-3)
    assert refined.apex_landmark == pytest.approx(apex_before, abs=1e-3)
    closest = min(
        refined.points,
        key=lambda point: (point[0] - apex_before[0]) ** 2 + (point[1] - apex_before[1]) ** 2,
    )
    assert math.hypot(closest[0] - apex_before[0], closest[1] - apex_before[1]) < 8.0
    roughness_before = _open_arc_roughness(jagged)
    roughness_after = _open_arc_roughness(refined.points)
    assert roughness_after < roughness_before


def _open_arc_roughness(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for index in range(1, len(points) - 1):
        x0, y0 = points[index - 1]
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        total += abs(x0 - 2.0 * x1 + x2) + abs(y0 - 2.0 * y1 + y2)
    return total


def test_refine_model_contour_opt_in() -> None:
    frame = np.zeros((120, 120), dtype=np.float64)
    frame[20:100, 20:100] = 200.0
    contour = fit_contour_from_landmarks(
        septal=(30.0, 90.0),
        lateral=(90.0, 90.0),
        apex=(60.0, 20.0),
        phase="ED",
    )
    refined, _mode = refine_model_contour(frame, contour)
    assert refined.source == "model"
    assert len(refined.points) == DEFAULT_NODE_COUNT


def test_refine_open_arc_contour_preserves_manual_source() -> None:
    frame = np.zeros((120, 120), dtype=np.float64)
    frame[20:100, 20:100] = 200.0
    contour = fit_contour_from_landmarks(
        septal=(30.0, 90.0),
        lateral=(90.0, 90.0),
        apex=(60.0, 20.0),
        phase="ED",
    )
    contour = replace(contour, source="manual")
    refined, _mode = refine_open_arc_contour(frame, contour)
    assert refined.source == "manual"
    assert len(refined.points) == DEFAULT_NODE_COUNT


def test_refine_ai_stepped_refine_locks_on_ring() -> None:
    frame = np.zeros((128, 128), dtype=np.float64)
    center = 63.5
    y_values, x_values = np.mgrid[0:128, 0:128]
    distance = np.hypot(x_values - center, y_values - center)
    frame[(distance > 28.0) & (distance <= 42.0)] = 220.0

    septal = (center - 20.0, center)
    lateral = (center + 20.0, center)
    ai_points = [
        (center + 22.0 * math.cos(angle), center - 22.0 * math.sin(angle)) for angle in np.linspace(math.pi, 0.0, 32)
    ]
    ai_points[0] = septal
    ai_points[-1] = lateral
    ai_contour = Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        mitral_annulus=(septal, lateral),
        apex_landmark=(center, 20.0),
        points=ai_points,
        source="ai",
        num_nodes=len(ai_points),
    )

    current = ai_contour
    for _ in range(8):
        current, mode = refine_open_arc_contour(frame, current)
        assert mode.startswith("step:") or mode.startswith("complete")
        if current.refine_locked_indices:
            break
    assert len(current.refine_locked_indices) > 0

    locked_positions = {index: current.points[index] for index in current.refine_locked_indices}
    next_pass, _mode2 = refine_open_arc_contour(frame, current)
    for index, position in locked_positions.items():
        assert next_pass.points[index] == position


def test_refine_ai_contour_does_not_collapse_to_bezier_template() -> None:
    from echo_personal_tool.domain.services.active_contour_refine import ActiveContourConfig, refine_open_arc
    from echo_personal_tool.domain.services.mbs_lite_service import _refine_internal_template

    frame = np.zeros((128, 128), dtype=np.float64)
    center = 63.5
    y_values, x_values = np.mgrid[0:128, 0:128]
    distance = np.hypot(x_values - center, y_values - center)
    frame[(distance > 28.0) & (distance <= 42.0)] = 220.0

    septal = (center - 20.0, center)
    lateral = (center + 20.0, center)
    apex = (center, 20.0)
    model = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ED",
    )
    bezier_template = build_lv_bezier_template_for_contour(model)
    ai_points = list(model.points)
    for index in range(4, len(ai_points) - 4, 3):
        x, y = ai_points[index]
        ai_points[index] = (x + 8.0, y + 5.0)

    ai_contour = Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        mitral_annulus=(septal, lateral),
        apex_landmark=apex,
        points=ai_points,
        source="ai",
        num_nodes=len(ai_points),
    )
    assert _refine_internal_template(ai_contour) == ai_points

    legacy = refine_open_arc(
        frame,
        ai_points,
        (septal, lateral),
        template_points=bezier_template,
        config=ActiveContourConfig(),
    )
    refined, mode = refine_open_arc_contour(frame, ai_contour)
    assert mode.startswith("step:")

    def mean_distance(
        target: list[tuple[float, float]],
        reference: list[tuple[float, float]],
    ) -> float:
        total = 0.0
        for left, right in zip(target, reference, strict=True):
            total += math.hypot(left[0] - right[0], left[1] - right[1])
        return total / len(target)

    legacy_dist = mean_distance(legacy, bezier_template)
    refined_dist = mean_distance(refined.points, bezier_template)
    assert refined_dist > legacy_dist * 1.5


def test_fit_contour_balances_nodes_for_off_center_apex() -> None:
    """Off-center apex must not collapse node count on the short side."""
    septal = (20.0, 90.0)
    lateral = (90.0, 90.0)
    apex = (35.0, 30.0)
    contour = fit_contour_from_landmarks(
        septal=septal,
        lateral=lateral,
        apex=apex,
        phase="ES",
    )
    assert len(contour.points) == DEFAULT_NODE_COUNT
    seg = [
        math.hypot(
            contour.points[index + 1][0] - contour.points[index][0],
            contour.points[index + 1][1] - contour.points[index][1],
        )
        for index in range(len(contour.points) - 1)
    ]
    mean = sum(seg) / len(seg)
    assert (max(seg) - min(seg)) / mean < 1.5


def test_fit_contour_simpson_volume_positive() -> None:
    ed = fit_contour_from_landmarks(
        septal=(10.0, 40.0),
        lateral=(50.0, 40.0),
        apex=(30.0, 10.0),
        phase="ED",
    )
    es = fit_contour_from_landmarks(
        septal=(12.0, 40.0),
        lateral=(48.0, 40.0),
        apex=(30.0, 15.0),
        phase="ES",
    )
    result = calculate((ed, es), (0.5, 0.5))
    assert result is not None
    assert result.a4c is not None
    assert result.a4c.edv_ml > 0.0
    assert result.a4c.esv_ml > 0.0
    assert result.lvef_percent > 0.0
