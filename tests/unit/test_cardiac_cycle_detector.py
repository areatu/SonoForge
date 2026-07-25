"""Tests for cardiac_cycle_detector module."""

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
    _estimate_lv_area_proxy,
    _shoelace_area,
    auto_detect_ed_es,
    average_strain_curves,
    build_myocardial_roi_mask,
    detect_cardiac_phases,
    detect_cycle_boundaries,
    detect_ed_es_from_frames,
    estimate_heart_rate_fft,
)


def _make_zone():
    """Create a simple MyocardialZone with triangular contours."""
    endo = np.array([[10, 50], [50, 10], [90, 50]], dtype=np.float64)
    epi = np.array([[5, 55], [50, 5], [95, 55]], dtype=np.float64)
    return MyocardialZone(
        endo_points=endo,
        epi_points=epi,
        thickness_mm=8.0,
        pixel_spacing=(1.0, 1.0),
    )


def _make_config():
    return SpeckleConfig()


class TestEstimateHeartRateFFT:
    def test_too_few_frames(self):
        frames = np.zeros((5, 64, 64), dtype=np.uint8)
        assert estimate_heart_rate_fft(frames) == 0.0

    def test_uniform_frames(self):
        frames = np.full((30, 64, 64), 128, dtype=np.uint8)
        hr = estimate_heart_rate_fft(frames, fps=30.0)
        assert hr == 0.0 or hr >= 0.0

    def test_sinusoidal_signal(self):
        """A 1 Hz sinusoidal signal at 30 fps should give ~60 BPM."""
        n_frames = 90
        fps = 30.0
        t = np.arange(n_frames) / fps
        signal_1hz = (np.sin(2 * np.pi * 1.0 * t) * 50 + 128).astype(np.uint8)
        # Build frames where each frame has a mean intensity matching the signal
        frames = np.zeros((n_frames, 16, 16), dtype=np.uint8)
        for i in range(n_frames):
            frames[i, :, :] = int(np.clip(signal_1hz[i], 0, 255))
        hr = estimate_heart_rate_fft(frames, fps=fps)
        assert 50.0 < hr < 70.0

    def test_with_roi_mask(self):
        n_frames = 90
        fps = 30.0
        t = np.arange(n_frames) / fps
        frames = np.zeros((n_frames, 32, 32), dtype=np.uint8)
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[8:24, 8:24] = 1
        for i in range(n_frames):
            val = int(np.clip(np.sin(2 * np.pi * 1.0 * t[i]) * 50 + 128, 0, 255))
            frames[i, 8:24, 8:24] = val
        hr = estimate_heart_rate_fft(frames, roi_mask=mask, fps=fps)
        assert 50.0 < hr < 70.0


class TestShoelaceArea:
    def test_triangle(self):
        pts = np.array([[0, 0], [4, 0], [2, 3]], dtype=np.float64)
        area = _shoelace_area(pts)
        assert area == pytest.approx(6.0, rel=0.01)

    def test_empty(self):
        assert _shoelace_area(np.array([], dtype=np.float64).reshape(0, 2)) == 0.0

    def test_two_points(self):
        pts = np.array([[0, 0], [1, 1]], dtype=np.float64)
        assert _shoelace_area(pts) == 0.0

    def test_with_ma_chord(self):
        pts = np.array([[10, 50], [50, 10], [90, 50]], dtype=np.float64)
        ma = ((10.0, 50.0), (90.0, 50.0))
        area = _shoelace_area(pts, ma_chord=ma)
        assert area > 0.0


class TestEstimateLvAreaProxy:
    def test_empty_zone(self):
        zone = MyocardialZone(
            endo_points=np.array([], dtype=np.float64).reshape(0, 2),
            epi_points=np.array([], dtype=np.float64).reshape(0, 2),
            thickness_mm=8.0,
            pixel_spacing=(1.0, 1.0),
        )
        frame = np.zeros((100, 100), dtype=np.uint8)
        assert _estimate_lv_area_proxy(frame, zone) == 0.0

    def test_3d_frame(self):
        zone = _make_zone()
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        assert _estimate_lv_area_proxy(frame, zone) == 0.0

    def test_valid_zone(self):
        zone = _make_zone()
        frame = np.full((100, 100), 100, dtype=np.uint8)
        result = _estimate_lv_area_proxy(frame, zone)
        assert result > 0.0


class TestDetectEdEsFromFrames:
    def test_few_frames(self):
        frames = np.zeros((2, 64, 64), dtype=np.uint8)
        zone = _make_zone()
        config = _make_config()
        ed, es = detect_ed_es_from_frames(frames, zone, config)
        assert ed == 0
        assert es in (0, 1)

    def test_varying_frames(self):
        """Frames with varying brightness should have different ED/ES."""
        n = 30
        frames = np.zeros((n, 100, 100), dtype=np.uint8)
        zone = _make_zone()
        # Create a synthetic area curve via brightness
        for i in range(n):
            frames[i, :, :] = int(80 + 40 * np.sin(2 * np.pi * i / n))
        config = _make_config()
        ed, es = detect_ed_es_from_frames(frames, zone, config)
        assert ed != es
        assert 0 <= ed < n
        assert 0 <= es < n


class TestDetectCycleBoundaries:
    def test_too_few_samples(self):
        assert detect_cycle_boundaries(np.ones(5)) == []

    def test_constant_signal(self):
        assert detect_cycle_boundaries(np.ones(30)) == []

    def test_sinusoidal_cycles(self):
        t = np.linspace(0, 4 * np.pi, 200)
        signal = np.sin(t)
        boundaries = detect_cycle_boundaries(signal, min_cycle_frames=15)
        assert len(boundaries) >= 1
        for start, end in boundaries:
            assert end > start

    def test_returns_list_of_tuples(self):
        t = np.linspace(0, 6 * np.pi, 300)
        signal = np.sin(t)
        boundaries = detect_cycle_boundaries(signal)
        for b in boundaries:
            assert isinstance(b, tuple)
            assert len(b) == 2


class TestAverageStrainCurves:
    def test_empty(self):
        result = average_strain_curves([], [], 10)
        assert result.shape == (10,)
        assert np.all(result == 0.0)

    def test_single_cycle(self):
        curve = np.sin(np.linspace(0, np.pi, 50))
        boundaries = [(0, 49)]
        result = average_strain_curves([curve], boundaries, 20)
        assert result.shape == (20,)

    def test_n_output_zero(self):
        result = average_strain_curves([], [], 0)
        assert result.shape == (0,)


class TestBuildMyocardialRoiMask:
    def test_invalid_shape(self):
        zone = _make_zone()
        mask = build_myocardial_roi_mask((0,), zone)
        assert mask.shape == (0, 0)

    def test_negative_dimensions(self):
        zone = _make_zone()
        mask = build_myocardial_roi_mask((-1, 10), zone)
        assert mask.shape == (0, 0)

    def test_valid_mask(self):
        zone = _make_zone()
        mask = build_myocardial_roi_mask((100, 100), zone)
        assert mask.dtype == bool
        assert mask.shape == (100, 100)


class TestAutoDetectEdEs:
    def test_few_frames(self):
        results = [TrackingResult(
            frame_index=i,
            displacements=np.zeros((3, 2)),
            ncc_scores=np.ones(3),
            valid_mask=np.ones(3, dtype=bool),
            kernel_positions=np.array([[10, 50], [50, 10], [90, 50]], dtype=np.float64),
        ) for i in range(1)]
        kernels = [
            TrackingKernel(center=(10, 50), layer="endo"),
            TrackingKernel(center=(50, 10), layer="endo"),
            TrackingKernel(center=(90, 50), layer="endo"),
        ]
        ed, es = auto_detect_ed_es(results, kernels)
        assert ed == 0
        assert es in (0, 1)

    def test_enough_frames(self):
        n = 10
        results = []
        for i in range(n - 1):
            # Vary kernel positions to create different areas
            angle = 2 * np.pi * i / n
            positions = np.array([
                [50 + 10 * np.cos(angle), 50 + 10 * np.sin(angle)],
                [30 + 5 * np.cos(angle), 50],
                [70 - 5 * np.cos(angle), 50],
            ], dtype=np.float64)
            results.append(TrackingResult(
                frame_index=i,
                displacements=np.zeros((3, 2)),
                ncc_scores=np.ones(3),
                valid_mask=np.ones(3, dtype=bool),
                kernel_positions=positions,
            ))
        kernels = [
            TrackingKernel(center=(50, 40), layer="endo"),
            TrackingKernel(center=(30, 50), layer="endo"),
            TrackingKernel(center=(70, 50), layer="endo"),
        ]
        ed, es = auto_detect_ed_es(results, kernels)
        assert ed != es
        assert 0 <= ed < n
        assert 0 <= es < n


class TestDetectCardiacPhases:
    def test_invalid_hr(self):
        frames = np.zeros((30, 64, 64), dtype=np.uint8)
        phases = detect_cardiac_phases(
            frames, [], [], heart_rate_bpm=0.0, fps=30.0,
        )
        assert "ED" in phases
        assert "ES" in phases

    def test_valid_phases(self):
        n = 60
        frames = np.zeros((n, 100, 100), dtype=np.uint8)
        results = [TrackingResult(
            frame_index=i,
            displacements=np.zeros((3, 2)),
            ncc_scores=np.ones(3),
            valid_mask=np.ones(3, dtype=bool),
            kernel_positions=np.array([[20, 50], [50, 10], [80, 50]], dtype=np.float64),
        ) for i in range(n - 1)]
        kernels = [
            TrackingKernel(center=(20, 50), layer="endo"),
            TrackingKernel(center=(50, 10), layer="endo"),
            TrackingKernel(center=(80, 50), layer="endo"),
        ]
        phases = detect_cardiac_phases(frames, results, kernels, heart_rate_bpm=72.0, fps=30.0)
        assert set(phases.keys()) == {"ED", "ES", "MD", "IR", "ER"}
        for key in phases:
            assert 0 <= phases[key] < n
