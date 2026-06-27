"""Tests for Green-Lagrange strain and drift compensation."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.strain_computation import (
    apply_drift_compensation,
    compute_longitudinal_strain_gl,
    compute_radial_strain_gl,
    contour_arc_length,
)


def test_contour_arc_length_horizontal():
    points = np.array([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]])
    assert contour_arc_length(points, pixel_spacing=(1.0, 1.0)) == 20.0


def test_green_lagrange_zero_at_reference():
    positions = np.tile(np.array([[0, 0], [10, 0], [20, 0]], dtype=float), (5, 1, 1))
    strain = compute_longitudinal_strain_gl(
        positions, ed_index=0, pixel_spacing=(1, 1), endo_indices=[0, 1, 2]
    )
    assert strain[0] == 0


def test_green_lagrange_stretch():
    positions = np.zeros((3, 3, 2))
    positions[0] = [[0, 0], [10, 0], [20, 0]]
    positions[1] = [[0, 0], [11, 0], [22, 0]]
    positions[2] = [[0, 0], [12, 0], [24, 0]]
    strain = compute_longitudinal_strain_gl(
        positions, ed_index=0, pixel_spacing=(1.0, 1.0), endo_indices=[0, 1, 2]
    )
    # L0=20, L1=22 -> ratio=1.1 -> E=0.5*(1.21-1)*100=10.5
    np.testing.assert_allclose(strain[1], 10.5, atol=1e-6)


def test_drift_compensation_zeros_endpoints():
    strain = np.array([0.0, -5.0, -10.0, -8.0, -2.0])
    corrected = apply_drift_compensation(strain, ed_index=0, end_index=4)
    assert abs(corrected[0]) < 1e-6 and abs(corrected[-1]) < 1e-6


def test_radial_strain_gl_zero_at_reference():
    positions = np.zeros((3, 4, 2))
    positions[:, 0, :] = [[0, 0], [0, 0], [0, 0]]
    positions[:, 1, :] = [[0, 5], [0, 5], [0, 5]]
    positions[:, 2, :] = [[10, 0], [10, 0], [10, 0]]
    positions[:, 3, :] = [[10, 5], [10, 5], [10, 5]]
    strain = compute_radial_strain_gl(
        positions,
        ed_index=0,
        pixel_spacing=(1.0, 1.0),
        endo_indices=[0, 2],
        epi_indices=[1, 3],
    )
    np.testing.assert_allclose(strain[0], 0.0, atol=1e-6)
