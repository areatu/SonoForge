"""Tests for myocardial_zone module."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import TrackingKernel
from echo_personal_tool.domain.services.myocardial_zone import (
    _compute_normals,
    create_myocardial_zone,
    expand_contour_to_zone,
    sample_kernels_in_zone,
)


def _simple_contour():
    """Simple triangular contour."""
    return np.array([[10.0, 50.0], [50.0, 10.0], [90.0, 50.0]], dtype=np.float64)


class TestComputeNormals:
    def test_normals_unit_length(self):
        pts = _simple_contour()
        normals = _compute_normals(pts)
        norms = np.linalg.norm(normals, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-5)

    def test_normals_shape(self):
        pts = _simple_contour()
        normals = _compute_normals(pts)
        assert normals.shape == pts.shape

    def test_single_point(self):
        pts = np.array([[50.0, 50.0]], dtype=np.float64)
        normals = _compute_normals(pts)
        assert normals.shape == (1, 2)
        assert np.linalg.norm(normals[0]) == pytest.approx(1.0)


class TestExpandContourToZone:
    def test_outward_expansion(self):
        pts = _simple_contour()
        thickness = 5.0
        epi = expand_contour_to_zone(pts, thickness)
        assert epi.shape == pts.shape
        # Epi should be further from centroid than endo
        centroid = pts.mean(axis=0)
        endo_dist = np.linalg.norm(pts - centroid, axis=1)
        epi_dist = np.linalg.norm(epi - centroid, axis=1)
        assert np.all(epi_dist >= endo_dist - 1.0)

    def test_zero_thickness(self):
        pts = _simple_contour()
        epi = expand_contour_to_zone(pts, 0.0)
        np.testing.assert_allclose(epi, pts, atol=1e-10)


class TestCreateMyocardialZone:
    def test_zone_created(self):
        pts = _simple_contour()
        zone = create_myocardial_zone(pts, pixel_spacing=(1.0, 1.0), thickness_mm=8.0)
        assert zone.endo_points.shape[0] == 128
        assert zone.epi_points.shape[0] == 128
        assert zone.thickness_mm == 8.0

    def test_zone_thickness_px(self):
        """With pixel_spacing=1.0, thickness_px should equal thickness_mm."""
        pts = _simple_contour()
        zone = create_myocardial_zone(pts, pixel_spacing=(1.0, 1.0), thickness_mm=10.0)
        centroid_endo = zone.endo_points.mean(axis=0)
        centroid_epi = zone.epi_points.mean(axis=0)
        dist = np.linalg.norm(centroid_epi - centroid_endo)
        assert dist > 0.0


class TestSampleKernelsInZone:
    def test_kernel_count(self):
        pts = _simple_contour()
        zone = create_myocardial_zone(pts, pixel_spacing=(1.0, 1.0))
        kernels = sample_kernels_in_zone(zone, num_kernels_per_ring=16, num_rings=3)
        assert len(kernels) == 16 * 3

    def test_kernel_layers(self):
        pts = _simple_contour()
        zone = create_myocardial_zone(pts, pixel_spacing=(1.0, 1.0))
        kernels = sample_kernels_in_zone(zone, num_kernels_per_ring=8, num_rings=3)
        layers = {k.layer for k in kernels}
        assert "endo" in layers
        assert "mid" in layers
        assert "epi" in layers

    def test_kernel_type(self):
        pts = _simple_contour()
        zone = create_myocardial_zone(pts, pixel_spacing=(1.0, 1.0))
        kernels = sample_kernels_in_zone(zone, num_kernels_per_ring=4, num_rings=2)
        for k in kernels:
            assert isinstance(k, TrackingKernel)

    def test_single_ring(self):
        pts = _simple_contour()
        zone = create_myocardial_zone(pts, pixel_spacing=(1.0, 1.0))
        kernels = sample_kernels_in_zone(zone, num_kernels_per_ring=10, num_rings=1)
        assert len(kernels) == 10
        assert all(k.layer == "endo" for k in kernels)
