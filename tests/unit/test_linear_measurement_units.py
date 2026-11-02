"""Tests for linear measurement display units."""

from __future__ import annotations

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement, format_length_mm


def test_format_length_mm_and_cm() -> None:
    assert format_length_mm(12.3, "mm") == "12 mm"
    assert format_length_mm(12.3, "cm") == "1.2 cm"


def test_linear_measurement_display_text_cm() -> None:
    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=100.0,
        millimeter_length=45.6,
    )
    assert measurement.display_text(length_unit="cm") == "КДР ЛЖ: 4.6 cm"
