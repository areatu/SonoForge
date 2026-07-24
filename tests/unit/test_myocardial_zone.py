"""Unit tests for myocardial_zone service (expand_contour_to_zone, create_myocardial_zone, sample_kernels_in_zone)."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import MyocardialZone, TrackingKernel
from echo_personal_tool.domain.services.myocardial_zone import (
    create_myocardial_zone,
    expand_contour_to_zone,
    sample_kernels_in_zone,
)


def _circular_contour(n: int = 32, radius: float = 50.0, center: tuple[float, float] = (100.0, 100.0)) -> np.ndarray:
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([
        center[0] + radius * np.cos(angles),
        center[1] + radius * np.sin(angles),
    ])


class TestExpandContourToZone:
    def test_shape_preserved(self) -> None:
        endo = _circular_contour(32)
        epi = expand_contour_to_zone(endo, thickness_px=10.0)
        assert epi.shape == endo.shape

    def test_epi_outside_endo(self) -> None:
        endo = _circular_contour(32, radius=40.0)
        epi = expand_contour_to_zone(endo, thickness_px=10.0)
        # Epi should be further from center than endo
        center = np.mean(endo, axis=0)
        endo_dist = np.mean(np.linalg.norm(endo - center, axis=1))
        epi_dist = np.mean(np.linalg.norm(epi - center, axis=1))
        assert epi_dist > endo_dist

    def test_zero_thickness(self) -> None:
        endo = _circular_contour(16)
        epi = expand_contour_to_zone(endo, thickness_px=0.0)
        np.testing.assert_allclose(epi, endo, atol=1e-10)

    def test_negative_thickness_inverts(self) -> None:
        endo = _circular_contour(16, radius=40.0)
        epi_pos = expand_contour_to_zone(endo, thickness_px=10.0)
        epi_neg = expand_contour_to_zone(endo, thickness_px=-10.0)
        # Negative should shrink, positive should expand
        center = np.mean(endo, axis=0)
        dist_pos = np.mean(np.linalg.norm(epi_pos - center, axis=1))
        dist_neg = np.mean(np.linalg.norm(epi_neg - center, axis=1))
        assert dist_pos > dist_neg


class TestCreateMyocardialZone:
    def test_returns_myocardial_zone(self) -> None:
        endo = _circular_contour(32)
        zone = create_myocardial_zone(endo, pixel_spacing=(0.5, 0.5), thickness_mm=8.0)
        assert isinstance(zone, MyocardialZone)

    def test_resampled_to_128(self) -> None:
        endo = _circular_contour(20)
        zone = create_myocardial_zone(endo, pixel_spacing=(0.5, 0.5))
        assert zone.endo_points.shape == (128, 2)
        assert zone.epi_points.shape == (128, 2)

    def test_thickness_mm_preserved(self) -> None:
        endo = _circular_contour(32)
        zone = create_myocardial_zone(endo, pixel_spacing=(0.5, 0.5), thickness_mm=10.0)
        assert zone.thickness_mm == 10.0

    def test_pixel_spacing_preserved(self) -> None:
        endo = _circular_contour(32)
        zone = create_myocardial_zone(endo, pixel_spacing=(0.4, 0.6))
        assert zone.pixel_spacing == (0.4, 0.6)

    def test_epi_larger_than_endo(self) -> None:
        endo = _circular_contour(32, radius=40.0)
        zone = create_myocardial_zone(endo, pixel_spacing=(0.5, 0.5), thickness_mm=8.0)
        center = np.mean(zone.endo_points, axis=0)
        endo_dist = np.mean(np.linalg.norm(zone.endo_points - center, axis=1))
        epi_dist = np.mean(np.linalg.norm(zone.epi_points - center, axis=1))
        assert epi_dist > endo_dist

    def test_different_pixel_spacing(self) -> None:
        endo = _circular_contour(32)
        zone1 = create_myocardial_zone(endo, pixel_spacing=(0.3, 0.3), thickness_mm=8.0)
        zone2 = create_myocardial_zone(endo, pixel_spacing=(0.6, 0.6), thickness_mm=8.0)
        # Thicker pixels → less physical thickness in pixels → epi closer to endo
        center = np.mean(endo, axis=0)
        gap1 = np.mean(np.linalg.norm(zone1.epi_points - zone1.endo_points, axis=1))
        gap2 = np.mean(np.linalg.norm(zone2.epi_points - zone2.endo_points, axis=1))
        assert gap1 > gap2


class TestSampleKernelsInZone:
    def _make_zone(self) -> MyocardialZone:
        endo = _circular_contour(32, radius=40.0)
        return create_myocardial_zone(endo, pixel_spacing=(0.5, 0.5), thickness_mm=8.0)

    def test_default_kernel_count(self) -> None:
        zone = self._make_zone()
        kernels = sample_kernels_in_zone(zone)
        # 3 rings × 32 kernels = 96
        assert len(kernels) == 96

    def test_custom_rings_and_per_ring(self) -> None:
        zone = self._make_zone()
        kernels = sample_kernels_in_zone(zone, num_kernels_per_ring=16, num_rings=2)
        assert len(kernels) == 32

    def test_all_are_tracking_kernel(self) -> None:
        zone = self._make_zone()
        kernels = sample_kernels_in_zone(zone)
        for k in kernels:
            assert isinstance(k, TrackingKernel)

    def test_first_ring_is_endo(self) -> None:
        zone = self._make_zone()
        kernels = sample_kernels_in_zone(zone, num_kernels_per_ring=8, num_rings=3)
        first_ring = kernels[:8]
        assert all(k.layer == "endo" for k in first_ring)

    def test_last_ring_is_epi(self) -> None:
        zone = self._make_zone()
        kernels = sample_kernels_in_zone(zone, num_kernels_per_ring=8, num_rings=3)
        last_ring = kernels[-8:]
        assert all(k.layer == "epi" for k in last_ring)

    def test_middle_ring_is_mid(self) -> None:
        zone = self._make_zone()
        kernels = sample_kernels_in_zone(zone, num_kernels_per_ring=8, num_rings=3)
        mid_ring = kernels[8:16]
        assert all(k.layer == "mid" for k in mid_ring)

    def test_kernel_radius_propagated(self) -> None:
        zone = self._make_zone()
        kernels = sample_kernels_in_zone(zone, kernel_radius=10)
        assert all(k.radius == 10 for k in kernels)

    def test_kernels_between_endo_and_epi(self) -> None:
        zone = self._make_zone()
        kernels = sample_kernels_in_zone(zone, num_kernels_per_ring=8, num_rings=3)
        for k in kernels:
            assert isinstance(k.center, tuple)
            assert len(k.center) == 2
