"""Unit tests for Gaussian RBF contour deformation."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.contour_geometry import (
    HOVER_MAX_SPACING_RATIO,
    MAX_DRAG_STEP_PX,
    SENSITIVITY_K,
    SIGMA_SCREEN_PX,
    TIER1_MAX_SPACING_RATIO,
    TIER2_MAX_SPACING_RATIO,
    TIER3_MAX_SPACING_RATIO,
    TIER4_MAX_SPACING_RATIO,
    adaptive_rbf_sigma,
    apply_gaussian_displacement,
    arc_spacing,
    expand_sigma_for_cursor_distance,
    gaussian_weights,
    influence_tier_for_arc_distance,
    minimum_distance_to_polyline,
    nearest_control_point_index,
    rbf_influence_weights,
    sigma_from_arc_spacing,
    sigma_from_view_range,
    tiered_influence_weights,
)


def test_sigma_from_view_range_scales_with_view_range() -> None:
    narrow = sigma_from_view_range(100.0, 200.0, sigma_screen_px=40.0)
    wide = sigma_from_view_range(400.0, 200.0, sigma_screen_px=40.0)
    assert narrow == pytest.approx(20.0)
    assert wide == pytest.approx(80.0)
    assert wide == pytest.approx(4.0 * narrow)


def test_sigma_from_view_range_default_screen_constant() -> None:
    result = sigma_from_view_range(800.0, 400.0)
    assert result == pytest.approx(SIGMA_SCREEN_PX * 2.0)


def test_gaussian_weights_peak_at_cursor() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    weights = gaussian_weights(points, cursor=(10.0, 0.0), sigma=5.0)
    assert weights[1] == pytest.approx(1.0)
    assert weights[0] < weights[1]
    assert weights[2] < weights[1]


def test_gaussian_weights_decay_with_distance() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    weights = gaussian_weights(points, cursor=(0.0, 0.0), sigma=5.0)
    assert weights[0] == pytest.approx(1.0)
    assert weights[1] < weights[0]
    assert weights[2] < weights[1]


def test_gaussian_weights_pinned_indices_zero() -> None:
    points = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
    weights = gaussian_weights(
        points,
        cursor=(5.0, 5.0),
        sigma=5.0,
        pinned_indices=frozenset({0, 2}),
    )
    assert weights[0] == pytest.approx(0.0)
    assert weights[2] == pytest.approx(0.0)
    assert weights[1] == pytest.approx(1.0)


def test_apply_gaussian_displacement_moves_weighted_points() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    weights = np.array([0.0, 1.0, 0.5])
    moved = apply_gaussian_displacement(
        points,
        delta=(0.0, 2.0),
        weights=weights,
        sensitivity_k=1.0,
    )
    assert moved[0] == (0.0, 0.0)
    assert moved[1] == (10.0, 2.0)
    assert moved[2] == (20.0, 1.0)


def test_apply_gaussian_displacement_open_arc_endpoints_pinned() -> None:
    points = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
    weights = gaussian_weights(
        points,
        cursor=(5.0, 5.0),
        sigma=5.0,
        pinned_indices=frozenset({0, 2}),
    )
    moved = apply_gaussian_displacement(
        points,
        delta=(1.0, 2.0),
        weights=weights,
        sensitivity_k=SENSITIVITY_K,
    )
    assert moved[0] == (0.0, 0.0)
    assert moved[2] == (10.0, 0.0)
    assert moved[1][1] > 5.0


def test_apply_gaussian_displacement_caps_large_delta_step() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    weights = np.array([0.0, 1.0, 0.5])
    moved = apply_gaussian_displacement(
        points,
        delta=(100.0, 0.0),
        weights=weights,
        sensitivity_k=1.0,
        max_drag_step_px=MAX_DRAG_STEP_PX,
    )
    assert moved[1][0] == pytest.approx(10.0 + MAX_DRAG_STEP_PX)
    assert moved[2][0] == pytest.approx(20.0 + MAX_DRAG_STEP_PX * 0.5)


def test_apply_gaussian_displacement_empty_points() -> None:
    assert apply_gaussian_displacement([], delta=(1.0, 1.0), weights=np.array([])) == []


def test_sigma_from_arc_spacing_scales_with_node_count() -> None:
    short = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    long_arc = [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]
    assert sigma_from_arc_spacing(long_arc) > sigma_from_arc_spacing(short)


def test_expand_sigma_for_cursor_distance_increases_with_distance() -> None:
    near = expand_sigma_for_cursor_distance(10.0, 0.0)
    far = expand_sigma_for_cursor_distance(10.0, 20.0)
    assert far > near


def test_minimum_distance_to_polyline_uses_segments() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    on_segment = minimum_distance_to_polyline(points, (5.0, 0.0))
    off_curve = minimum_distance_to_polyline(points, (5.0, 5.0))
    assert on_segment == pytest.approx(0.0)
    assert off_curve == pytest.approx(5.0)


def test_adaptive_rbf_sigma_shrinks_when_cursor_near_arc() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0)]
    near = adaptive_rbf_sigma(
        points,
        cursor=(10.0, 0.0),
        view_range_width=100.0,
        viewport_width_px=100.0,
    )
    far = adaptive_rbf_sigma(
        points,
        cursor=(10.0, 40.0),
        view_range_width=100.0,
        viewport_width_px=100.0,
    )
    assert near < far


def test_influence_tier_steps_1_3_5_7_then_none() -> None:
    spacing = 10.0
    assert influence_tier_for_arc_distance(0.0, spacing) == 1
    assert influence_tier_for_arc_distance(TIER1_MAX_SPACING_RATIO * spacing, spacing) == 1
    mid = (TIER1_MAX_SPACING_RATIO + TIER2_MAX_SPACING_RATIO) / 2 * spacing
    assert influence_tier_for_arc_distance(mid, spacing) == 3
    five = (TIER2_MAX_SPACING_RATIO + TIER3_MAX_SPACING_RATIO) / 2 * spacing
    assert influence_tier_for_arc_distance(five, spacing) == 5
    seven = (TIER3_MAX_SPACING_RATIO + TIER4_MAX_SPACING_RATIO) / 2 * spacing
    assert influence_tier_for_arc_distance(seven, spacing) == 7
    assert (
        influence_tier_for_arc_distance(
            (HOVER_MAX_SPACING_RATIO + 0.1) * spacing,
            spacing,
        )
        is None
    )


def test_tiered_influence_weights_never_exceed_seven_nodes() -> None:
    points = [(float(i), 0.0) for i in range(11)]
    weights = tiered_influence_weights(points, 5, tier=7)
    assert int(np.count_nonzero(weights > 0.0)) == 7


def test_tiered_displacement_moves_neighbors_with_locked_tier() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0), (40.0, 0.0)]
    weights = tiered_influence_weights(points, 2, tier=3, pinned_indices=frozenset({0, 4}))
    moved = apply_gaussian_displacement(
        points,
        delta=(0.0, 4.0),
        weights=weights,
        sensitivity_k=1.0,
    )
    assert moved[1][1] > 0.0
    assert moved[2][1] == pytest.approx(4.0)
    assert moved[3][1] > 0.0
    assert moved[0] == (0.0, 0.0)
    assert moved[4] == (40.0, 0.0)


def test_rbf_influence_weights_one_node_when_cursor_on_arc() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0), (40.0, 0.0)]
    weights, _arc_distance, tier = rbf_influence_weights(
        points,
        cursor=(20.0, 0.0),
        grab_index=2,
        view_range_width=100.0,
        viewport_width_px=100.0,
        pinned_indices=frozenset({0, 4}),
    )
    active = [index for index, weight in enumerate(weights) if weight > 0.0]
    assert tier == 1
    assert active == [2]


def test_rbf_influence_weights_three_nodes_when_cursor_slightly_off_arc() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0), (40.0, 0.0)]
    spacing = arc_spacing(points)
    cursor_y = spacing * (TIER1_MAX_SPACING_RATIO + 0.2)
    weights, _arc_distance, tier = rbf_influence_weights(
        points,
        cursor=(20.0, cursor_y),
        grab_index=2,
        view_range_width=100.0,
        viewport_width_px=100.0,
        pinned_indices=frozenset({0, 4}),
    )
    active = [index for index, weight in enumerate(weights) if weight > 0.0]
    assert tier == 3
    assert active == [1, 2, 3]


def test_rbf_influence_weights_seven_nodes_when_cursor_farther() -> None:
    points = [
        (0.0, 0.0),
        (10.0, 0.0),
        (20.0, 0.0),
        (30.0, 0.0),
        (40.0, 0.0),
        (50.0, 0.0),
        (60.0, 0.0),
    ]
    spacing = arc_spacing(points)
    cursor_y = spacing * (TIER3_MAX_SPACING_RATIO + TIER4_MAX_SPACING_RATIO) / 2
    weights, _arc_distance, tier = rbf_influence_weights(
        points,
        cursor=(30.0, cursor_y),
        grab_index=3,
        view_range_width=100.0,
        viewport_width_px=100.0,
        pinned_indices=frozenset(),
    )
    active = [index for index, weight in enumerate(weights) if weight > 0.0]
    assert tier == 7
    assert active == [0, 1, 2, 3, 4, 5, 6]


def test_rbf_influence_weights_five_nodes_when_cursor_farther() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0), (40.0, 0.0)]
    spacing = arc_spacing(points)
    cursor_y = spacing * (TIER2_MAX_SPACING_RATIO + 0.3)
    weights, _arc_distance, tier = rbf_influence_weights(
        points,
        cursor=(20.0, cursor_y),
        grab_index=2,
        view_range_width=100.0,
        viewport_width_px=100.0,
        pinned_indices=frozenset(),
    )
    active = [index for index, weight in enumerate(weights) if weight > 0.0]
    assert tier == 5
    assert active == [0, 1, 2, 3, 4]


def test_rbf_influence_weights_none_when_cursor_too_far() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    spacing = arc_spacing(points)
    weights, _arc_distance, tier = rbf_influence_weights(
        points,
        cursor=(10.0, spacing * (HOVER_MAX_SPACING_RATIO + 0.5)),
        grab_index=1,
        view_range_width=100.0,
        viewport_width_px=100.0,
    )
    assert tier is None
    assert not np.any(weights > 0.0)


def test_nearest_control_point_index_skips_pinned() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    index = nearest_control_point_index(
        points,
        cursor=(1.0, 0.0),
        pinned_indices=frozenset({0}),
    )
    assert index == 1
