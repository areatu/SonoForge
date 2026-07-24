"""Unit tests for doppler_baseline.detect_baseline_y."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_baseline import detect_baseline_y


def _roi(x0: float = 0.0, y0: float = 0.0, w: float = 100.0, h: float = 50.0) -> DopplerSpectrogramRoi:
    return DopplerSpectrogramRoi(x0=x0, y0=y0, width=w, height=h)


class TestDetectBaselineY:
    def test_3d_image_returns_midpoint(self) -> None:
        rgb = np.zeros((100, 200, 3), dtype=np.uint8)
        roi = _roi(w=100.0, h=50.0)
        result = detect_baseline_y(rgb, roi)
        assert result == roi.y0 + roi.height / 2.0

    def test_roi_beyond_image_clamped(self) -> None:
        img = np.zeros((10, 10), dtype=np.uint8)
        roi = _roi(x0=50.0, y0=50.0, w=10.0, h=10.0)
        result = detect_baseline_y(img, roi)
        # Clamped to bottom-right pixel; still returns valid float
        assert isinstance(result, float)
        assert 0.0 <= result <= 10.0

    def test_uniform_image_any_row(self) -> None:
        img = np.full((50, 100), 128, dtype=np.uint8)
        roi = _roi(w=100.0, h=50.0)
        result = detect_baseline_y(img, roi)
        # All rows have variance 0; argmin picks first (index 0)
        assert result == 0.5

    def test_baseline_at_low_variance_row(self) -> None:
        # Create image where row 20 has very low variance (quiet band)
        img = np.random.randint(0, 255, (50, 100), dtype=np.uint8)
        img[20, :] = 128  # constant row → zero variance
        roi = _roi(w=100.0, h=50.0)
        result = detect_baseline_y(img, roi)
        # Should detect row 20 → y = 20 + 0.5 = 20.5
        assert abs(result - 20.5) < 0.01

    def test_roi_clamped_to_image_bounds(self) -> None:
        img = np.zeros((30, 60), dtype=np.uint8)
        img[15, :] = 128
        roi = _roi(x0=10.0, y0=5.0, w=100.0, h=100.0)  # extends beyond image
        result = detect_baseline_y(img, roi)
        # ROI gets clamped; row 15 should still be detectable if within clamped range
        assert isinstance(result, float)

    def test_result_offset_by_half_pixel(self) -> None:
        img = np.zeros((20, 40), dtype=np.uint8)
        img[10, :] = 128
        roi = _roi(w=40.0, h=20.0)
        result = detect_baseline_y(img, roi)
        # Result should be at integer row + 0.5
        assert result == int(result) + 0.5

    def test_narrow_roi(self) -> None:
        img = np.zeros((20, 40), dtype=np.uint8)
        img[5:15, 10:20] = 255
        roi = _roi(x0=10.0, y0=5.0, w=10.0, h=10.0)
        result = detect_baseline_y(img, roi)
        assert 5.0 <= result <= 15.0
