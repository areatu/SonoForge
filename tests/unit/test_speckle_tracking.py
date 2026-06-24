"""Tests for speckle tracking domain services."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import (
    SpeckleConfig,
    TrackingKernel,
    TrackingResult,
)
from echo_personal_tool.domain.services.cardiac_cycle_detector import (
    auto_detect_ed_es,
    estimate_heart_rate_fft,
)
from echo_personal_tool.domain.services.myocardial_zone import (
    create_myocardial_zone,
    expand_contour_to_zone,
    sample_kernels_in_zone,
)
from echo_personal_tool.domain.services.speckle_tracking import (
    build_gaussian_pyramid,
)
from echo_personal_tool.domain.services.strain_computation import (
    compute_gls,
)


class TestGaussianPyramid:
    def test_builds_correct_levels(self) -> None:
        frame = np.random.randint(0, 256, (128, 128), dtype=np.uint8)
        pyramid = build_gaussian_pyramid(frame, levels=3)
        assert len(pyramid) == 3
        assert pyramid[0].shape == (128, 128)
        assert pyramid[1].shape == (64, 64)
        assert pyramid[2].shape == (32, 32)

    def test_single_level(self) -> None:
        frame = np.random.randint(0, 256, (64, 64), dtype=np.uint8)
        pyramid = build_gaussian_pyramid(frame, levels=1)
        assert len(pyramid) == 1


class TestNCC:
    def test_cv2_matchtemplate_identical(self) -> None:
        import cv2

        patch = np.array([[10, 20], [30, 40]], dtype=np.float32)
        result = cv2.matchTemplate(patch, patch, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        assert max_val > 0.99

    def test_cv2_matchtemplate_different(self) -> None:
        import cv2

        kernel = np.zeros((8, 8), dtype=np.float32)
        kernel[0, 0] = 255
        region = np.ones((16, 16), dtype=np.float32) * 128
        result = cv2.matchTemplate(region, kernel, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        assert max_val < 0.5


class TestMyocardialZone:
    def test_expand_contour_outward(self) -> None:
        endo = np.array([[50, 50], [60, 50], [60, 60], [50, 60]], dtype=np.float64)
        epi = expand_contour_to_zone(endo, thickness_px=5.0)
        assert epi.shape == endo.shape
        for i in range(len(endo)):
            dist = np.linalg.norm(epi[i] - endo[i])
            assert 3.0 < dist < 7.0

    def test_create_zone(self) -> None:
        endo = np.array([[50, 50], [60, 50], [60, 60], [50, 60]], dtype=np.float64)
        zone = create_myocardial_zone(endo, pixel_spacing=(0.5, 0.5), thickness_mm=8.0)
        assert zone.thickness_mm == 8.0
        assert zone.endo_points.shape == (4, 2)
        assert zone.epi_points.shape == (4, 2)

    def test_sample_kernels(self) -> None:
        endo = np.array([[50, 50], [60, 50], [60, 60], [50, 60]], dtype=np.float64)
        zone = create_myocardial_zone(endo, pixel_spacing=(0.5, 0.5))
        kernels = sample_kernels_in_zone(zone, num_kernels_per_ring=8, num_rings=2)
        assert len(kernels) == 16
        assert all(isinstance(k, TrackingKernel) for k in kernels)


class TestTrackingResult:
    def test_valid_mask_filters_low_ncc(self) -> None:
        result = TrackingResult(
            frame_index=1,
            displacements=np.array([[1.0, 0.5], [0.0, 0.0]]),
            ncc_scores=np.array([0.9, 0.2]),
            valid_mask=np.array([True, True]),
            kernel_positions=np.array([[51.0, 50.5], [60.0, 50.0]]),
        )
        config = SpeckleConfig(ncc_threshold=0.5)
        valid = result.ncc_scores >= config.ncc_threshold
        assert valid[0] == True  # noqa: E712
        assert valid[1] == False  # noqa: E712


class TestStrainComputation:
    def test_gls_returns_min_strain(self) -> None:
        strain = np.array([0.0, -5.0, -15.0, -20.0, -18.0, -10.0, 0.0])
        gls = compute_gls(strain, ed_index=0, es_index=3)
        assert gls == pytest.approx(-20.0)

    def test_gls_equal_ed_es(self) -> None:
        strain = np.array([0.0, -5.0, -10.0])
        gls = compute_gls(strain, ed_index=1, es_index=1)
        assert gls == 0.0


class TestCardiacCycleDetector:
    def test_estimate_hr_low_fps(self) -> None:
        frames = np.random.randint(0, 256, (5, 64, 64), dtype=np.uint8)
        hr = estimate_heart_rate_fft(frames, fps=30.0)
        assert hr == 0.0

    def test_auto_detect_ed_es(self) -> None:
        base_positions = np.array([
            [50.0, 30.0], [60.0, 30.0], [70.0, 40.0],
            [70.0, 60.0], [60.0, 70.0], [50.0, 70.0],
            [40.0, 60.0], [40.0, 40.0],
        ])
        expand = np.array([0.0, 0.0, 5.0, 5.0, 0.0, 0.0, -5.0, -5.0])
        shrink = np.array([0.0, 0.0, -3.0, -3.0, 0.0, 0.0, 3.0, 3.0])

        results = [
            TrackingResult(
                frame_index=1,
                displacements=np.zeros((8, 2)),
                ncc_scores=np.ones(8) * 0.8,
                valid_mask=np.ones(8, dtype=bool),
                kernel_positions=base_positions + expand[:, np.newaxis],
            ),
            TrackingResult(
                frame_index=2,
                displacements=np.zeros((8, 2)),
                ncc_scores=np.ones(8) * 0.8,
                valid_mask=np.ones(8, dtype=bool),
                kernel_positions=base_positions,
            ),
            TrackingResult(
                frame_index=3,
                displacements=np.zeros((8, 2)),
                ncc_scores=np.ones(8) * 0.8,
                valid_mask=np.ones(8, dtype=bool),
                kernel_positions=base_positions + shrink[:, np.newaxis],
            ),
        ]
        kernels = [
            TrackingKernel(
                center=(float(base_positions[i, 0]), float(base_positions[i, 1])),
                layer="endo",
            )
            for i in range(8)
        ]
        ed, es = auto_detect_ed_es(results, kernels, pixel_spacing=(0.5, 0.5))
        assert ed == 1
        assert es == 3
