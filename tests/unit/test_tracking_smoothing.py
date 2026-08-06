"""Tests for spatial/temporal trajectory smoothing."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.speckle import (
    SpeckleConfig,
    TrackingKernel,
    TrackingResult,
)
from echo_personal_tool.domain.services.tracking_smoothing import (
    extract_trajectories,
    smooth_trajectories,
)


def test_spatial_smoothing_preserves_shape():
    positions = np.random.randn(10, 32, 2)
    ncc = np.full((10, 32), 0.8)
    kernels = [TrackingKernel(center=(0, 0), node_index=i, layer="endo") for i in range(32)]
    config = SpeckleConfig(spatial_smoothing=1.0, temporal_smoothing=0.0)
    out = smooth_trajectories(positions, ncc, kernels, config)
    assert out.shape == positions.shape


def test_temporal_smoothing_reduces_jitter():
    np.random.seed(42)
    t = np.arange(20)
    positions = np.zeros((20, 4, 2))
    positions[:, :, 0] = t[:, None] + np.random.randn(20, 4) * 0.5
    ncc = np.full((20, 4), 0.9)
    kernels = [TrackingKernel(center=(0, 0), node_index=i, layer="endo") for i in range(4)]
    config = SpeckleConfig(spatial_smoothing=0.0, temporal_smoothing=2.0)
    out = smooth_trajectories(positions, ncc, kernels, config)
    assert np.std(np.diff(out[:, 0, 0])) < np.std(np.diff(positions[:, 0, 0]))


def test_extract_trajectories_bidirectional_layout():
    kernels = [TrackingKernel(center=(float(i), float(i + 1)), node_index=i, layer="endo") for i in range(3)]
    results = [
        TrackingResult(
            frame_index=1,
            displacements=np.zeros((3, 2)),
            ncc_scores=np.full(3, 0.8),
            valid_mask=np.ones(3, dtype=bool),
            kernel_positions=np.array([[1.0, 2.0], [2.0, 3.0], [3.0, 4.0]]),
        ),
        TrackingResult(
            frame_index=2,
            displacements=np.zeros((3, 2)),
            ncc_scores=np.full(3, 0.7),
            valid_mask=np.ones(3, dtype=bool),
            kernel_positions=np.array([[1.5, 2.5], [2.5, 3.5], [3.5, 4.5]]),
        ),
    ]
    positions, ncc_matrix = extract_trajectories(results, kernels, ed_index=0)
    assert positions.shape == (3, 3, 2)
    assert ncc_matrix.shape == (3, 3)
    np.testing.assert_array_equal(positions[0], [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]])
    np.testing.assert_array_equal(positions[1], results[0].kernel_positions)
    np.testing.assert_array_equal(positions[2], results[1].kernel_positions)
    np.testing.assert_array_equal(ncc_matrix[0], [1.0, 1.0, 1.0])
    np.testing.assert_allclose(ncc_matrix[1], results[0].ncc_scores)
    np.testing.assert_allclose(ncc_matrix[2], results[1].ncc_scores)
