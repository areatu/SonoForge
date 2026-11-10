"""Behavioral unit tests for unified Doppler ROI validation (issue 483)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.roi_validator import (
    RoiValidationResult,
    validate_doppler_roi,
)


def _frame_with_grid_lines(height: int = 600, width: int = 800, *, draw_grid: bool = True) -> np.ndarray:
    """Build a synthetic ultrasound frame with optional horizontal velocity grid lines in the lower half."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    if draw_grid:
        for y in (360, 410, 460, 510, 560):
            # Dashed/solid horizontal scale line spanning the spectrogram band
            frame[y, 20 : width - 20] = (95, 95, 95)
        # Brighter baseline
        frame[460, 10 : width - 10] = (180, 180, 180)
    return frame


class TestValidateDopplerRoi:
    def test_valid_lower_half_spectrogram_with_grid_lines_passes(self) -> None:
        frame = _frame_with_grid_lines(600, 800, draw_grid=True)
        roi = DopplerSpectrogramRoi(x0=0, y0=320, width=780, height=260)

        result = validate_doppler_roi(roi, frame)

        assert isinstance(result, RoiValidationResult)
        assert result.valid is True
        assert result.reason == "ok"
        assert result.grid_line_count >= 1

    def test_rejects_narrow_roi_below_min_width_fraction(self) -> None:
        frame = _frame_with_grid_lines(600, 800)
        roi = DopplerSpectrogramRoi(x0=0, y0=320, width=500, height=240)

        result = validate_doppler_roi(roi, frame)

        assert result.valid is False
        assert "width" in result.reason

    def test_rejects_too_short_and_too_tall_roi(self) -> None:
        frame = _frame_with_grid_lines(600, 800)
        too_short = DopplerSpectrogramRoi(x0=0, y0=420, width=760, height=100)
        too_tall = DopplerSpectrogramRoi(x0=0, y0=100, width=760, height=480)

        short_res = validate_doppler_roi(too_short, frame)
        tall_res = validate_doppler_roi(too_tall, frame, require_lower_half=False)

        assert short_res.valid is False
        assert "height" in short_res.reason and "<" in short_res.reason
        assert tall_res.valid is False
        assert "height" in tall_res.reason and ">" in tall_res.reason

    def test_rejects_upper_half_roi_unless_require_lower_half_disabled(self) -> None:
        frame = _frame_with_grid_lines(600, 800, draw_grid=False)
        upper_roi = DopplerSpectrogramRoi(x0=0, y0=120, width=760, height=240)

        strict = validate_doppler_roi(upper_roi, frame, check_grid_lines=False)
        relaxed = validate_doppler_roi(
            upper_roi,
            frame,
            require_lower_half=False,
            check_grid_lines=False,
        )

        assert strict.valid is False
        assert "upper half" in strict.reason
        assert relaxed.valid is True
        assert relaxed.reason == "ok"

    def test_rejects_negative_origin_and_out_of_frame_bounds(self) -> None:
        frame = _frame_with_grid_lines(600, 800, draw_grid=False)
        neg_roi = DopplerSpectrogramRoi(x0=-4, y0=320, width=760, height=220)
        overflow_roi = DopplerSpectrogramRoi(x0=60, y0=320, width=760, height=220)

        neg_res = validate_doppler_roi(neg_roi, frame, check_grid_lines=False)
        over_res = validate_doppler_roi(overflow_roi, frame, check_grid_lines=False)

        assert neg_res.valid is False
        assert "negative" in neg_res.reason
        assert over_res.valid is False
        assert "extends beyond frame bounds" in over_res.reason

    def test_rejects_bmode_region_without_grid_lines_unless_disabled(self) -> None:
        blank_frame = _frame_with_grid_lines(600, 800, draw_grid=False)
        roi = DopplerSpectrogramRoi(x0=0, y0=320, width=760, height=240)

        with_grid_check = validate_doppler_roi(roi, blank_frame, check_grid_lines=True)
        without_grid_check = validate_doppler_roi(roi, blank_frame, check_grid_lines=False)

        assert with_grid_check.valid is False
        assert with_grid_check.grid_line_count == 0
        assert "no velocity grid lines" in with_grid_check.reason
        assert without_grid_check.valid is True
        assert without_grid_check.grid_line_count == 0
