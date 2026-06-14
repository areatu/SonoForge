"""Unit tests for MBS-lite contour fitting."""

from __future__ import annotations

import math

import numpy as np
import pytest

from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.services.contour_geometry import DEFAULT_NODE_COUNT
from echo_personal_tool.domain.services.lv_shape_template import (
    lame_profile_for_view_phase,
    warp_lame_open_arc,
)
from echo_personal_tool.domain.services.mbs_lite_service import (
    fit_contour_from_landmarks,
    infer_apex_from_open_arc,
    refine_model_contour,
    refine_open_arc_contour,
)


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


def test_dome_arc_is_not_septal_apex_lateral_triangle() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    warped = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    quarter = warped[len(warped) // 4]
    triangle_x = 0.25 * apex[0]
    triangle_y = 0.25 * apex[1]
    assert quarter[0] > triangle_x + 10.0
    assert quarter[1] > triangle_y + 5.0


def test_fit_contour_dome_includes_lateral_blend_before_apex() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    warped = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    quarter = warped[len(warped) // 4]
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


def test_a2c_lame_profile_differs_from_a4c() -> None:
    a4c = lame_profile_for_view_phase("A4C", "ED")
    a2c = lame_profile_for_view_phase("A2C", "ED")
    assert a2c.n_lat != pytest.approx(a4c.n_lat)


def test_fit_contour_uses_a2c_profile_for_a2c_view() -> None:
    septal = (10.0, 40.0)
    lateral = (50.0, 40.0)
    apex = (22.0, 10.0)
    a4c_warp = warp_lame_open_arc(
        septal, lateral, apex, view="A4C", phase="ED", num_points=81
    )
    a2c_warp = warp_lame_open_arc(
        septal, lateral, apex, view="A2C", phase="ED", num_points=81
    )
    body_index = 75
    assert a4c_warp[body_index] != pytest.approx(a2c_warp[body_index], abs=0.5)


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
    contour.points = jagged
    apex_before = apex

    refined = refine_open_arc_contour(frame, contour)

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
    refined = refine_model_contour(frame, contour)
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
    contour.source = "manual"
    refined = refine_open_arc_contour(frame, contour)
    assert refined.source == "manual"
    assert len(refined.points) == DEFAULT_NODE_COUNT


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
