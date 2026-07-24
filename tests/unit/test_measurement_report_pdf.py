"""Unit tests for measurement_report_pdf."""

from __future__ import annotations

from unittest.mock import patch

from echo_personal_tool.infrastructure.measurement_report_pdf import (
    PdfExportError,
    export_measurement_report_pdf,
)


def _mock_register(*args, **kwargs) -> str:
    return "Helvetica"


class TestExportMeasurementReportPdf:
    def test_creates_pdf(self, tmp_path) -> None:
        output = tmp_path / "report.pdf"
        with patch(
            "echo_personal_tool.infrastructure.measurement_report_pdf._register_cyrillic_font",
            side_effect=_mock_register,
        ):
            result = export_measurement_report_pdf("Hello\nWorld", output)
        assert result == output
        assert output.exists()
        assert output.stat().st_size > 0

    def test_empty_text(self, tmp_path) -> None:
        output = tmp_path / "empty.pdf"
        with patch(
            "echo_personal_tool.infrastructure.measurement_report_pdf._register_cyrillic_font",
            side_effect=_mock_register,
        ):
            export_measurement_report_pdf("", output)
        assert output.exists()

    def test_creates_parent_dirs(self, tmp_path) -> None:
        output = tmp_path / "subdir" / "report.pdf"
        with patch(
            "echo_personal_tool.infrastructure.measurement_report_pdf._register_cyrillic_font",
            side_effect=_mock_register,
        ):
            export_measurement_report_pdf("test", output)
        assert output.exists()

    def test_long_text_no_crash(self, tmp_path) -> None:
        output = tmp_path / "long.pdf"
        text = "\n".join([f"Line {i}" for i in range(200)])
        with patch(
            "echo_personal_tool.infrastructure.measurement_report_pdf._register_cyrillic_font",
            side_effect=_mock_register,
        ):
            export_measurement_report_pdf(text, output)
        assert output.exists()

    def test_font_size_clamped(self, tmp_path) -> None:
        output = tmp_path / "clamp.pdf"
        with patch(
            "echo_personal_tool.infrastructure.measurement_report_pdf._register_cyrillic_font",
            side_effect=_mock_register,
        ):
            export_measurement_report_pdf("test", output, font_size=100)
        assert output.exists()

    def test_pdf_export_error_is_exception(self) -> None:
        assert issubclass(PdfExportError, RuntimeError)
