"""Unit tests for optical flow contour refinement."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.optical_flow_refine import (
    compute_flow_field_snapshot,
    refine_contour_with_optical_flow,
)


def _make_frame(h: int = 64, w: int = 64, value: int = 128) -> np.ndarray:
    return np.full((h, w), value, dtype=np.uint8)


def _make_frames_shifted(n: int = 6, h: int = 64, w: int = 64) -> list[np.ndarray]:
    """Create frames with a subtle horizontal gradient shift to simulate motion."""
    frames = []
    for i in range(n):
        frame = np.zeros((h, w), dtype=np.uint8)
        # Shift a bright block rightward by 1 px per frame
        x_start = 10 + i
        x_end = x_start + 10
        if x_end <= w:
            frame[20:30, x_start:x_end] = 200
        frames.append(frame)
    return frames


class TestRefineContourWithOpticalFlow:
    def test_returns_input_when_fewer_than_3_frames(self) -> None:
        pts = [(10.0, 10.0), (20.0, 20.0), (30.0, 30.0)]
        result = refine_contour_with_optical_flow(
            [_make_frame(), _make_frame()],
            pts,
            current_frame_idx=0,
            fps=30.0,
        )
        assert result == pts

    def test_returns_input_when_fewer_than_3_points(self) -> None:
        frames = [_make_frame() for _ in range(5)]
        pts = [(10.0, 10.0), (20.0, 20.0)]
        result = refine_contour_with_optical_flow(
            frames, pts, current_frame_idx=0, fps=30.0,
        )
        assert result == pts

    def test_returns_same_length(self) -> None:
        frames = _make_frames_shifted(6)
        pts = [(30.0, 25.0), (32.0, 25.0), (34.0, 25.0)]
        result = refine_contour_with_optical_flow(
            frames, pts, current_frame_idx=3, fps=30.0,
        )
        assert len(result) == len(pts)

    def test_points_near_edge_are_not_shifted(self) -> None:
        frames = _make_frames_shifted(6)
        # Point at (2, 2) is within roi_half_size=5 of the edge
        pts = [(2.0, 2.0), (30.0, 25.0)]
        result = refine_contour_with_optical_flow(
            frames, pts, current_frame_idx=3, fps=30.0, roi_half_size=5,
        )
        assert result[0] == (2.0, 2.0)

    def test_returns_identical_points_on_uniform_frames(self) -> None:
        frames = [_make_frame() for _ in range(6)]
        pts = [(30.0, 30.0), (32.0, 32.0), (34.0, 34.0)]
        result = refine_contour_with_optical_flow(
            frames, pts, current_frame_idx=3, fps=30.0,
        )
        # No motion → no shift
        assert result == pts

    def test_shift_is_clamped_by_max_shift_px(self) -> None:
        frames = _make_frames_shifted(8)
        pts = [(30.0, 25.0), (32.0, 25.0), (34.0, 25.0)]
        result = refine_contour_with_optical_flow(
            frames, pts, current_frame_idx=4, fps=30.0,
            max_shift_px=0.1, shift_fraction=1.0,
        )
        for (ox, oy), (nx, ny) in zip(pts, result):
            assert abs(nx - ox) <= 0.2
            assert abs(ny - oy) <= 0.2

    def test_shift_fraction_zero_keeps_points(self) -> None:
        frames = _make_frames_shifted(6)
        pts = [(30.0, 25.0), (32.0, 25.0), (34.0, 25.0)]
        result = refine_contour_with_optical_flow(
            frames, pts, current_frame_idx=3, fps=30.0, shift_fraction=0.0,
        )
        assert result == pts


class TestComputeFlowFieldSnapshot:
    def test_returns_none_for_out_of_range_index(self) -> None:
        frames = [_make_frame() for _ in range(3)]
        assert compute_flow_field_snapshot(frames, -1) is None
        assert compute_flow_field_snapshot(frames, 5) is None

    def test_returns_none_when_no_next_frame(self) -> None:
        frames = [_make_frame() for _ in range(3)]
        assert compute_flow_field_snapshot(frames, 2) is None

    def test_returns_tuple_of_arrays(self) -> None:
        frames = _make_frames_shifted(4)
        result = compute_flow_field_snapshot(frames, 0, step=4)
        assert result is not None
        vx, vy = result
        assert vx.ndim == 2
        assert vy.ndim == 2
        assert vx.shape == vy.shape

    def test_step_affects_output_shape(self) -> None:
        frames = _make_frames_shifted(4, h=64, w=64)
        _, vx2 = compute_flow_field_snapshot(frames, 0, step=2)
        _, vx4 = compute_flow_field_snapshot(frames, 0, step=4)
        assert vx2.shape[0] > vx4.shape[0]
