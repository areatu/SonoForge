"""Tests for doppler_envelope tracing functions."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_envelope import (
    trace_envelope,
    trace_envelope_above_baseline,
)


def _roi(x0=0, y0=0, w=100, h=50):
    return DopplerSpectrogramRoi(x0=x0, y0=y0, width=w, height=h)


class TestTraceEnvelopeAboveBaseline:
    """trace_envelope_above_baseline: TR/PR envelopes are below baseline."""

    @pytest.mark.parametrize("label", ["VTI TR", "vti tr", "TR", "tr", "PR", "pr", "VTI PR"])
    def test_below_baseline_labels(self, label):
        assert trace_envelope_above_baseline(label) is False

    @pytest.mark.parametrize("label", ["VTI", "LVOT", "MV", "AAo", "vti", ""])
    def test_above_baseline_labels(self, label):
        assert trace_envelope_above_baseline(label) is True

    def test_whitespace_handling(self):
        assert trace_envelope_above_baseline("  VTI TR  ") is False
        assert trace_envelope_above_baseline("  VTI  ") is True


class TestTraceEnvelope:
    """trace_envelope: column-wise intensity ridge extraction."""

    def test_returns_tuple(self):
        gray = np.random.randint(0, 50, size=(60, 120), dtype=np.uint8)
        result = trace_envelope(gray, _roi(), baseline_y_px=30.0, num_samples=16)
        assert isinstance(result, tuple)

    def test_empty_for_3d_input(self):
        rgb = np.random.randint(0, 50, size=(60, 120, 3), dtype=np.uint8)
        result = trace_envelope(rgb, _roi(), baseline_y_px=30.0)
        assert result == ()

    def test_few_samples_returns_empty(self):
        gray = np.zeros((60, 120), dtype=np.uint8)
        result = trace_envelope(gray, _roi(), baseline_y_px=30.0, num_samples=1)
        assert result == ()

    def test_uniform_low_intensity_returns_empty(self):
        gray = np.full((60, 120), 5, dtype=np.uint8)
        result = trace_envelope(gray, _roi(), baseline_y_px=30.0, num_samples=16)
        assert result == ()

    def test_bright_signal_above_baseline(self):
        """A bright diagonal ridge should produce trace points."""
        gray = np.zeros((60, 120), dtype=np.uint8)
        baseline = 30
        # Create a strong diagonal signal above baseline
        for col in range(10, 110):
            row = max(0, baseline - (col - 10) // 4)
            gray[row, col] = 200
        result = trace_envelope(gray, _roi(), baseline_y_px=float(baseline), num_samples=20)
        assert len(result) >= 2

    def test_points_are_float_tuples(self):
        gray = np.zeros((60, 120), dtype=np.uint8)
        for col in range(10, 110):
            gray[15, col] = 200
        result = trace_envelope(gray, _roi(), baseline_y_px=30.0, num_samples=20)
        if len(result) >= 2:
            for pt in result:
                assert isinstance(pt, tuple)
                assert len(pt) == 2
                assert isinstance(pt[0], float)
                assert isinstance(pt[1], float)

    def test_start_at_baseline_prepend(self):
        gray = np.zeros((60, 120), dtype=np.uint8)
        for col in range(10, 110):
            gray[15, col] = 200
        result = trace_envelope(gray, _roi(), baseline_y_px=30.0, num_samples=20, start_at_baseline=True)
        if len(result) >= 2:
            # First point should be on the baseline
            assert result[0][1] == pytest.approx(30.0, abs=0.1)

    def test_start_at_baseline_false(self):
        gray = np.zeros((60, 120), dtype=np.uint8)
        for col in range(10, 110):
            gray[15, col] = 200
        result = trace_envelope(
            gray, _roi(), baseline_y_px=30.0, num_samples=20,
            start_at_baseline=False, above_baseline=True,
        )
        if len(result) >= 2:
            assert result[0][1] != pytest.approx(30.0, abs=0.1)

    def test_below_baseline_mode(self):
        gray = np.zeros((60, 120), dtype=np.uint8)
        baseline = 20
        for col in range(10, 110):
            row = min(59, baseline + (col - 10) // 4)
            gray[row, col] = 200
        result = trace_envelope(
            gray, _roi(), baseline_y_px=float(baseline), num_samples=20,
            above_baseline=False,
        )
        assert len(result) >= 2

    def test_roi_clamped_to_image(self):
        gray = np.zeros((40, 60), dtype=np.uint8)
        roi = _roi(x0=0, y0=0, w=200, h=200)
        result = trace_envelope(gray, roi, baseline_y_px=10.0, num_samples=16)
        assert isinstance(result, tuple)
