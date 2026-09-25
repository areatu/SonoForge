"""Unit tests for linear measurement model."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.linear_measurement import (
    PERCENT_LABELS,
    LinearMeasurement,
    format_length_mm,
    format_velocity_cm_s,
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

    @pytest.mark.parametrize("label", ["%D", "%S"])
    def test_percent_labels_use_percent_unit(self, label: str) -> None:
        m = LinearMeasurement(label=label, pixel_length=0, millimeter_length=45.0)
        text = m.display_text()
        assert "45.0%" in text
        assert "mm" not in text
        assert "стеноз" not in text


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


class TestPercentLabels:
    """A percentage stored in ``millimeter_length`` must never render as a length."""

    @pytest.mark.parametrize("label", sorted(PERCENT_LABELS))
    def test_percent_labels_render_as_percent(self, label: str) -> None:
        m = LinearMeasurement(label=label, pixel_length=0.0, millimeter_length=80.0)
        text = m.display_text()
        assert "80.0%" in text
        assert "mm" not in text
        assert "cm" not in text

    @pytest.mark.parametrize("label", sorted(PERCENT_LABELS))
    def test_percent_ignores_length_unit(self, label: str) -> None:
        m = LinearMeasurement(label=label, pixel_length=0.0, millimeter_length=80.0)
        assert m.display_text(length_unit="cm") == m.display_text(length_unit="mm")

    def test_length_label_still_renders_mm(self) -> None:
        m = LinearMeasurement(label="LVEDD", pixel_length=0.0, millimeter_length=55.0)
        assert "55.0 mm" in m.display_text()


class TestDopplerCaliperMeasurement:
    """Doppler-zone caliper: Δt (ms) + velocity amplitude (cm/s or m/s)."""

    def test_display_text_time_and_velocity(self) -> None:
        m = LinearMeasurement(
            label="Dist1",
            pixel_length=22.4,
            millimeter_length=None,
            time_ms=105.0,
            velocity_cm_s=87.3,
            doppler=True,
        )
        text = m.display_text()
        assert "105.0 ms" in text
        assert "87.3 cm/s" in text
        assert "mm" not in text
        # Doppler Δt must not render the M-mode HR line.
        assert "ЧСС" not in text and "HR" not in text

    def test_display_text_switches_to_m_per_s(self) -> None:
        m = LinearMeasurement(
            label="Dist2",
            pixel_length=0.0,
            millimeter_length=None,
            time_ms=90.0,
            velocity_cm_s=350.0,
            doppler=True,
        )
        assert "3.50 m/s" in m.display_text()

    def test_display_text_time_only(self) -> None:
        m = LinearMeasurement(
            label="Dist1",
            pixel_length=0.0,
            millimeter_length=None,
            time_ms=150.0,
            doppler=True,
        )
        text = m.display_text()
        assert "150.0 ms" in text
        assert "ЧСС" not in text and "HR" not in text

    def test_display_text_velocity_only(self) -> None:
        m = LinearMeasurement(
            label="Dist1",
            pixel_length=0.0,
            millimeter_length=None,
            velocity_cm_s=-45.0,
            doppler=True,
        )
        assert "-45.0 cm/s" in m.display_text()

    def test_inline_text(self) -> None:
        m = LinearMeasurement(
            label="Dist1",
            pixel_length=0.0,
            millimeter_length=None,
            time_ms=105.0,
            velocity_cm_s=87.3,
            doppler=True,
        )
        text = inline_caliper_text(m)
        assert text == "Dist1 105.0 ms 87.3 cm/s"

    def test_format_velocity_units(self) -> None:
        assert format_velocity_cm_s(99.9) == "99.9 cm/s"
        assert format_velocity_cm_s(100.0) == "1.00 m/s"
        assert format_velocity_cm_s(-250.0) == "-2.50 m/s"

    def test_mmode_time_caliper_still_shows_hr(self) -> None:
        """Non-Doppler time calipers keep the legacy HR display."""
        m = LinearMeasurement(label="Time", pixel_length=100.0, millimeter_length=None, time_ms=800.0)
        text = m.display_text()
        assert "800.0 ms" in text
        assert ("ЧСС" in text) or ("HR" in text)
