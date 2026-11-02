"""Unit tests for Doppler trace point helpers and baseline detection."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.doppler_baseline import detect_baseline_y
from echo_personal_tool.domain.services.doppler_trace_points import (
    finalize_vti_trace_points,
)


class TestFinalizeVtiTracePoints:
    def test_returns_fewer_than_3_points_unchanged(self) -> None:
        pts = [(10.0, 5.0), (20.0, 8.0)]
        result = finalize_vti_trace_points(pts)
        assert result == ((10.0, 5.0), (20.0, 8.0))

    def test_empty_input(self) -> None:
        assert finalize_vti_trace_points([]) == ()

    def test_sorts_middle_points_by_time(self) -> None:
        pts = [(0.0, 5.0), (30.0, 10.0), (10.0, 8.0), (20.0, 9.0), (40.0, 5.0)]
        result = finalize_vti_trace_points(pts, min_dt_ms=1.0)
        times = [p[0] for p in result]
        assert times == sorted(times)

    def test_filters_close_points_by_min_dt(self) -> None:
        pts = [(0.0, 5.0), (10.0, 8.0), (11.0, 9.0), (12.0, 10.0), (50.0, 5.0)]
        result = finalize_vti_trace_points(pts, min_dt_ms=5.0)
        # Point at 11.0 and 12.0 should be filtered (too close to previous)
        times = [p[0] for p in result]
        assert all(times[i + 1] - times[i] >= 5.0 for i in range(len(times) - 1))

    def test_onset_and_offset_are_preserved(self) -> None:
        pts = [(0.0, 5.0), (10.0, 8.0), (20.0, 9.0), (30.0, 5.0)]
        result = finalize_vti_trace_points(pts, min_dt_ms=1.0)
        assert result[0] == (0.0, 5.0)
        assert result[-1] == (30.0, 5.0)

    def test_duplicate_times_are_filtered(self) -> None:
        pts = [(10.0, 5.0), (10.0, 8.0), (10.0, 9.0), (30.0, 5.0)]
        result = finalize_vti_trace_points(pts, min_dt_ms=1.0)
        times = [p[0] for p in result]
        assert len(times) == len(set(times))


class TestDetectBaselineY:
    def test_returns_first_row_for_uniform_image(self) -> None:
        # Uniform image → all row variances are 0 → argmin returns 0
        roi = DopplerSpectrogramRoi(x0=10, y0=5, width=80, height=40)
        img = np.full((100, 200), 128, dtype=np.uint8)
        result = detect_baseline_y(img, roi)
        assert result == pytest.approx(5.5)  # y0 + 0 + 0.5

    def test_returns_minimum_variance_row(self) -> None:
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=50, height=20)
        img = np.zeros((50, 100), dtype=np.uint8)
        # Row 10 has zero variance (uniform), other rows have noise
        img[10, :] = 128
        for r in range(50):
            if r != 10:
                img[r, :] = np.random.randint(0, 255, 100, dtype=np.uint8)
        result = detect_baseline_y(img, roi)
        assert result == pytest.approx(10.5)

    def test_returns_center_for_3d_input(self) -> None:
        roi = DopplerSpectrogramRoi(x0=0, y0=0, width=50, height=20)
        img_3d = np.zeros((50, 100, 3), dtype=np.uint8)
        result = detect_baseline_y(img_3d, roi)
        assert result == roi.y0 + roi.height / 2.0

    def test_clamps_roi_to_image_bounds(self) -> None:
        roi = DopplerSpectrogramRoi(x0=-10, y0=-5, width=200, height=200)
        img = np.zeros((50, 100), dtype=np.uint8)
        result = detect_baseline_y(img, roi)
        assert isinstance(result, float)
