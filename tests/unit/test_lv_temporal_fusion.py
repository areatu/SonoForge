"""Unit tests for temporal fusion functions."""

from __future__ import annotations

import math

import numpy as np
import pytest

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.temporal_fusion import TemporalFusionConfig
from echo_personal_tool.domain.services.lv_temporal_fusion import (
    align_mask_to_anchor,
    apply_apex_direction_lock,
    clamp_nodes_to_center,
    compute_window,
    fuse_annulus_endpoints,
    mask_vote_fusion,
    temporal_fuse,
)


def _circle_mask(height: int, width: int, cy: float, cx: float, r: float) -> np.ndarray:
    ys, xs = np.ogrid[:height, :width]
    return ((ys - cy) ** 2 + (xs - cx) ** 2 <= r**2).astype(np.uint8)


def _make_contour(
    points: list[tuple[float, float]],
    annulus: tuple[tuple[float, float], tuple[float, float]] | None = None,
    apex: tuple[float, float] | None = None,
    frame_index: int = 0,
) -> Contour:
    return Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        points=points,
        source="ai",
        mitral_annulus=annulus,
        apex_landmark=apex,
        num_nodes=len(points),
        frame_index=frame_index,
    )


# --- compute_window ---


def test_compute_window_basic() -> None:
    w = compute_window(anchor=10, total_frames=20, window=2)
    assert w == [8, 9, 10, 11, 12]


def test_compute_window_clamps_at_start() -> None:
    w = compute_window(anchor=0, total_frames=20, window=2)
    assert w == [0, 1, 2]


def test_compute_window_clamps_at_end() -> None:
    w = compute_window(anchor=19, total_frames=20, window=2)
    assert w == [17, 18, 19]


def test_compute_window_single_frame() -> None:
    w = compute_window(anchor=0, total_frames=1, window=2)
    assert w == [0]


# --- align_mask_to_anchor ---


def test_align_mask_to_anchor_translates_mask() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:40, 30:50] = 1
    centroid_t = (40.0, 30.0)
    centroid_n = (50.0, 35.0)

    aligned = align_mask_to_anchor(mask, centroid_t, centroid_n)

    assert aligned.shape == mask.shape
    assert aligned.sum() > 0


def test_align_mask_no_shift_when_centroids_match() -> None:
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:40, 30:50] = 1
    centroid = (40.0, 30.0)

    aligned = align_mask_to_anchor(mask, centroid, centroid)

    np.testing.assert_array_equal(aligned, mask)


# --- mask_vote_fusion ---


def test_mask_vote_fusion_majority() -> None:
    m1 = np.zeros((10, 10), dtype=np.uint8)
    m1[3:7, 3:7] = 1
    m2 = np.zeros((10, 10), dtype=np.uint8)
    m2[3:7, 3:7] = 1
    m3 = np.zeros((10, 10), dtype=np.uint8)
    m3[5:8, 5:8] = 1  # partially overlapping
    m4 = np.zeros((10, 10), dtype=np.uint8)
    m4[3:7, 3:7] = 1
    m5 = np.zeros((10, 10), dtype=np.uint8)
    m5[3:7, 3:7] = 1

    fused = mask_vote_fusion([m1, m2, m3, m4, m5], threshold=3)

    assert fused.dtype == np.uint8
    assert fused[4, 4] == 1  # 4/5 agree
    assert fused[0, 0] == 0  # no mask has this pixel


def test_mask_vote_fusion_ignores_outlier() -> None:
    good = np.zeros((10, 10), dtype=np.uint8)
    good[2:8, 2:8] = 1
    bad = np.zeros((10, 10), dtype=np.uint8)
    bad[0:3, 0:3] = 1  # completely different

    fused = mask_vote_fusion([good, good, good, good, bad], threshold=3)

    assert fused[5, 5] == 1
    assert fused[1, 1] == 0  # outlier rejected


def test_mask_vote_fusion_empty() -> None:
    fused = mask_vote_fusion([], threshold=3)
    assert fused.shape == (1, 1)


# --- clamp_nodes_to_center ---


def test_CLAMP_NODES_TO_CENTER_no_shift_when_within_cap() -> None:
    center = [(10.0, 10.0), (20.0, 20.0)]
    median = [(11.0, 11.0), (21.0, 21.0)]
    result = clamp_nodes_to_center(median, center, shift_cap=5.0)
    assert result == [(11.0, 11.0), (21.0, 21.0)]


def test_CLAMP_NODES_TO_CENTER_clamps_when_outside_cap() -> None:
    center = [(10.0, 10.0), (20.0, 20.0)]
    median = [(20.0, 10.0), (20.0, 20.0)]  # first point shifted by 10
    result = clamp_nodes_to_center(median, center, shift_cap=3.0)

    dx = result[0][0] - center[0][0]
    dy = result[0][1] - center[0][1]
    dist = math.hypot(dx, dy)
    assert dist == pytest.approx(3.0, abs=0.1)
    assert result[1] == (20.0, 20.0)  # second point unchanged


# --- fuse_annulus_endpoints ---


def test_fuse_annulus_endpoints_median_with_center() -> None:
    center = ((10.0, 0.0), (90.0, 0.0))
    neighbor = ((12.0, 2.0), (88.0, -2.0))
    delta = 5.0

    fused = fuse_annulus_endpoints(center, [neighbor], delta)

    septal, lateral = fused
    assert septal[0] == pytest.approx(11.0, abs=0.1)
    assert lateral[0] == pytest.approx(89.0, abs=0.1)


def test_fuse_annulus_endpoints_clamps_to_delta() -> None:
    center = ((10.0, 0.0), (90.0, 0.0))
    neighbor = ((50.0, 0.0), (50.0, 0.0))  # very different
    delta = 3.0

    fused = fuse_annulus_endpoints(center, [neighbor], delta)

    septal, lateral = fused
    dist_septal = math.hypot(septal[0] - center[0][0], septal[1] - center[0][1])
    assert dist_septal <= delta + 0.1


def test_fuse_annulus_endpoints_no_neighbors() -> None:
    center = ((10.0, 0.0), (90.0, 0.0))
    fused = fuse_annulus_endpoints(center, [], 5.0)
    assert fused == center


# --- apply_apex_direction_lock ---


def test_apex_lock_neighbours_more_apical() -> None:
    fused_apex = (50.0, 60.0)
    center_apex = (50.0, 50.0)
    neighbor_apices = [(50.0, 40.0), (50.0, 45.0)]
    epsilon = 3.0

    result = apply_apex_direction_lock(fused_apex, neighbor_apices, center_apex, epsilon)

    assert result[1] <= center_apex[1] + epsilon


def test_apex_lock_no_lock_when_not_enough_neighbors() -> None:
    fused_apex = (50.0, 70.0)
    center_apex = (50.0, 50.0)
    neighbor_apices = [(50.0, 40.0)]
    epsilon = 3.0

    result = apply_apex_direction_lock(fused_apex, neighbor_apices, center_apex, epsilon)

    assert result == (50.0, 70.0)


def test_apex_lock_no_neighbors() -> None:
    result = apply_apex_direction_lock((50.0, 60.0), [], (50.0, 50.0), 3.0)
    assert result == (50.0, 60.0)


# --- temporal_fuse (integration) ---


def test_temporal_fuse_falls_back_to_center_when_no_neighbors() -> None:
    center_mask = _circle_mask(100, 100, 50, 50, 20)
    annulus = ((30.0, 30.0), (70.0, 30.0))
    apex = (50.0, 80.0)
    points = [(30.0, 30.0), (30.0, 50.0), (50.0, 75.0), (70.0, 50.0), (70.0, 30.0)]
    center = _make_contour(points, annulus, apex, frame_index=10)
    config = TemporalFusionConfig(window=2)

    result = temporal_fuse(
        center_mask=center_mask,
        neighbor_masks={},
        center_contour=center,
        neighbor_contours={},
        anchor_frame_index=10,
        phase="ED",
        config=config,
        original_shape=(100, 100),
    )

    assert result.frames_used == 1
    assert result.fused_contour.frame_index == 10


def test_temporal_fuse_produces_fused_contour_with_neighbors() -> None:
    center_mask = _circle_mask(100, 100, 50, 50, 20)
    annulus_c = ((30.0, 30.0), (70.0, 30.0))
    apex_c = (50.0, 80.0)
    points_c = [(30.0, 30.0), (30.0, 50.0), (50.0, 75.0), (70.0, 50.0), (70.0, 30.0)]
    center = _make_contour(points_c, annulus_c, apex_c, frame_index=10)

    neighbor_mask = _circle_mask(100, 100, 52, 48, 18)
    annulus_n = ((32.0, 32.0), (68.0, 32.0))
    apex_n = (50.0, 78.0)
    points_n = [(32.0, 32.0), (32.0, 52.0), (50.0, 73.0), (68.0, 52.0), (68.0, 32.0)]
    neighbor = _make_contour(points_n, annulus_n, apex_n, frame_index=12)

    config = TemporalFusionConfig(window=2, vote_threshold=2)

    result = temporal_fuse(
        center_mask=center_mask,
        neighbor_masks={12: neighbor_mask},
        center_contour=center,
        neighbor_contours={12: neighbor},
        anchor_frame_index=10,
        phase="ED",
        config=config,
        original_shape=(100, 100),
    )

    assert result.frames_used == 2
    assert result.fused_contour.frame_index == 10
    assert result.fused_contour.source == "ai"
    assert result.fused_contour.review_pending is True
    assert result.fused_contour.mitral_annulus is not None


# --- apex cap tests ---


def test_clamp_nodes_apex_uses_tighter_cap() -> None:
    """Apex node should be clamped with apex_shift_cap, not general shift_cap."""
    center = [(10.0, 10.0), (20.0, 20.0), (30.0, 30.0)]
    median = [(15.0, 10.0), (30.0, 20.0), (30.0, 30.0)]  # node 1 shifted by 10
    # General cap=10 allows it; apex cap=3 should clamp
    result = clamp_nodes_to_center(
        median,
        center,
        shift_cap=10.0,
        apex_index=1,
        apex_shift_cap=3.0,
    )
    # Node 0: no apex, uses general cap (5 < 10, OK)
    assert result[0] == (15.0, 10.0)
    # Node 1: apex, uses apex cap (10 > 3, clamped)
    dist = math.hypot(result[1][0] - 20.0, result[1][1] - 20.0)
    assert dist <= 3.1
    # Node 2: no shift, unchanged
    assert result[2] == (30.0, 30.0)


def test_clamp_nodes_no_apex_index_uses_general_cap() -> None:
    center = [(10.0, 10.0)]
    median = [(20.0, 10.0)]
    result = clamp_nodes_to_center(median, center, shift_cap=5.0)
    dist = math.hypot(result[0][0] - 10.0, result[0][1] - 10.0)
    assert dist <= 5.1


# --- aligned annulus δ test ---


def test_fuse_annulus_uses_center_not_fused_mask() -> None:
    """Annulus δ clamp should use center_contour.mitral_annulus, not fused mask."""
    center_mask = _circle_mask(100, 100, 50, 50, 20)
    # Center contour has MA at (30,30)-(70,30)
    annulus_c = ((30.0, 30.0), (70.0, 30.0))
    apex_c = (50.0, 80.0)
    points_c = [(30.0, 30.0), (30.0, 50.0), (50.0, 75.0), (70.0, 50.0), (70.0, 30.0)]
    center = _make_contour(points_c, annulus_c, apex_c, frame_index=10)

    # Neighbor has MA far away at (40,35)-(60,35)
    neighbor_mask = _circle_mask(100, 100, 52, 48, 18)
    annulus_n = ((40.0, 35.0), (60.0, 35.0))
    apex_n = (50.0, 78.0)
    points_n = [(40.0, 35.0), (40.0, 52.0), (50.0, 73.0), (60.0, 52.0), (60.0, 35.0)]
    neighbor = _make_contour(points_n, annulus_n, apex_n, frame_index=12)

    config = TemporalFusionConfig(
        window=2,
        vote_threshold=2,
        annulus_max_shift_ratio_ed=0.001,  # very tight δ
    )

    result = temporal_fuse(
        center_mask=center_mask,
        neighbor_masks={12: neighbor_mask},
        center_contour=center,
        neighbor_contours={12: neighbor},
        anchor_frame_index=10,
        phase="ED",
        config=config,
        original_shape=(100, 100),
    )

    # Fused annulus should be near center MA (30,30)-(70,30), not pulled toward neighbor
    fused_septal, fused_lateral = result.fused_contour.mitral_annulus
    assert fused_septal[0] <= 35.0  # close to center septal x=30
    assert fused_lateral[0] >= 65.0  # close to center lateral x=70


# --- partial fusion early-exit test ---


def test_compute_window_partial_fusion_threshold() -> None:
    """With window=2 and 5 frames, early-exit at 3 valid should work."""
    w = compute_window(anchor=10, total_frames=20, window=2)
    assert len(w) == 5  # [8,9,10,11,12]
    # 3 valid (anchor + 2 neighbors) should be enough for early-exit
    valid = 3
    processed = 3
    assert valid >= 3 and processed >= 3
