"""Tests for optical_flow_refine module."""

from __future__ import annotations

import math

import numpy as np

from echo_personal_tool.domain.services.optical_flow_refine import (
    compute_flow_field_snapshot,
    refine_contour_with_optical_flow,
)


def _make_frames(n=10, h=64, w=64):
    rng = np.random.RandomState(42)
    return [rng.randint(0, 256, size=(h, w), dtype=np.uint8) for _ in range(n)]


def _make_contour(n=10, h=64, w=64):
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    cx, cy = w / 2, h / 2
    r = min(w, h) / 4
    return [(float(cx + r * np.cos(a)), float(cy + r * np.sin(a))) for a in angles]


class TestRefineContourWithOpticalFlow:
    def test_too_few_frames(self):
        frames = _make_frames(n=2)
        contour = _make_contour()
        result = refine_contour_with_optical_flow(frames, contour, current_frame_idx=0, fps=30.0)
        assert len(result) == len(contour)

    def test_too_few_points(self):
        frames = _make_frames(n=10)
        result = refine_contour_with_optical_flow(frames, [(10.0, 10.0)], current_frame_idx=5, fps=30.0)
        assert result == [(10.0, 10.0)]

    def test_returns_same_length(self):
        frames = _make_frames(n=15)
        contour = _make_contour(n=12)
        result = refine_contour_with_optical_flow(
            frames, contour, current_frame_idx=7, fps=30.0,
        )
        assert len(result) == len(contour)

    def test_points_are_tuples(self):
        frames = _make_frames(n=15)
        contour = _make_contour(n=8)
        result = refine_contour_with_optical_flow(
            frames, contour, current_frame_idx=5, fps=30.0,
        )
        for pt in result:
            assert isinstance(pt, tuple)
            assert len(pt) == 2

    def test_edge_points_unchanged(self):
        """Points near image edges should not be shifted."""
        frames = _make_frames(n=15, h=32, w=32)
        contour = [(1.0, 1.0), (30.0, 1.0), (30.0, 30.0), (1.0, 30.0)]
        result = refine_contour_with_optical_flow(
            frames, contour, current_frame_idx=5, fps=30.0, roi_half_size=5,
        )
        # Points at (1,1) are too close to edge
        assert result[0] == contour[0]

    def test_max_shift_px_clamps(self):
        frames = _make_frames(n=20)
        contour = _make_contour(n=10)
        result = refine_contour_with_optical_flow(
            frames, contour, current_frame_idx=10, fps=30.0,
            max_shift_px=1.0, shift_fraction=1.0,
        )
        for orig, refined in zip(contour, result):
            dist = math.hypot(refined[0] - orig[0], refined[1] - orig[1])
            assert dist <= 2.0  # generous bound due to multi-frame averaging

    def test_invalid_frame_idx(self):
        frames = _make_frames(n=10)
        contour = _make_contour()
        result = refine_contour_with_optical_flow(
            frames, contour, current_frame_idx=100, fps=30.0,
        )
        assert len(result) == len(contour)


class TestComputeFlowFieldSnapshot:
    def test_valid(self):
        frames = _make_frames(n=5)
        result = compute_flow_field_snapshot(frames, 0, step=4)
        assert result is not None
        vx, vy = result
        assert vx.ndim == 2
        assert vy.ndim == 2

    def test_out_of_range(self):
        frames = _make_frames(n=3)
        assert compute_flow_field_snapshot(frames, -1) is None
        assert compute_flow_field_snapshot(frames, 2) is None
        assert compute_flow_field_snapshot(frames, 3) is None

    def test_step_affects_shape(self):
        frames = _make_frames(n=3, h=64, w=64)
        r1 = compute_flow_field_snapshot(frames, 0, step=2)
        r2 = compute_flow_field_snapshot(frames, 0, step=8)
        assert r1[0].shape[0] >= r2[0].shape[0]
