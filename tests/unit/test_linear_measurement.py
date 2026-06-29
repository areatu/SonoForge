"""Unit tests for linear measurement helpers."""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import (
    LinearMeasurement,
    inline_caliper_text,
    pixel_to_mm_length,
)


def test_display_text_omits_pixels_when_calibrated() -> None:
    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=100.0,
        millimeter_length=50.0,
    )
    assert measurement.display_text() == "КДР ЛЖ: 50.0 mm"


def test_display_text_shows_pixels_when_uncalibrated() -> None:
    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=100.0,
        millimeter_length=None,
    )
    assert measurement.display_text() == "КДР ЛЖ: 100.0 px"
    assert pixel_to_mm_length(10.0, 0.0, (0.5, 0.25)) == 2.5
    assert pixel_to_mm_length(10.0, 90.0, (0.5, 0.25)) == 5.0


def test_inline_caliper_text_mm() -> None:
    m = LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=35.5)
    assert inline_caliper_text(m, length_unit="mm") == "LVEDD 35.5 mm"


def test_inline_caliper_text_cm() -> None:
    m = LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=35.5)
    assert inline_caliper_text(m, length_unit="cm") == "LVEDD 3.55 cm"


def test_inline_caliper_text_px() -> None:
    m = LinearMeasurement(label="Dist1", pixel_length=42.0, millimeter_length=None)
    assert inline_caliper_text(m) == "Dist1 42.0 px"


def test_inline_caliper_text_raw_label() -> None:
    m = LinearMeasurement(label="IVSd", pixel_length=50.0, millimeter_length=8.0)
    result = inline_caliper_text(m)
    assert result == "IVSd 8.0 mm"
    assert "МЖП" not in result

