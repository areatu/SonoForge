"""Unit tests for LV Lamé open-arc template."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.contour_geometry import point_line_distance
from echo_personal_tool.domain.services.lv_shape_template import (
    LAME_A2C_ED,
    LAME_A2C_ES,
    LAME_A4C_ED,
    LAME_A4C_ES,
    lame_lift_height,
    lame_profile_for_view_phase,
    warp_lame_open_arc,
)


def test_lame_lift_height_high_at_ma_endpoints_with_footpoint_profile() -> None:
    """Foot-point warp pins S/L in warp_lame_open_arc; lift along chord stays high near ends."""
    profile = LAME_A4C_ED
    u_apex = 0.5
    ma_length = 100.0
    endpoint_lift = lame_lift_height(0.0, u_apex, ma_length, profile)
    peak_lift = lame_lift_height(u_apex, u_apex, ma_length, profile)
    assert endpoint_lift > 0.9
    assert peak_lift >= endpoint_lift


def test_lame_lift_height_peak_at_apex_projection() -> None:
    profile = LAME_A4C_ED
    u_apex = 0.5
    ma_length = 100.0
    peak = lame_lift_height(u_apex, u_apex, ma_length, profile)
    assert peak == pytest.approx(profile.lift_scale, abs=1e-6)
    assert peak > lame_lift_height(0.25, u_apex, ma_length, profile)
    assert peak > lame_lift_height(0.75, u_apex, ma_length, profile)


def test_lame_lift_height_monotonic_each_side() -> None:
    profile = LAME_A4C_ED
    u_apex = 0.5
    ma_length = 100.0
    septal_side = [
        lame_lift_height(u, u_apex, ma_length, profile)
        for u in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    ]
    lateral_side = [
        lame_lift_height(u, u_apex, ma_length, profile)
        for u in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    ]
    assert all(septal_side[i] <= septal_side[i + 1] for i in range(len(septal_side) - 1))
    assert all(lateral_side[i] >= lateral_side[i + 1] for i in range(len(lateral_side) - 1))


def test_lame_profile_for_view_phase_presets() -> None:
    assert lame_profile_for_view_phase("A4C", "ED") == LAME_A4C_ED
    assert lame_profile_for_view_phase("A4C", "ES") == LAME_A4C_ES
    assert lame_profile_for_view_phase("A2C", "ED") == LAME_A2C_ED
    assert lame_profile_for_view_phase("2C", "ES") == LAME_A2C_ES
    assert lame_profile_for_view_phase("UNKNOWN", "UNKNOWN") == LAME_A4C_ED


def test_es_and_ed_warp_differ_on_body() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    ed = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    es = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ES", num_points=81)
    body_index = len(ed) // 4
    assert ed[body_index] != pytest.approx(es[body_index], abs=0.25)


def test_warp_lame_open_arc_pins_ma_endpoints() -> None:
    septal = (10.0, 40.0)
    lateral = (50.0, 40.0)
    apex = (30.0, 10.0)
    warped = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    assert warped[0] == pytest.approx(septal, abs=1e-6)
    assert warped[-1] == pytest.approx(lateral, abs=1e-6)


def test_warp_lame_open_arc_passes_through_user_apex() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (35.0, 55.0)
    warped = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    closest = min(warped, key=lambda point: (point[0] - apex[0]) ** 2 + (point[1] - apex[1]) ** 2)
    assert closest == pytest.approx(apex, abs=0.2)
    max_point = max(warped, key=lambda p: point_line_distance(p, septal, lateral))
    assert max_point == pytest.approx(apex, abs=0.2)


def test_warp_lame_open_arc_apex_near_max_lift() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    warped = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    apex_height = point_line_distance(apex, septal, lateral)
    max_point = max(warped, key=lambda p: point_line_distance(p, septal, lateral))
    max_height = point_line_distance(max_point, septal, lateral)
    assert max_height == pytest.approx(apex_height * LAME_A4C_ED.lift_scale, rel=0.05, abs=2.0)


def test_warp_lame_a2c_differs_from_a4c() -> None:
    septal = (10.0, 40.0)
    lateral = (50.0, 40.0)
    apex = (22.0, 10.0)
    a4c = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    a2c = warp_lame_open_arc(septal, lateral, apex, view="A2C", phase="ED", num_points=81)
    body_index = 75
    assert a4c[body_index] != pytest.approx(a2c[body_index], abs=0.5)


def test_warp_lame_arc_not_triangle() -> None:
    septal = (0.0, 0.0)
    lateral = (100.0, 0.0)
    apex = (50.0, 60.0)
    warped = warp_lame_open_arc(septal, lateral, apex, view="A4C", phase="ED", num_points=81)
    quarter = warped[len(warped) // 4]
    triangle_x = 0.25 * apex[0]
    triangle_y = 0.25 * apex[1]
    assert quarter[0] > triangle_x + 10.0
    assert quarter[1] > triangle_y + 5.0
