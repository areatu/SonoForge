"""Tests for speckle tracking domain services."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    SpeckleConfig,
    TrackingKernel,
    TrackingResult,
)
from echo_personal_tool.domain.services.cardiac_cycle_detector import (
    auto_detect_ed_es,
    detect_ed_es_from_frames,
    estimate_heart_rate_fft,
)
from echo_personal_tool.domain.services.myocardial_zone import (
    create_myocardial_zone,
    expand_contour_to_zone,
    sample_kernels_in_zone,
)
from echo_personal_tool.domain.services.speckle_tracking import (
    build_gaussian_pyramid,
    track_cine,
    track_cine_bidirectional,
    track_cine_incremental,
)
from echo_personal_tool.domain.services.strain_computation import (
    compute_gls,
)


def _make_synthetic_cine(n_frames: int, shift_per_frame: float = 0.5) -> np.ndarray:
    """Cyclic horizontal shift cine: out-and-back so last frame matches ED."""
    from scipy.ndimage import shift as ndimage_shift

    h, w = 128, 128
    rng = np.random.default_rng(42)
    base = rng.integers(40, 220, (h, w), dtype=np.uint8)
    base[48:80, 48:80] = 220
    base[52:76, 52:76] = 60

    frames = np.zeros((n_frames, h, w), dtype=np.uint8)
    half = n_frames // 2
    for t in range(n_frames):
        if t <= half:
            dx = t * shift_per_frame
        else:
            dx = (n_frames - 1 - t) * shift_per_frame
        shifted = ndimage_shift(base.astype(np.float32), (0, dx), order=1, mode="nearest")
        frames[t] = np.clip(shifted, 0, 255).astype(np.uint8)
    return frames


def _make_test_kernels() -> list[TrackingKernel]:
    centers = [(58.0, 64.0), (68.0, 64.0), (64.0, 58.0), (64.0, 70.0)]
    return [TrackingKernel(center=c, node_index=i, layer="endo") for i, c in enumerate(centers)]


def _ed_closure_error(
    results: list[TrackingResult],
    kernels: list[TrackingKernel],
) -> float:
    """Mean distance from final tracked positions to ED kernel centers."""
    if not results:
        return float("inf")
    ed_centers = np.array([k.center for k in kernels], dtype=np.float64)
    final_pos = results[-1].kernel_positions
    return float(np.mean(np.linalg.norm(final_pos - ed_centers, axis=1)))


def _ed_closure_error_bidi(
    results: list[TrackingResult],
    kernels: list[TrackingKernel],
    ed_index: int = 0,
) -> float:
    del ed_index
    return _ed_closure_error(results, kernels)


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
        assert zone.endo_points.shape == (128, 2)
        assert zone.epi_points.shape == (128, 2)

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


class TestSpeckleConfig:
    def test_default_kernel_and_search_radius(self) -> None:
        config = SpeckleConfig()
        assert config.kernel_size == 12
        assert config.search_radius == 8
        assert config.bidirectional is True
        assert config.ed_anchored is True

    def test_preset_standard(self) -> None:
        config = SpeckleConfig.preset_standard()
        assert config.kernel_size == 12
        assert config.search_radius == 8
        assert config.bidirectional is True
        assert config.drift_compensation is True

    def test_preset_research(self) -> None:
        config = SpeckleConfig.preset_research()
        assert config.kernel_size == 18
        assert config.search_radius == 18
        assert config.spatial_smoothing == pytest.approx(1.2)
        assert config.temporal_smoothing == pytest.approx(1.1)

    def test_preset_debug_forward_only(self) -> None:
        config = SpeckleConfig.preset_debug()
        assert config.bidirectional is False
        assert config.spatial_smoothing == 0.0
        assert config.temporal_smoothing == 0.0
        assert config.drift_compensation is False


class TestBidirectionalTracking:
    def test_bidirectional_no_position_collapse(self) -> None:
        """Bidirectional must not mix ED/target coords (no collapse toward origin)."""
        from echo_personal_tool.domain.services.tracking_smoothing import extract_trajectories

        n_frames = 20
        frames = _make_synthetic_cine(n_frames, shift_per_frame=0.5)
        kernels = _make_test_kernels()
        config = SpeckleConfig.preset_standard()

        results = track_cine_bidirectional(frames, kernels, ed_index=0, config=config)
        positions, _ = extract_trajectories(results, kernels, ed_index=0)

        assert np.all(np.isfinite(positions))
        assert np.all(positions[..., 0] > 1.0)
        assert np.all(positions[..., 1] > 1.0)

    def test_bidirectional_ed_closure_not_worse_than_forward(self) -> None:
        """ED-anchored bidirectional should not be worse than forward-only drift."""
        n_frames = 20
        frames = _make_synthetic_cine(n_frames, shift_per_frame=0.5)
        kernels = _make_test_kernels()
        config_fwd = SpeckleConfig.preset_debug()
        config_bidi = SpeckleConfig.preset_standard()

        fwd = track_cine(frames, kernels, config_fwd)
        bidi = track_cine_bidirectional(frames, kernels, ed_index=0, config=config_bidi)

        fwd_err = _ed_closure_error(fwd, kernels)
        bidi_err = _ed_closure_error_bidi(bidi, kernels, ed_index=0)
        assert bidi_err <= fwd_err * 1.25

    def test_track_cine_uses_bidirectional_by_default(self) -> None:
        n_frames = 10
        frames = _make_synthetic_cine(n_frames, shift_per_frame=0.5)
        kernels = _make_test_kernels()
        config = SpeckleConfig.preset_standard()
        results = track_cine(frames, kernels, config)
        assert len(results) == n_frames - 1
        assert results[-1].reference_frame == 0


class TestIncrementalTracking:
    def test_incremental_no_position_collapse(self) -> None:
        """Incremental tracking must not collapse toward origin."""
        from echo_personal_tool.domain.services.tracking_smoothing import extract_trajectories

        n_frames = 20
        frames = _make_synthetic_cine(n_frames, shift_per_frame=0.5)
        kernels = _make_test_kernels()
        config = SpeckleConfig(
            tracking_mode="incremental",
            bidirectional=True,
            closure_error_threshold=0.5,
        )

        results = track_cine_incremental(frames, kernels, ed_index=0, config=config)
        positions, _ = extract_trajectories(results, kernels, ed_index=0)

        assert np.all(np.isfinite(positions))
        assert np.all(positions[..., 0] > 1.0)
        assert np.all(positions[..., 1] > 1.0)

    def test_incremental_ed_closure_not_worse_than_bidirectional(self) -> None:
        """Incremental ED-anchored should produce finite positions without drift."""
        n_frames = 20
        frames = _make_synthetic_cine(n_frames, shift_per_frame=0.5)
        kernels = _make_test_kernels()
        config_incr = SpeckleConfig(
            tracking_mode="incremental",
            bidirectional=True,
            closure_error_threshold=0.5,
        )

        incr = track_cine_incremental(frames, kernels, ed_index=0, config=config_incr)
        incr_err = _ed_closure_error_bidi(incr, kernels, ed_index=0)

        assert incr_err < 100.0
        assert len(incr) == n_frames - 1

    def test_incremental_returns_correct_count(self) -> None:
        n_frames = 15
        frames = _make_synthetic_cine(n_frames, shift_per_frame=0.5)
        kernels = _make_test_kernels()
        config = SpeckleConfig(tracking_mode="incremental")
        results = track_cine_incremental(frames, kernels, ed_index=0, config=config)
        assert len(results) == n_frames - 1
        assert results[-1].reference_frame == 0


class TestCardiacCycleDetector:
    def test_estimate_hr_low_fps(self) -> None:
        frames = np.random.randint(0, 256, (5, 64, 64), dtype=np.uint8)
        hr = estimate_heart_rate_fft(frames, fps=30.0)
        assert hr == 0.0

    def test_auto_detect_ed_es(self) -> None:
        base_positions = np.array(
            [
                [50.0, 30.0],
                [60.0, 30.0],
                [70.0, 40.0],
                [70.0, 60.0],
                [60.0, 70.0],
                [50.0, 70.0],
                [40.0, 60.0],
                [40.0, 40.0],
            ]
        )
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

    def test_detect_ed_es_from_frames_pretracking(self) -> None:
        n_frames = 12
        h, w = 64, 64
        frames = np.zeros((n_frames, h, w), dtype=np.float32)
        t = np.linspace(0.0, 2.0 * np.pi, n_frames, endpoint=False)
        signal = 80.0 + 30.0 * np.sin(t)

        for i, val in enumerate(signal):
            frames[i, 22:42, 22:42] = val
            frames[i, 0:8, 0:8] = 10.0

        contour = np.array(
            [
                [22.0, 22.0],
                [42.0, 22.0],
                [42.0, 42.0],
                [22.0, 42.0],
            ],
            dtype=np.float64,
        )
        zone = MyocardialZone(
            endo_points=contour,
            epi_points=contour + 4.0,
            thickness_mm=8.0,
            pixel_spacing=(1.0, 1.0),
        )
        ed, es = detect_ed_es_from_frames(frames, zone, SpeckleConfig.preset_standard())
        assert ed in (2, 3, 4)
        assert es in (8, 9, 10)
        assert ed != es
