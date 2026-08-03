"""Tests for doppler_baseline.detect_baseline_y."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_baseline import (
    detect_baseline_line_y,
    detect_baseline_y,
)


def _roi(x0=10, y0=20, w=80, h=40):
    return DopplerSpectrogramRoi(x0=x0, y0=y0, width=w, height=h)


class TestDetectBaselineY:
    """detect_baseline_y returns plot Y of the quietest horizontal band."""

    def test_returns_float(self):
        gray = np.zeros((100, 200), dtype=np.uint8)
        result = detect_baseline_y(gray, _roi())
        assert isinstance(result, float)

    def test_uniform_image_returns_midpoint(self):
        gray = np.full((100, 200), 128, dtype=np.uint8)
        roi = _roi()
        result = detect_baseline_y(gray, roi)
        assert isinstance(result, float)

    def test_3d_array_converted_to_grayscale(self):
        """3D RGB input is converted via channel mean and baseline detected."""
        gray = np.zeros((100, 200), dtype=np.uint8)
        gray[30:40, :] = 180  # dark band / baseline
        gray[60:90, :] = 120  # signal lobe
        rgb = np.stack([gray, gray, gray], axis=-1)
        roi = _roi(y0=0, h=100)
        result = detect_baseline_y(rgb, roi)
        # Baseline should be found at the dark band, not the ROI midpoint
        assert result != pytest.approx(roi.y0 + roi.height / 2.0)

    def test_dark_band_selected_as_baseline(self):
        """A dark band (baseline) should be selected even among noisy signal."""
        gray = np.random.randint(50, 200, size=(50, 100), dtype=np.uint8)
        # Inject a dark band at rows 14..16
        gray[14:17, :] = 20
        roi = _roi(x0=0, y0=0, w=100, h=50)
        result = detect_baseline_y(gray, roi)
        assert 14.0 <= result <= 16.5

    def test_single_row_patch(self):
        gray = np.array([[10, 20, 30]], dtype=np.uint8)
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=3, height=1)
        result = detect_baseline_y(gray, roi)
        assert isinstance(result, float)

    def test_roi_clamped_to_image_bounds(self):
        """ROI exceeding image bounds should be clamped without error."""
        gray = np.zeros((30, 40), dtype=np.uint8)
        roi = _roi(x0=0, y0=0, w=200, h=200)
        result = detect_baseline_y(gray, roi)
        assert isinstance(result, float)

    def test_roi_negative_coords(self):
        gray = np.zeros((30, 40), dtype=np.uint8)
        roi = _roi(x0=-10, y0=-5, w=50, h=50)
        result = detect_baseline_y(gray, roi)
        assert isinstance(result, float)

    def test_single_column_patch(self):
        gray = np.array([[1], [2], [3], [4], [5]], dtype=np.uint8)
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=1, height=5)
        result = detect_baseline_y(gray, roi)
        assert isinstance(result, float)

    def test_constant_row_selected_over_varying(self):
        """A constant row should have lower variance than a varying one."""
        gray = np.zeros((20, 60), dtype=np.uint8)
        # Row 5 is constant
        gray[5, :] = 100
        # Other rows have random variation
        rng = np.random.RandomState(42)
        for r in range(20):
            if r != 5:
                gray[r, :] = rng.randint(50, 200, size=60)
        roi = _roi(x0=0, y0=0, w=60, h=20)
        result = detect_baseline_y(gray, roi)
        assert result == pytest.approx(5.5, abs=0.6)

    def test_signal_both_sides_no_black_gap(self):
        """Signal above and below baseline with no black zone: baseline = valley."""
        gray = np.zeros((60, 80), dtype=np.uint8)
        # Upper lobe (bright)
        for r in range(5, 25):
            gray[r, :] = 150 + (r % 5) * 10
        # Lower lobe (bright)
        for r in range(35, 55):
            gray[r, :] = 140 + (r % 4) * 10
        # The gap rows 25..35 stay at low intensity (baseline region)
        roi = _roi(x0=0, y0=0, w=80, h=60)
        result = detect_baseline_y(gray, roi)
        assert 25.0 <= result <= 35.0

    def test_signal_only_above_baseline(self):
        """Signal only on one side; baseline sits at the signal edge."""
        gray = np.zeros((60, 80), dtype=np.uint8)
        for r in range(5, 40):
            gray[r, :] = 150 + (r % 5) * 10
        roi = _roi(x0=0, y0=0, w=80, h=60)
        result = detect_baseline_y(gray, roi)
        # Baseline should be near the bottom of the signal band (~row 40)
        assert 30.0 <= result <= 45.0

    def test_dead_zone_at_bottom_not_baseline(self):
        """A pure-black dead zone at ROI bottom must not be chosen as baseline."""
        gray = np.zeros((60, 80), dtype=np.uint8)
        for r in range(5, 40):
            gray[r, :] = 150 + (r % 5) * 10
        # Rows 40..60 are pure black (dead zone)
        roi = _roi(x0=0, y0=0, w=80, h=60)
        result = detect_baseline_y(gray, roi)
        # Baseline is the bottom edge of the signal band (~40), not the dead zone
        assert result <= 45.0


class TestDetectBaselineLineY:
    """detect_baseline_line_y finds a thin horizontal band of one color."""

    def test_returns_none_without_line(self):
        gray = np.zeros((60, 80), dtype=np.uint8)
        assert detect_baseline_line_y(gray, _roi(x0=0, y0=0, w=80, h=60)) is None

    def test_finds_visible_band_at_roi_top_edge(self):
        """A thin orange line right at the ROI top edge must be found."""
        gray = np.zeros((100, 200), dtype=np.uint8)
        rng = np.random.RandomState(7)
        # Multi-color signal lobe below the line (like a real spectrogram)
        for r in range(10, 60):
            gray[r, :] = rng.randint(120, 200, size=200)
        # Orange-ish line at rows 0..1 of the ROI (absolute rows 20..21)
        gray[20:22, :] = 179
        roi = _roi(y0=20, h=60)
        result = detect_baseline_line_y(gray, roi)
        assert result is not None
        assert 20.0 <= result <= 22.0

    def test_is_color_agnostic(self):
        """The line may be any uniform color, not just orange."""
        for color in (200, 90, 40):
            gray = np.full((60, 80), 0, dtype=np.uint8)
            rng = np.random.RandomState(1)
            for r in range(15, 45):
                gray[r, :] = rng.randint(120, 220, size=80)
            gray[30:32, :] = color
            roi = _roi(x0=0, y0=0, w=80, h=60)
            result = detect_baseline_line_y(gray, roi)
            assert result is not None, f"color={color} missed"
            assert 30.0 <= result <= 32.0

    def test_rejects_large_solid_region(self):
        """A thick solid block (not a thin line) must not be reported as a line."""
        gray = np.full((60, 80), 0, dtype=np.uint8)
        gray[10:40, :] = 150
        result = detect_baseline_line_y(gray, _roi(x0=0, y0=0, w=80, h=60))
        assert result is None

    def test_rejects_partial_band(self):
        """A band covering <50% width is not a baseline line."""
        gray = np.zeros((60, 80), dtype=np.uint8)
        gray[30:32, 0:20] = 150
        result = detect_baseline_line_y(gray, _roi(x0=0, y0=0, w=80, h=60))
        assert result is None
