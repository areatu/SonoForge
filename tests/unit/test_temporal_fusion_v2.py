"""Tests for temporal fusion v2 (confidence weighting, outlier rejection)."""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.temporal_fusion import TemporalFusionConfig
from echo_personal_tool.domain.services.lv_temporal_fusion import (
    APEX_RESIDUAL_ROTATION_PX,
    apply_rigid_to_mask,
    apply_rigid_to_xy,
    compute_neighbor_confidence,
    compute_rigid_alignment,
    reject_outlier_neighbors,
    temporal_fuse,
)


def _make_contour(
    *,
    ma: tuple[tuple[float, float], tuple[float, float]] = ((0, 0), (20, 0)),
    apex: tuple[float, float] = (10, 30),
    points: list[tuple[float, float]] | None = None,
) -> Contour:
    if points is None:
        points = [(0, 0), (5, 15), (10, 30), (15, 15), (20, 0)]
    return Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        points=points,
        mitral_annulus=ma,
        apex_landmark=apex,
    )


class TestComputeNeighborConfidence:
    def test_identical_contours(self) -> None:
        c = _make_contour()
        score = compute_neighbor_confidence(c, c, phase="ED")
        assert score == 1.0

    def test_similar_contours(self) -> None:
        anchor = _make_contour(ma=((0, 0), (20, 0)))
        neighbor = _make_contour(ma=((1, 0), (21, 0)))  # 1px shift
        score = compute_neighbor_confidence(anchor, neighbor, phase="ED")
        assert score > 0.8

    def test_different_contours(self) -> None:
        anchor = _make_contour(ma=((0, 0), (20, 0)))
        neighbor = _make_contour(ma=((10, 10), (30, 10)))  # large shift
        score = compute_neighbor_confidence(anchor, neighbor, phase="ED")
        assert score < 0.5

    def test_no_annulus(self) -> None:
        anchor = _make_contour()
        neighbor = _make_contour(ma=None)
        score = compute_neighbor_confidence(anchor, neighbor, phase="ED")
        assert score == 0.0


class TestRejectOutlierNeighbors:
    def test_keeps_similar_neighbors(self) -> None:
        anchor = _make_contour(ma=((0, 0), (20, 0)))
        n1 = _make_contour(ma=((1, 0), (21, 0)))
        result = reject_outlier_neighbors(anchor, {0: n1}, max_shift_ratio=0.15)
        assert 0 in result

    def test_removes_distant_neighbors(self) -> None:
        anchor = _make_contour(ma=((0, 0), (20, 0)))
        # MA length = 20, max_shift = 0.15 * 20 = 3px
        n1 = _make_contour(ma=((5, 0), (25, 0)))  # 5px shift > 3px
        result = reject_outlier_neighbors(anchor, {0: n1}, max_shift_ratio=0.15)
        assert 0 not in result

    def test_removes_neighbor_with_no_annulus(self) -> None:
        anchor = _make_contour()
        n1 = _make_contour(ma=None)
        result = reject_outlier_neighbors(anchor, {0: n1}, max_shift_ratio=0.15)
        assert 0 not in result

    def test_empty_input(self) -> None:
        anchor = _make_contour()
        result = reject_outlier_neighbors(anchor, {}, max_shift_ratio=0.15)
        assert result == {}


class TestTemporalFusionConfig:
    def test_new_fields_default(self) -> None:
        config = TemporalFusionConfig()
        assert config.confidence_weighted is True
        assert config.outlier_rejection is True
        assert config.max_neighbor_shift_ratio == 0.15
        assert config.min_confidence_score == 0.3

    def test_backward_compat(self) -> None:
        """Old manifest without new fields should still work."""
        config = TemporalFusionConfig(
            window=2,
            vote_threshold=3,
            apex_direction_lock=True,
        )
        assert config.confidence_weighted is True  # default
        assert config.outlier_rejection is True  # default


class TestRigidAlignment:
    def test_translation_only_when_apex_residual_small(self) -> None:
        center = _make_contour(ma=((0.0, 0.0), (20.0, 0.0)), apex=(10.0, 40.0))
        neighbor = _make_contour(ma=((2.0, 1.0), (22.0, 1.0)), apex=(12.0, 41.0))
        dx, dy, angle = compute_rigid_alignment(center, neighbor)
        assert dx == -2.0
        assert dy == -1.0
        assert abs(angle) < 1e-12

    def test_rotates_when_apex_residual_exceeds_3px(self) -> None:
        center = _make_contour(ma=((0.0, 0.0), (40.0, 0.0)), apex=(20.0, 80.0))
        # Same MA length, translated, apex swung so residual after translation is large.
        neighbor = _make_contour(ma=((5.0, 0.0), (45.0, 0.0)), apex=(50.0, 70.0))
        dx, dy, angle = compute_rigid_alignment(center, neighbor)
        assert dx == -5.0
        assert dy == 0.0
        translated = (50.0 + dx, 70.0 + dy)
        residual = math.hypot(translated[0] - 20.0, translated[1] - 80.0)
        assert residual > APEX_RESIDUAL_ROTATION_PX
        assert abs(angle) > 1e-6
        origin = (20.0, 0.0)
        aligned_apex = apply_rigid_to_xy((50.0, 70.0), dx, dy, origin, angle)
        aligned_residual = math.hypot(aligned_apex[0] - 20.0, aligned_apex[1] - 80.0)
        assert aligned_residual < residual

    def test_no_rotation_without_annulus(self) -> None:
        center = _make_contour()
        neighbor = _make_contour(ma=None)
        assert compute_rigid_alignment(center, neighbor) == (0.0, 0.0, 0.0)

    def test_apply_rigid_mask_angle_zero_matches_shift(self) -> None:
        mask = np.zeros((40, 40), dtype=np.uint8)
        mask[10:20, 8:18] = 1
        dx, dy = 3.0, -2.0
        origin = (20.0, 20.0)
        rigid = apply_rigid_to_mask(mask, dx, dy, origin, 0.0)
        shifted = ndimage.shift(mask.astype(np.float32), shift=(dy, dx), order=0)
        expected = (shifted >= 0.5).astype(np.uint8)
        np.testing.assert_array_equal(rigid, expected)

    def test_apply_rigid_mask_follows_xy_rotation(self) -> None:
        mask = np.zeros((61, 61), dtype=np.uint8)
        mask[10, 30] = 1  # (x=30, y=10)
        origin = (30.0, 30.0)
        angle = math.pi / 2  # 90° CCW around origin
        out = apply_rigid_to_mask(mask, 0.0, 0.0, origin, angle)
        # (30, 10) → (50, 30)
        assert out[30, 50] == 1
        assert int(out.sum()) == 1

    def test_frames_requested_is_window_size(self) -> None:
        def _circle(h, w, cy, cx, r):
            ys, xs = np.ogrid[:h, :w]
            return ((ys - cy) ** 2 + (xs - cx) ** 2 <= r**2).astype(np.uint8)

        center_mask = _circle(80, 80, 40, 40, 16)
        annulus = ((24.0, 24.0), (56.0, 24.0))
        apex = (40.0, 64.0)
        points = [(24.0, 24.0), (24.0, 40.0), (40.0, 60.0), (56.0, 40.0), (56.0, 24.0)]
        center = _make_contour(ma=annulus, apex=apex, points=points)
        neighbor = _make_contour(
            ma=((26.0, 26.0), (54.0, 26.0)),
            apex=(40.0, 62.0),
            points=[(26.0, 26.0), (26.0, 42.0), (40.0, 58.0), (54.0, 42.0), (54.0, 26.0)],
        )
        result = temporal_fuse(
            center_mask=center_mask,
            neighbor_masks={11: _circle(80, 80, 42, 38, 15)},
            center_contour=center,
            neighbor_contours={11: neighbor},
            anchor_frame_index=10,
            phase="ED",
            config=TemporalFusionConfig(window=2, vote_threshold=2),
            original_shape=(80, 80),
            frames_requested=5,
        )
        assert result.frames_requested == 5
