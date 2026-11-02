"""Unit tests for LV Bézier cubic-spline contour."""

from __future__ import annotations

import math

import pytest

from echo_personal_tool.domain.services.contour_geometry import point_line_distance
from echo_personal_tool.domain.services.lv_bezier_contour import (
    LvBezierParams,
    _build_control_points,
    _sample_cubic_spline,
    fit_lv_bezier_contour,
)


def test_bezier_pins_ma_endpoints() -> None:
    septal = (10.0, 40.0)
    lateral = (50.0, 40.0)
    apex = (30.0, 10.0)
    contour = fit_lv_bezier_contour(septal, lateral, apex)
    assert contour.points[0] == pytest.approx(septal, abs=1e-6)
    assert contour.points[-1] == pytest.approx(lateral, abs=1e-6)


def test_bezier_passes_through_user_apex() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (35.0, 55.0)
    contour = fit_lv_bezier_contour(septal, lateral, apex)
    closest = min(
        contour.points,
        key=lambda p: (p[0] - apex[0]) ** 2 + (p[1] - apex[1]) ** 2,
    )
    assert math.hypot(closest[0] - apex[0], closest[1] - apex[1]) < 5.0


def test_bezier_apex_near_max_ma_distance() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    contour = fit_lv_bezier_contour(septal, lateral, apex)
    max_point = max(contour.points, key=lambda p: point_line_distance(p, septal, lateral))
    max_height = point_line_distance(max_point, septal, lateral)
    apex_height = point_line_distance(apex, septal, lateral)
    assert max_height == pytest.approx(apex_height, rel=0.05, abs=2.0)


def test_bezier_arc_not_triangle() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    contour = fit_lv_bezier_contour(septal, lateral, apex)
    quarter = contour.points[len(contour.points) // 4]
    triangle_x = 0.25 * apex[0]
    triangle_y = 0.25 * apex[1]
    assert quarter[0] > triangle_x + 3.0
    assert quarter[1] > triangle_y + 2.0


def test_bezier_control_points_produce_s_shape() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    pts = _build_control_points(
        septal,
        lateral,
        apex,
        septal_base_frac=0.04,
        septal_apex_frac=0.06,
        septal_shift_frac=0.03,
        septal_base_t=0.20,
        septal_apex_t=0.60,
        lateral_bow_frac=0.04,
        lateral_t=0.35,
    )
    # P0 = septal, P3 = apex, P5 = lateral
    assert pts[0] == septal
    assert pts[3] == apex
    assert pts[5] == lateral

    # P1 (базальная септальная) — +perp → справа от хорды septal→apex = в полость ЛЖ
    chord_sa_dx = apex[0] - septal[0]
    chord_sa_dy = apex[1] - septal[1]
    p1_side = chord_sa_dx * (pts[1][1] - septal[1]) - chord_sa_dy * (pts[1][0] - septal[0])
    assert p1_side < 0  # cross < 0 = правая сторона хорды = в полость ЛЖ

    # P2 (апикальная септальная) — −perp → слева от хорды septal→apex = в сторону ПЖ
    p2_side = chord_sa_dx * (pts[2][1] - septal[1]) - chord_sa_dy * (pts[2][0] - septal[0])
    assert p2_side > 0  # cross > 0 = левая сторона хорды = в сторону ПЖ

    # P4 — слева от chord apex→lateral (латеральная стенка наружу от полости)
    chord_al_dx = lateral[0] - apex[0]
    chord_al_dy = lateral[1] - apex[1]
    p4_side = chord_al_dx * (pts[4][1] - apex[1]) - chord_al_dy * (pts[4][0] - apex[0])
    assert p4_side > 0  # cross > 0 = левая сторона apex→lateral = наружу


def test_cubic_spline_smoothness() -> None:
    pts = [(0.0, 0.0), (15.0, 18.0), (35.0, 55.0), (50.0, 60.0), (80.0, 25.0), (100.0, 0.0)]
    sampled = _sample_cubic_spline(pts, 50)
    assert len(sampled) == 50
    # Sampled endpoints should match input endpoints
    assert sampled[0] == pytest.approx(pts[0], abs=1e-4)
    assert sampled[-1] == pytest.approx(pts[-1], abs=1e-4)


def test_septal_shift_moves_both_control_points() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    pts_unshifted = _build_control_points(
        septal,
        lateral,
        apex,
        septal_base_frac=0.04,
        septal_apex_frac=0.06,
        septal_shift_frac=0.0,
        septal_base_t=0.20,
        septal_apex_t=0.60,
        lateral_bow_frac=0.04,
        lateral_t=0.35,
    )
    pts_shifted = _build_control_points(
        septal,
        lateral,
        apex,
        septal_base_frac=0.04,
        septal_apex_frac=0.06,
        septal_shift_frac=0.05,
        septal_base_t=0.20,
        septal_apex_t=0.60,
        lateral_bow_frac=0.04,
        lateral_t=0.35,
    )
    # Обе септальные точки сдвинулись левее (меньше x)
    assert pts_shifted[1][0] < pts_unshifted[1][0]
    assert pts_shifted[2][0] < pts_unshifted[2][0]
    # Apex и lateral не изменились
    assert pts_shifted[3] == pts_unshifted[3]
    assert pts_shifted[5] == pts_unshifted[5]


def test_es_uses_different_defaults_than_ed() -> None:
    import math

    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    ed = fit_lv_bezier_contour(septal, lateral, apex, phase="ED")
    es = fit_lv_bezier_contour(septal, lateral, apex, phase="ES")
    max_dist = max(math.hypot(e[0] - d[0], e[1] - d[1]) for e, d in zip(es.points, ed.points))
    assert max_dist > 1.0


def test_fit_lv_bezier_contour_with_custom_params() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    params = LvBezierParams(septal_base_frac=0.06, septal_apex_frac=0.08, lateral_bow_frac=0.06)
    contour = fit_lv_bezier_contour(septal, lateral, apex, params=params)
    assert len(contour.points) > 0
    assert contour.points[0] == pytest.approx(septal, abs=1e-6)
    assert contour.points[-1] == pytest.approx(lateral, abs=1e-6)
    max_height = max(point_line_distance(p, septal, lateral) for p in contour.points)
    apex_height = point_line_distance(apex, septal, lateral)
    assert max_height >= apex_height * 0.95
