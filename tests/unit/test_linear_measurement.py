"""Unit tests for linear measurement model."""

from __future__ import annotations

import math

import pytest

from echo_personal_tool.domain.models.linear_measurement import (
    LinearMeasurement,
    format_length_mm,
    inline_caliper_text,
    pixel_to_mm_length,
)


class TestFormatLengthMm:
    def test_mm_unit(self) -> None:
        assert format_length_mm(9.5, "mm") == "9.5 mm"

    def test_cm_unit(self) -> None:
        assert format_length_mm(25.0, "cm") == "2.50 cm"


class TestInlineCaliperText:
    def test_with_mm(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=9.5)
        result = inline_caliper_text(m)
        assert "IVSd" in result
        assert "9.5" in result

    def test_px_only(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=None)
        result = inline_caliper_text(m)
        assert "px" in result

    def test_cm_unit(self) -> None:
        m = LinearMeasurement(label="LA", pixel_length=20, millimeter_length=25.0)
        result = inline_caliper_text(m, length_unit="cm")
        assert "2.50" in result


class TestLinearMeasurementDisplayText:
    def test_with_i18n_label(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=9.5)
        text = m.display_text()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_without_i18n_label(self) -> None:
        m = LinearMeasurement(label="CustomLabel", pixel_length=10, millimeter_length=9.5)
        text = m.display_text()
        assert "CustomLabel" in text

    def test_px_only(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=None)
        text = m.display_text()
        assert "px" in text

    def test_cm_unit(self) -> None:
        m = LinearMeasurement(label="IVSd", pixel_length=10, millimeter_length=25.0)
        text = m.display_text(length_unit="cm")
        assert "2.50" in text


class TestPixelToMmLength:
    def test_horizontal_line(self) -> None:
        # 10 pixels horizontal, spacing 0.5 mm/px → 5 mm
        result = pixel_to_mm_length(10.0, 0.0, (0.5, 0.5))
        assert result == pytest.approx(5.0)

    def test_vertical_line(self) -> None:
        result = pixel_to_mm_length(10.0, 90.0, (0.5, 0.5))
        assert result == pytest.approx(5.0)

    def test_diagonal_line(self) -> None:
        # 45 degree, equal spacing
        result = pixel_to_mm_length(10.0, 45.0, (1.0, 1.0))
        assert result == pytest.approx(10.0)

    def test_non_square_spacing(self) -> None:
        # 10 pixels at 0 degrees → column spacing only
        result = pixel_to_mm_length(10.0, 0.0, (0.5, 1.0))
        assert result == pytest.approx(10.0)
