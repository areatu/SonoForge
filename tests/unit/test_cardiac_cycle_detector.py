"""Unit tests for cardiac_cycle_detector service."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    SpeckleConfig,
    TrackingKernel,
    TrackingResult,
)
from echo_personal_tool.domain.services.cardiac_cycle_detector import (
    _shoelace_area,
    auto_detect_ed_es,
    average_strain_curves,
    build_myocardial_roi_mask,
    detect_cardiac_phases,
    detect_cycle_boundaries,
    detect_ed_es_from_frames,
    estimate_heart_rate_fft,
)


# ── estimate_heart_rate_fft ────────────────────────────────────────


class TestEstimateHeartRateFft:
    def test_too_few_frames(self) -> None:
        frames = np.zeros((5, 32, 32), dtype=np.uint8)
        assert estimate_heart_rate_fft(frames) == 0.0

    def test_sinusoidal_signal(self) -> None:
        fps = 30.0
        n = 60
        t = np.arange(n) / fps
        signal = np.sin(2 * np.pi * 1.2 * t)  # 1.2 Hz = 72 BPM
        # Use float frames to avoid uint8 quantization
        frames = np.zeros((n, 16, 16), dtype=np.float64)
        for i in range(n):
            frames[i] = 128.0 + 50.0 * signal[i]
        hr = estimate_heart_rate_fft(frames, fps=fps)
        # FFT resolution: fps/n = 0.5 Hz = 30 BPM; allow wide tolerance
        assert 55.0 < hr < 90.0

    def test_constant_signal(self) -> None:
        frames = np.full((30, 16, 16), 128, dtype=np.uint8)
        hr = estimate_heart_rate_fft(frames, fps=30.0)
        assert hr == 0.0

    def test_with_roi_mask(self) -> None:
        n = 30
        frames = np.zeros((n, 16, 16), dtype=np.uint8)
        mask = np.zeros((16, 16), dtype=np.uint8)
        mask[4:12, 4:12] = 1
        for i in range(n):
            frames[i][mask > 0] = int(128 + 30 * np.sin(2 * np.pi * 1.0 * i / n))
        hr = estimate_heart_rate_fft(frames, roi_mask=mask, fps=30.0)
        assert hr > 0.0


# ── _shoelace_area ─────────────────────────────────────────────────


class TestShoelaceArea:
    def test_triangle(self) -> None:
        pts = np.array([[0.0, 0.0], [10.0, 0.0], [5.0, 10.0]])
        area = _shoelace_area(pts)
        assert abs(area - 50.0) < 1e-6

    def test_square(self) -> None:
        pts = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
        area = _shoelace_area(pts)
        assert abs(area - 100.0) < 1e-6

    def test_with_ma_chord(self) -> None:
        pts = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])
        ma = ((0.0, 0.0), (10.0, 10.0))
        area = _shoelace_area(pts, ma_chord=ma)
        assert area > 0.0

    def test_too_few_points(self) -> None:
        pts = np.array([[0.0, 0.0], [10.0, 0.0]])
        assert _shoelace_area(pts) == 0.0

    def test_single_point(self) -> None:
        pts = np.array([[5.0, 5.0]])
        assert _shoelace_area(pts) == 0.0


# ── detect_cycle_boundaries ────────────────────────────────────────


class TestDetectCycleBoundaries:
    def test_too_short(self) -> None:
        areas = np.array([1.0, 2.0, 3.0])
        assert detect_cycle_boundaries(areas, min_cycle_frames=15) == []

    def test_constant_signal(self) -> None:
        areas = np.full(30, 100.0)
        assert detect_cycle_boundaries(areas, min_cycle_frames=5) == []

    def test_periodic_signal(self) -> None:
        # Two clear peaks
        x = np.arange(60)
        areas = np.sin(2 * np.pi * x / 30)
        boundaries = detect_cycle_boundaries(areas, min_cycle_frames=10)
        assert len(boundaries) >= 1
        for start, end in boundaries:
            assert end > start

    def test_single_peak(self) -> None:
        areas = np.array([1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 2, 1])
        boundaries = detect_cycle_boundaries(areas, min_cycle_frames=5)
        assert len(boundaries) == 0  # need >= 2 peaks


# ── average_strain_curves ──────────────────────────────────────────


class TestAverageStrainCurves:
    def test_no_boundaries(self) -> None:
        curves = [np.array([1.0, 2.0, 3.0])]
        result = average_strain_curves(curves, [], n_output_frames=10)
        assert result.shape == (10,)
        assert np.all(result == 0.0)

    def test_single_curve(self) -> None:
        curve = np.linspace(0.0, 1.0, 20)
        boundaries = [(0, 19)]
        result = average_strain_curves([curve], boundaries, n_output_frames=10)
        assert result.shape == (10,)
        assert result[0] < result[-1]  # ascending

    def test_average_of_two(self) -> None:
        c1 = np.linspace(0.0, 1.0, 20)
        c2 = np.linspace(0.0, 0.8, 20)
        boundaries = [(0, 19)]
        result = average_strain_curves([c1, c2], boundaries, n_output_frames=10)
        assert result.shape == (10,)
        # Average of 1.0 and 0.8 at last point
        assert abs(result[-1] - 0.9) < 0.01

    def test_zero_output_frames(self) -> None:
        result = average_strain_curves([np.ones(10)], [(0, 9)], n_output_frames=0)
        assert result.shape == (0,)


# ── build_myocardial_roi_mask ──────────────────────────────────────


class TestBuildMyocardialRoiMask:
    def _make_zone(self) -> MyocardialZone:
        angles = np.linspace(0, 2 * np.pi, 32, endpoint=False)
        endo = np.column_stack([50 + 20 * np.cos(angles), 50 + 20 * np.sin(angles)])
        epi = np.column_stack([50 + 30 * np.cos(angles), 50 + 30 * np.sin(angles)])
        return MyocardialZone(
            endo_points=endo, epi_points=epi,
            thickness_mm=8.0, pixel_spacing=(0.5, 0.5),
        )

    def test_returns_bool_mask(self) -> None:
        zone = self._make_zone()
        mask = build_myocardial_roi_mask((100, 100), zone)
        assert mask.dtype == bool
        assert mask.shape == (100, 100)

    def test_has_true_pixels(self) -> None:
        zone = self._make_zone()
        mask = build_myocardial_roi_mask((100, 100), zone)
        assert mask.any()

    def test_invalid_shape(self) -> None:
        zone = self._make_zone()
        mask = build_myocardial_roi_mask((0, 0), zone)
        assert mask.shape == (0, 0)

    def test_1d_shape(self) -> None:
        mask = build_myocardial_roi_mask((100,), self._make_zone())
        assert mask.shape == (0, 0)


# ── auto_detect_ed_es ──────────────────────────────────────────────


class TestAutoDetectEdEs:
    def _make_kernels(self, n: int = 16, layer: str = "endo") -> list[TrackingKernel]:
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
        return [
            TrackingKernel(center=(float(50 + 20 * np.cos(a)), float(50 + 20 * np.sin(a))), layer=layer)
            for a in angles
        ]

    def _make_tracking_result(self, scale: float = 1.0) -> TrackingResult:
        n = 16
        positions = np.array([(50 + 20 * scale * np.cos(a), 50 + 20 * scale * np.sin(a))
                              for a in np.linspace(0, 2 * np.pi, n, endpoint=False)])
        return TrackingResult(
            frame_index=0,
            displacements=np.zeros((n, 2)),
            ncc_scores=np.ones(n),
            valid_mask=np.ones(n, dtype=bool),
            kernel_positions=positions,
        )

    def test_too_few_frames(self) -> None:
        kernels = self._make_kernels()
        ed, es = auto_detect_ed_es([], kernels)
        assert ed == 0
        assert es <= 1

    def test_few_endo_kernels(self) -> None:
        kernels = [TrackingKernel(center=(0.0, 0.0), layer="epi")]
        results = [self._make_tracking_result() for _ in range(5)]
        ed, es = auto_detect_ed_es(results, kernels)
        assert ed == 0

    def test_normal_case(self) -> None:
        kernels = self._make_kernels()
        # Frame 0: large area (ED), Frame 1: small area (ES), Frame 2: large again
        r0 = self._make_tracking_result(1.0)
        r1 = self._make_tracking_result(0.5)
        ed, es = auto_detect_ed_es([r0, r1], kernels)
        assert ed != es
        assert 0 <= ed <= 2
        assert 0 <= es <= 2


# ── detect_cardiac_phases ──────────────────────────────────────────


class TestDetectCardiacPhases:
    def _make_frames(self, n: int = 30) -> np.ndarray:
        return np.zeros((n, 32, 32), dtype=np.uint8)

    def _make_kernels(self, n: int = 16) -> list[TrackingKernel]:
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
        return [
            TrackingKernel(center=(float(16 + 10 * np.cos(a)), float(16 + 10 * np.sin(a))), layer="endo")
            for a in angles
        ]

    def test_zero_hr(self) -> None:
        frames = self._make_frames(30)
        kernels = self._make_kernels()
        phases = detect_cardiac_phases(frames, [], kernels, heart_rate_bpm=0, fps=30.0)
        assert "ED" in phases
        assert "ES" in phases

    def test_normal(self) -> None:
        frames = self._make_frames(60)
        kernels = self._make_kernels()
        n = 16
        results = []
        for i in range(59):
            scale = 1.0 if i % 30 < 15 else 0.6
            positions = np.array([(16 + 10 * scale * np.cos(a), 16 + 10 * scale * np.sin(a))
                                  for a in np.linspace(0, 2 * np.pi, n, endpoint=False)])
            results.append(TrackingResult(
                frame_index=i, displacements=np.zeros((n, 2)),
                ncc_scores=np.ones(n), valid_mask=np.ones(n, dtype=bool),
                kernel_positions=positions,
            ))
        phases = detect_cardiac_phases(frames, results, kernels, heart_rate_bpm=72, fps=30.0)
        assert "ED" in phases
        assert "ES" in phases
        assert "MD" in phases
        assert "IR" in phases
        assert "ER" in phases


# ── detect_ed_es_from_frames ───────────────────────────────────────


class TestDetectEdEsFromFrames:
    def _make_zone(self) -> MyocardialZone:
        angles = np.linspace(0, 2 * np.pi, 16, endpoint=False)
        endo = np.column_stack([16 + 5 * np.cos(angles), 16 + 5 * np.sin(angles)])
        epi = np.column_stack([16 + 8 * np.cos(angles), 16 + 8 * np.sin(angles)])
        return MyocardialZone(
            endo_points=endo, epi_points=epi,
            thickness_mm=8.0, pixel_spacing=(0.5, 0.5),
        )

    def test_too_few_frames(self) -> None:
        frames = np.zeros((2, 32, 32), dtype=np.uint8)
        zone = self._make_zone()
        ed, es = detect_ed_es_from_frames(frames, zone, SpeckleConfig())
        assert ed == 0

    def test_normal(self) -> None:
        zone = self._make_zone()
        n = 20
        frames = np.zeros((n, 32, 32), dtype=np.uint8)
        # Make frame 5 brighter (ED) and frame 15 darker (ES)
        for i in range(n):
            if i == 5:
                frames[i] = 200
            elif i == 15:
                frames[i] = 50
            else:
                frames[i] = 128
        ed, es = detect_ed_es_from_frames(frames, zone, SpeckleConfig())
        assert ed != es
        assert 0 <= ed < n
        assert 0 <= es < n
