"""Tests for heart rate estimation (optical flow + area-time)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.heart_rate import (
    HeartRateResult,
    _autocorrelation_bpm,
    _find_local_minima,
    estimate_hr_area_time,
    estimate_hr_optical_flow,
)


class TestAutocorrelation:
    def test_sine_wave_60bpm(self):
        """A 1 Hz sine at 30 fps should give ~60 BPM."""
        fps = 30.0
        t = np.arange(0, 5, 1 / fps)  # 5 seconds
        sig = np.sin(2 * np.pi * 1.0 * t)  # 1 Hz = 60 BPM
        bpm, conf, period_ms = _autocorrelation_bpm(sig, fps)
        assert abs(bpm - 60.0) < 5.0
        assert conf > 0.5

    def test_sine_wave_90bpm(self):
        """A 1.5 Hz sine at 30 fps should give ~90 BPM."""
        fps = 30.0
        t = np.arange(0, 5, 1 / fps)
        sig = np.sin(2 * np.pi * 1.5 * t)  # 1.5 Hz = 90 BPM
        bpm, conf, period_ms = _autocorrelation_bpm(sig, fps)
        assert abs(bpm - 90.0) < 5.0
        assert conf > 0.5

    def test_constant_signal(self):
        """Constant signal should give 0 BPM."""
        sig = np.ones(100)
        bpm, conf, _ = _autocorrelation_bpm(sig, 30.0)
        assert bpm == 0.0

    def test_short_signal(self):
        """Very short signal should give 0 BPM."""
        sig = np.array([1.0, 2.0])
        bpm, conf, _ = _autocorrelation_bpm(sig, 30.0)
        assert bpm == 0.0


class TestLocalMinima:
    def test_simple_v_shape(self):
        data = np.array([5, 4, 3, 4, 5, 4, 3, 4, 5])
        minima = _find_local_minima(data)
        assert minima == [2, 6]

    def test_no_minima(self):
        data = np.array([1, 2, 3, 4, 5])
        minima = _find_local_minima(data)
        assert minima == []

    def test_single_minimum(self):
        data = np.array([5, 3, 5])
        minima = _find_local_minima(data)
        assert minima == [1]


class TestAreaTime:
    def test_regular_60bpm(self):
        """6 ES frames at 30 fps, every 30 frames = 1s interval = 60 BPM."""
        fps = 30.0
        # Simulate area curve with minima at frames 0, 30, 60, 90, 120, 150
        areas = []
        for i in range(180):
            # Sine-like area: min at 0, 30, 60, ...
            phase = (i % 30) / 30.0 * 2 * np.pi
            areas.append(10.0 + 5.0 * np.cos(phase))
        result = estimate_hr_area_time(areas, fps=fps)
        assert abs(result.bpm - 60.0) < 10.0
        assert result.confidence > 0.3

    def test_too_few_frames(self):
        result = estimate_hr_area_time([10.0, 8.0], fps=30.0)
        assert result.bpm == 0.0

    def test_constant_area(self):
        areas = [10.0] * 20
        result = estimate_hr_area_time(areas, fps=30.0)
        # May return 0 or low BPM for constant signal
        assert result.bpm >= 0.0


class TestOpticalFlow:
    def test_static_frames(self):
        """Identical frames should give 0 BPM."""
        frame = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
        frames = [frame.copy() for _ in range(10)]
        result = estimate_hr_optical_flow(frames, fps=30.0)
        assert result.bpm == 0.0

    def test_too_few_frames(self):
        frame = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
        result = estimate_hr_optical_flow([frame, frame], fps=30.0)
        assert result.bpm == 0.0

    def test_moving_edge(self):
        """Synthetic: vertical edge oscillates at 1.5 Hz = 90 BPM."""
        fps = 30.0
        n_frames = 150
        frames = []
        for i in range(n_frames):
            frame = np.zeros((100, 100), dtype=np.uint8)
            # Edge position oscillates at 1.5 Hz
            edge_x = int(50 + 20 * np.sin(2 * np.pi * 1.5 * i / fps))
            frame[:, :edge_x] = 200
            frames.append(frame)
        result = estimate_hr_optical_flow(frames, fps=fps)
        assert result.bpm > 0.0
        assert result.confidence > 0.0
