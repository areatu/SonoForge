"""Regression tests for M-mode measurements and calibration."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.models.frame_panels import (
    MmodeCalibrationState,
    PanelKind,
    UltrasoundPanel,
)
from echo_personal_tool.domain.services.mmode_calibration import mmode_state_from_panel
from echo_personal_tool.domain.services.mmode_extractor import extract_mmode_column


class TestMModeCalibrationRegression:
    """M-mode calibration produces exact expected states."""

    def _make_panel(
        self,
        kind: PanelKind = PanelKind.M_MODE,
        dy: float = 0.1,
        dx: float = 10.0,
        units_y: int = 3,
        units_x: int = 4,
    ) -> UltrasoundPanel:
        return UltrasoundPanel(
            kind=kind,
            bounds=DopplerSpectrogramRoi(x0=100.0, y0=50.0, width=300.0, height=200.0),
            physical_delta_y=dy,
            physical_delta_x=dx,
            physical_units_y=units_y,
            physical_units_x=units_x,
        )

    def test_mmode_state_from_mmode_panel(self) -> None:
        panel = self._make_panel(kind=PanelKind.M_MODE, dy=0.08, units_y=3)
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.vertical_mm_per_pixel > 0.0
        assert state.is_complete() is True

    def test_mmode_state_rejects_bmode(self) -> None:
        panel = self._make_panel(kind=PanelKind.B_MODE)
        assert mmode_state_from_panel(panel) is None

    def test_mmode_state_rejects_zero_vertical(self) -> None:
        panel = self._make_panel(kind=PanelKind.M_MODE, dy=0.0, units_y=3)
        state = mmode_state_from_panel(panel)
        assert state is None

    def test_mmode_state_absorbs_negative_vertical(self) -> None:
        """physical_delta_y is abs()-ed internally, so negative values still produce valid state."""
        panel = self._make_panel(kind=PanelKind.M_MODE, dy=-0.1, units_y=3)
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.vertical_mm_per_pixel > 0.0

    def test_mmode_state_no_physical_delta(self) -> None:
        panel = UltrasoundPanel(
            kind=PanelKind.M_MODE,
            bounds=DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=100.0, height=100.0),
        )
        state = mmode_state_from_panel(panel)
        assert state is None

    def test_mmode_calibration_roi_bounds(self) -> None:
        panel = self._make_panel(kind=PanelKind.M_MODE, dy=0.1, units_y=3)
        state = mmode_state_from_panel(panel)
        assert state is not None
        assert state.roi.x0 == pytest.approx(100.0)
        assert state.roi.y0 == pytest.approx(50.0)
        assert state.roi.width == pytest.approx(300.0)
        assert state.roi.height == pytest.approx(200.0)


class TestMModeExtractorRegression:
    """M-mode column extraction from frames produces expected results."""

    def test_extract_horizontal_line(self) -> None:
        frame = np.zeros((100, 200), dtype=np.uint8)
        frame[50, :] = 255  # Bright horizontal line
        result = extract_mmode_column(frame, (10.0, 50.0), (190.0, 50.0), num_samples=100)
        assert len(result) == 100
        assert np.all(result == 255)

    def test_extract_vertical_line(self) -> None:
        frame = np.zeros((100, 200), dtype=np.uint8)
        frame[:, 50] = 128  # Bright vertical line
        result = extract_mmode_column(frame, (50.0, 0.0), (50.0, 99.0), num_samples=50)
        assert len(result) == 50
        assert np.all(result == 128)

    def test_extract_gradient(self) -> None:
        frame = np.zeros((100, 200), dtype=np.uint8)
        for x in range(200):
            frame[:, x] = min(x, 255)
        result = extract_mmode_column(frame, (0.0, 50.0), (199.0, 50.0), num_samples=200)
        assert len(result) == 200
        # Values should be increasing
        assert result[-1] > result[0]

    def test_extract_rgb_frame(self) -> None:
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[50, :] = 200
        result = extract_mmode_column(frame, (10.0, 50.0), (190.0, 50.0), num_samples=50)
        assert len(result) == 50
        assert result.dtype == np.uint8

    def test_extract_single_sample(self) -> None:
        frame = np.zeros((100, 200), dtype=np.uint8)
        frame[50, 100] = 42
        result = extract_mmode_column(frame, (100.0, 50.0), (100.0, 50.0), num_samples=1)
        assert len(result) == 1

    def test_extract_default_samples(self) -> None:
        frame = np.zeros((100, 200), dtype=np.uint8)
        result = extract_mmode_column(frame, (0.0, 50.0), (199.0, 50.0))
        assert len(result) == 256


class TestMModeCalibrationStateRegression:
    """MmodeCalibrationState properties produce exact results."""

    def test_is_complete(self) -> None:
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=300, height=200),
            vertical_mm_per_pixel=0.1,
        )
        assert state.is_complete() is True

    def test_is_incomplete_zero_width(self) -> None:
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=0, height=200),
            vertical_mm_per_pixel=0.1,
        )
        assert state.is_complete() is False

    def test_is_incomplete_zero_height(self) -> None:
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=300, height=0),
            vertical_mm_per_pixel=0.1,
        )
        assert state.is_complete() is False

    def test_is_incomplete_zero_depth(self) -> None:
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=300, height=200),
            vertical_mm_per_pixel=0.0,
        )
        assert state.is_complete() is False

    def test_with_horizontal_ms_per_pixel(self) -> None:
        state = MmodeCalibrationState(
            roi=DopplerSpectrogramRoi(x0=0, y0=0, width=300, height=200),
            vertical_mm_per_pixel=0.1,
            horizontal_ms_per_pixel=5.0,
        )
        assert state.horizontal_ms_per_pixel == pytest.approx(5.0)
        assert state.is_complete() is True
