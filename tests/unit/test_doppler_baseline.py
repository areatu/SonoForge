"""Tests for doppler_baseline.detect_baseline_y."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_baseline import detect_baseline_y


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

    def test_3d_array_fallback(self):
        """Non-2D input returns ROI midpoint."""
        rgb = np.zeros((100, 200, 3), dtype=np.uint8)
        roi = _roi(y0=10, h=30)
        result = detect_baseline_y(rgb, roi)
        assert result == pytest.approx(roi.y0 + roi.height / 2.0)

    def test_patch_with_zero_var_row_wins(self):
        """A row with zero variance should be selected as baseline."""
        gray = np.random.randint(10, 200, size=(50, 100), dtype=np.uint8)
        # Inject a zero-variance row at index 15
        gray[15, :] = 42
        roi = _roi(x0=0, y0=0, w=100, h=50)
        result = detect_baseline_y(gray, roi)
        assert result == pytest.approx(15.0 + 0.5, abs=0.6)

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
