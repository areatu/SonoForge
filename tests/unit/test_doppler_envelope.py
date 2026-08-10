"""Tests for doppler_envelope tracing functions."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_envelope import (
    VESSEL_ENVELOPE_PRESETS,
    extract_doppler_envelope,
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
            gray,
            _roi(),
            baseline_y_px=30.0,
            num_samples=20,
            start_at_baseline=False,
            above_baseline=True,
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
            gray,
            _roi(),
            baseline_y_px=float(baseline),
            num_samples=20,
            above_baseline=False,
        )
        assert len(result) >= 2

    def test_roi_clamped_to_image(self):
        gray = np.zeros((40, 60), dtype=np.uint8)
        roi = _roi(x0=0, y0=0, w=200, h=200)
        result = trace_envelope(gray, roi, baseline_y_px=10.0, num_samples=16)
        assert isinstance(result, tuple)


def _vessel_spectrum(height=80, width=120, baseline=50, edge_row=20):
    """Bright spectral flow whose top edge sits at *edge_row* (above baseline)."""
    gray = np.zeros((height, width), dtype=np.uint8)
    for col in range(10, width - 10):
        gray[edge_row:baseline, col] = 180
    return gray


class TestExtractDopplerEnvelope:
    def test_empty_for_3d_input(self):
        rgb = np.random.randint(0, 50, size=(60, 120, 3), dtype=np.uint8)
        assert extract_doppler_envelope(rgb, _roi(), baseline_y_px=30.0) == ()

    def test_empty_for_no_signal(self):
        gray = np.zeros((60, 120), dtype=np.uint8)
        assert extract_doppler_envelope(gray, _roi(), baseline_y_px=30.0) == ()

    def test_empty_for_uniform_bright(self):
        gray = np.full((60, 120), 200, dtype=np.uint8)
        assert extract_doppler_envelope(gray, _roi(), baseline_y_px=30.0) == ()

    def test_returns_plot_points_for_strong_signal(self):
        gray = _vessel_spectrum()
        result = extract_doppler_envelope(gray, _roi(w=120, h=80), baseline_y_px=50.0)
        assert len(result) >= 2
        for pt in result:
            assert isinstance(pt, tuple) and len(pt) == 2
            assert isinstance(pt[0], float) and isinstance(pt[1], float)

    def test_points_above_baseline(self):
        gray = _vessel_spectrum()
        result = extract_doppler_envelope(gray, _roi(w=120, h=80), baseline_y_px=50.0)
        for pt in result:
            assert pt[1] < 50.0

    def test_x_is_monotonic(self):
        gray = _vessel_spectrum()
        result = extract_doppler_envelope(gray, _roi(w=120, h=80), baseline_y_px=50.0)
        xs = [pt[0] for pt in result]
        assert xs == sorted(xs)

    def test_envelope_follows_top_edge(self):
        gray = _vessel_spectrum(edge_row=20)
        result = extract_doppler_envelope(gray, _roi(w=120, h=80), baseline_y_px=50.0)
        ys = [pt[1] for pt in result]
        assert abs(float(np.median(ys)) - 20.5) < 3.0

    def test_interpolates_gap_in_signal(self):
        gray = _vessel_spectrum()
        # wipe a vertical band in the middle of the flow
        gray[10:50, 55:70] = 0
        result = extract_doppler_envelope(gray, _roi(w=120, h=80), baseline_y_px=50.0)
        assert len(result) >= 2

    def test_preset_parametrization(self):
        assert VESSEL_ENVELOPE_PRESETS["low"].k < VESSEL_ENVELOPE_PRESETS["normal"].k
        assert VESSEL_ENVELOPE_PRESETS["normal"].k < VESSEL_ENVELOPE_PRESETS["high"].k

    def test_unknown_preset_falls_back_to_normal(self):
        gray = _vessel_spectrum()
        a = extract_doppler_envelope(gray, _roi(w=120, h=80), baseline_y_px=50.0, preset="normal")
        b = extract_doppler_envelope(gray, _roi(w=120, h=80), baseline_y_px=50.0, preset="nonsense")
        assert a == b

    def test_noisy_background_still_traces_with_high_preset(self):
        rng = np.random.default_rng(42)
        gray = _vessel_spectrum()
        noise = rng.integers(0, 40, size=gray.shape, dtype=np.uint8)
        gray = np.clip(gray.astype(int) + noise, 0, 255).astype(np.uint8)
        result = extract_doppler_envelope(gray, _roi(w=120, h=80), baseline_y_px=50.0, preset="high")
        assert len(result) >= 2

    def _frame_with_text_and_spectrum(self):
        """Doppler frame with a pulsing flow plus a technical-text line at the top."""
        h, w = 120, 160
        gray = np.zeros((h, w), dtype=np.uint8)
        rng = np.random.default_rng(7)
        gray[20:100, :] = rng.integers(0, 25, size=(80, w), dtype=np.uint8)
        for c in range(15, 145):
            top = int(50 + 30 * abs(c - 80) / 65)
            gray[top:95, c] = 200
        for col, cw in (
            (2, 8),
            (6, 8),
            (10, 8),
            (14, 4),
            (18, 4),
            (22, 4),
            (26, 4),
            (30, 8),
            (34, 8),
            (38, 8),
            (42, 4),
        ):
            gray[10:13, col : col + cw] = 230
        return gray

    def test_text_above_spectrum_is_not_traced(self):
        gray = self._frame_with_text_and_spectrum()
        result = extract_doppler_envelope(gray, _roi(w=160, h=120), baseline_y_px=95.0, preset="normal")
        assert len(result) >= 2
        assert all(pt[1] > 15.0 for pt in result), "trace must not follow the text glyphs"

    def test_spectrum_is_traced_when_text_sits_in_noise_region(self):
        gray = self._frame_with_text_and_spectrum()
        result = extract_doppler_envelope(gray, _roi(w=160, h=120), baseline_y_px=95.0, preset="normal")
        ys = [pt[1] for pt in result]
        assert min(ys) >= 30.0, "text must not suppress or hijack the spectrum"
        assert max(ys) < 95.0
        assert (max(ys) - min(ys)) > 8.0, "envelope must follow a real flow profile, not a flat text band"

    def test_flow_separated_from_baseline_by_dark_gap_is_traced(self):
        """A dark zero-velocity window can separate the real flow from the
        baseline. If only a thin speckle line touches the baseline while the
        actual flow is a large disconnected blob, the flow must be traced
        (real DICOMs show this, e.g. auto-gain darkness below the flow)."""
        h, w = 100, 120
        gray = np.zeros((h, w), dtype=np.uint8)
        baseline = 80
        gray[20:60, 10:110] = 200  # real flow, top edge at row 20
        gray[79, 10:110] = 200  # speckle line exactly on the baseline row
        result = extract_doppler_envelope(gray, _roi(w=w, h=h), baseline_y_px=float(baseline))
        assert len(result) >= 2
        ys = [pt[1] for pt in result]
        assert abs(float(np.median(ys)) - 20.5) < 3.0, "must trace the flow, not the baseline speckle"


def _below_baseline_spectrum(height=100, width=160, baseline=40):
    """Bright spectral flow whose bottom edge sits at *edge_row* (below baseline)."""
    gray = np.zeros((height, width), dtype=np.uint8)
    for col in range(15, width - 15):
        bottom = int(60 + 30 * abs(col - width // 2) / (width // 2))
        gray[baseline:bottom, col] = 200
    return gray


class TestExtractDopplerEnvelopeBelowBaseline:
    """extract_doppler_envelope must auto-detect and trace below-baseline flow."""

    def test_traces_below_baseline(self):
        gray = _below_baseline_spectrum()
        result = extract_doppler_envelope(gray, _roi(w=160, h=100), baseline_y_px=40.0)
        assert len(result) >= 2
        assert all(pt[1] > 40.0 for pt in result), "envelope must sit below the baseline"

    def test_envelope_follows_bottom_edge(self):
        gray = _below_baseline_spectrum()
        result = extract_doppler_envelope(gray, _roi(w=160, h=100), baseline_y_px=40.0)
        ys = [pt[1] for pt in result]
        assert abs(float(np.median(ys)) - 71.0) < 4.0

    def test_empty_side_is_not_traced(self):
        gray = np.zeros((100, 160), dtype=np.uint8)
        assert extract_doppler_envelope(gray, _roi(w=160, h=100), baseline_y_px=40.0) == ()

    def test_prefers_stronger_side(self):
        """When flow is below baseline, the below envelope wins even if the
        above half has faint speckle."""
        h, w = 100, 160
        gray = _below_baseline_spectrum(height=h, width=w, baseline=40)
        rng = np.random.default_rng(3)
        gray[:40, :] = rng.integers(0, 20, size=(40, w), dtype=np.uint8)
        result = extract_doppler_envelope(gray, _roi(w=w, h=h), baseline_y_px=40.0)
        assert len(result) >= 2
        assert all(pt[1] > 40.0 for pt in result), "below flow must win over faint speckle above"
