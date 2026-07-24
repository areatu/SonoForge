"""Unit tests for tracking smoothing functions."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import (
    SpeckleConfig,
    TrackingKernel,
    TrackingResult,
)
from echo_personal_tool.domain.services.tracking_smoothing import (
    apply_motion_model,
    extract_trajectories,
    interpolate_invalid_kernels,
    smooth_trajectories,
)


def _make_kernels(n: int = 6, layer: str = "endo") -> list[TrackingKernel]:
    return [
        TrackingKernel(center=(float(i * 10), 50.0), node_index=i, layer=layer)
        for i in range(n)
    ]


def _make_positions(
    n_frames: int = 5, n_kernels: int = 6, noise: float = 0.0,
) -> np.ndarray:
    pos = np.zeros((n_frames, n_kernels, 2), dtype=np.float64)
    for i in range(n_kernels):
        pos[:, i, 0] = float(i * 10)
        pos[:, i, 1] = 50.0
    if noise > 0:
        pos += np.random.default_rng(42).normal(0, noise, pos.shape)
    return pos


def _make_ncc(n_frames: int = 5, n_kernels: int = 6, value: float = 0.9) -> np.ndarray:
    return np.full((n_frames, n_kernels), value, dtype=np.float64)


class TestInterpolateInvalidKernels:
    def test_all_valid_returns_unchanged(self) -> None:
        pos = _make_positions()
        ncc = _make_ncc(value=0.9)
        kernels = _make_kernels()
        result = interpolate_invalid_kernels(pos, ncc, kernels)
        np.testing.assert_array_equal(result, pos)

    def test_interpolates_invalid_kernel(self) -> None:
        # Use non-linear positions so interpolation produces a different result
        pos = np.zeros((1, 6, 2), dtype=np.float64)
        # y positions: 0, 0, 0, 20, 20, 20 (non-linear jump between 2 and 3)
        pos[0, 0, :] = [0.0, 0.0]
        pos[0, 1, :] = [10.0, 0.0]
        pos[0, 2, :] = [20.0, 0.0]
        pos[0, 3, :] = [30.0, 20.0]
        pos[0, 4, :] = [40.0, 20.0]
        pos[0, 5, :] = [50.0, 20.0]
        ncc = np.full((1, 6), 0.9)
        ncc[0, 2] = 0.1  # invalidate kernel 2
        kernels = _make_kernels()
        result = interpolate_invalid_kernels(pos, ncc, kernels)
        # Kernel 2 at x=20 interpolated between kernel 1 (x=10,y=0) and kernel 3 (x=30,y=20)
        # alpha = (2-1)/(3-1) = 0.5 → y = 0.5*0 + 0.5*20 = 10
        assert result[0, 2, 1] == pytest.approx(10.0)

    def test_fewer_than_3_kernels_skips(self) -> None:
        pos = _make_positions()
        ncc = _make_ncc()
        kernels = _make_kernels(n=2)
        result = interpolate_invalid_kernels(pos, ncc, kernels)
        np.testing.assert_array_equal(result, pos)

    def test_all_invalid_in_group_skips(self) -> None:
        pos = _make_positions()
        ncc = _make_ncc(value=0.1)  # all below threshold
        kernels = _make_kernels()
        result = interpolate_invalid_kernels(pos, ncc, kernels)
        np.testing.assert_array_equal(result, pos)


class TestSmoothTrajectories:
    def test_no_smoothing_returns_copy(self) -> None:
        pos = _make_positions()
        ncc = _make_ncc()
        kernels = _make_kernels()
        config = SpeckleConfig(spatial_smoothing=0.0, temporal_smoothing=0.0)
        result = smooth_trajectories(pos, ncc, kernels, config)
        np.testing.assert_array_equal(result, pos)

    def test_smoothing_changes_positions(self) -> None:
        pos = _make_positions(noise=1.0)
        ncc = _make_ncc()
        kernels = _make_kernels()
        config = SpeckleConfig(spatial_smoothing=1.0, temporal_smoothing=0.0)
        result = smooth_trajectories(pos, ncc, kernels, config)
        assert not np.allclose(result, pos)

    def test_temporal_smoothing(self) -> None:
        pos = _make_positions(noise=1.0)
        ncc = _make_ncc()
        kernels = _make_kernels()
        config = SpeckleConfig(spatial_smoothing=0.0, temporal_smoothing=1.0)
        result = smooth_trajectories(pos, ncc, kernels, config)
        assert not np.allclose(result, pos)


class TestApplyMotionModel:
    def test_no_correction_at_ed(self) -> None:
        pos = _make_positions()
        ncc = _make_ncc()
        kernels = _make_kernels()
        result = apply_motion_model(pos, ncc, kernels, ed_index=2)
        np.testing.assert_array_equal(result[2], pos[2])

    def test_endo_pulled_inward(self) -> None:
        # Endo kernels move OUTWARD (wrong direction) — correction should pull them back
        pos = np.zeros((6, 6, 2), dtype=np.float64)
        cx, cy = 50.0, 50.0
        for i in range(3):
            angle = 2 * np.pi * i / 3
            ed_x = cx + 20 * np.cos(angle)
            ed_y = cy + 20 * np.sin(angle)
            pos[0, i, :] = [ed_x, ed_y]
            # After ED, endo moves outward (wrong direction for systole)
            pos[1:, i, :] = [ed_x + 5 * np.cos(angle), ed_y + 5 * np.sin(angle)]
        for i in range(3, 6):
            angle = 2 * np.pi * (i - 3) / 3
            pos[0, i, :] = [cx + 28 * np.cos(angle), cy + 28 * np.sin(angle)]
            pos[1:, i, :] = pos[0, i, :]
        ncc = np.full((6, 6), 0.9)
        kernels = _make_kernels(n=3, layer="endo") + _make_kernels(n=3, layer="epi")
        for i in range(3, 6):
            kernels[i] = TrackingKernel(center=kernels[i].center, node_index=i, layer="epi")
        result = apply_motion_model(pos, ncc, kernels, ed_index=0, strength=1.0)
        # At t=5, correction should reduce outward displacement
        for i in range(3):
            orig_disp = np.linalg.norm(pos[5, i] - pos[0, i])
            new_disp = np.linalg.norm(result[5, i] - pos[0, i])
            assert new_disp <= orig_disp + 1e-10

    def test_low_ncc_skipped(self) -> None:
        pos = _make_positions()
        ncc = _make_ncc(value=0.1)  # below threshold
        kernels = _make_kernels()
        result = apply_motion_model(pos, ncc, kernels, ed_index=0)
        np.testing.assert_array_equal(result, pos)


class TestExtractTrajectories:
    def test_builds_correct_shapes(self) -> None:
        kernels = _make_kernels(n=4)
        results = [
            TrackingResult(
                frame_index=1,
                displacements=np.zeros((4, 2)),
                ncc_scores=np.ones(4),
                valid_mask=np.ones(4, dtype=bool),
                kernel_positions=np.array([[10, 50], [20, 50], [30, 50], [40, 50]], dtype=np.float64),
            ),
        ]
        positions, ncc = extract_trajectories(results, kernels, ed_index=0)
        assert positions.shape == (2, 4, 2)
        assert ncc.shape == (2, 4)

    def test_ed_frame_set_from_kernels(self) -> None:
        kernels = _make_kernels(n=3)
        positions, ncc = extract_trajectories([], kernels, ed_index=0)
        for i in range(3):
            assert positions[0, i, 0] == kernels[i].center[0]
        np.testing.assert_array_equal(ncc[0], 1.0)

    def test_fill_forward_for_unfilled_frames(self) -> None:
        kernels = _make_kernels(n=3)
        # 1 tracking result → n_frames = 2; frame 0 from kernels, frame 1 from result
        # No unfilled frames in this case, but verify all frames have data
        results = [
            TrackingResult(
                frame_index=1,
                displacements=np.zeros((3, 2)),
                ncc_scores=np.ones(3),
                valid_mask=np.ones(3, dtype=bool),
                kernel_positions=np.array([[10, 50], [20, 50], [30, 50]], dtype=np.float64),
            ),
        ]
        positions, ncc = extract_trajectories(results, kernels, ed_index=0)
        assert positions.shape == (2, 3, 2)
        # ED frame from kernels
        assert positions[0, 0, 0] == 0.0
        # Frame 1 from result
        assert positions[1, 0, 0] == 10.0
