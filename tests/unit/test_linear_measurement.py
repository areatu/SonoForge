"""Unit tests for linear measurement helpers."""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import (
    LinearMeasurement,
    pixel_to_mm_length,
)


def test_display_text_omits_pixels_when_calibrated() -> None:
    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=100.0,
        millimeter_length=50.0,
    )
    assert measurement.display_text() == "LVEDD: 50.0 mm"


def test_display_text_shows_pixels_when_uncalibrated() -> None:
    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=100.0,
        millimeter_length=None,
    )
    assert measurement.display_text() == "LVEDD: 100.0 px"
    assert pixel_to_mm_length(10.0, 0.0, (0.5, 0.25)) == 2.5
    assert pixel_to_mm_length(10.0, 90.0, (0.5, 0.25)) == 5.0

