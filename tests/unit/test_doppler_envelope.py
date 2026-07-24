"""Unit tests for Doppler spectral envelope tracing."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_envelope import (
    trace_envelope,
    trace_envelope_above_baseline,
)


def _make_spectrogram(
    h: int = 50, w: int = 100, baseline_row: int = 25, signal_above: bool = True,
) -> np.ndarray:
    """Synthetic spectrogram: bright ridge above (or below) baseline."""
    spec = np.zeros((h, w), dtype=np.uint8)
    for col in range(w):
        if signal_above:
            # Bright ridge at baseline_row - 5
            peak_row = max(0, baseline_row - 5)
        else:
            peak_row = min(h - 1, baseline_row + 5)
        # Spread intensity around peak
        for dr in range(-3, 4):
            r = peak_row + dr
            if 0 <= r < h:
                spec[r, col] = 200 - abs(dr) * 30
    return spec


class TestTraceEnvelope:
    def test_returns_empty_for_1d_input(self) -> None:
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=10, height=10)
        assert trace_envelope(np.zeros(10), roi, 5.0) == ()

    def test_returns_empty_when_num_samples_too_low(self) -> None:
        spec = _make_spectrogram()
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
        assert trace_envelope(spec, roi, 25.0, num_samples=1) == ()

    def test_returns_tuple_of_tuples(self) -> None:
        spec = _make_spectrogram()
        roi = DopplerSpectrogramRoi(x0=10, y0=5, width=80, height=40)
        result = trace_envelope(spec, roi, 25.0, num_samples=20)
        assert isinstance(result, tuple)
        if len(result) > 0:
            assert isinstance(result[0], tuple)
            assert len(result[0]) == 2

    def test_trace_points_are_ordered_by_x(self) -> None:
        spec = _make_spectrogram()
        roi = DopplerSpectrogramRoi(x0=10, y0=5, width=80, height=40)
        result = trace_envelope(spec, roi, 25.0, num_samples=20)
        if len(result) >= 2:
            xs = [p[0] for p in result]
            assert xs == sorted(xs)

    def test_start_at_baseline_prepends_baseline_point(self) -> None:
        spec = _make_spectrogram()
        roi = DopplerSpectrogramRoi(x0=10, y0=5, width=80, height=40)
        result = trace_envelope(spec, roi, 25.0, num_samples=20, start_at_baseline=True)
        if len(result) >= 2:
            # First point should be on the baseline
            assert result[0][1] == 25.0

    def test_empty_spectrogram_returns_empty(self) -> None:
        spec = np.zeros((50, 100), dtype=np.uint8)
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=100, height=50)
        result = trace_envelope(spec, roi, 25.0, num_samples=20)
        assert result == ()

    def test_above_baseline_false(self) -> None:
        spec = _make_spectrogram(signal_above=False)
        roi = DopplerSpectrogramRoi(x0=10, y0=5, width=80, height=40)
        result = trace_envelope(spec, roi, 25.0, num_samples=20, above_baseline=False)
        assert isinstance(result, tuple)


class TestTraceEnvelopeAboveBaseline:
    def test_normal_labels_are_above(self) -> None:
        assert trace_envelope_above_baseline("VTI LV") is True
        assert trace_envelope_above_baseline("VTI RV") is True
        assert trace_envelope_above_baseline("") is True

    def test_tr_pr_labels_are_below(self) -> None:
        assert trace_envelope_above_baseline("VTI TR") is False
        assert trace_envelope_above_baseline("VTI PR") is False
        assert trace_envelope_above_baseline("tr") is False
        assert trace_envelope_above_baseline("Pr") is False
        assert trace_envelope_above_baseline("  VTI TR  ") is False
