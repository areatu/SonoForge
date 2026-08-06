"""Tests for measurement_report_pdf export."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_MOCK_A4 = (595.27, 841.89)
_MM = 2.8346  # reportlab mm in points
_MOCK_MM = 2.8346
_FAKE_FONT = Path("/fake/font.ttf")


def _patch_pdf_deps(tmp_path: Path, lines: str = "Hello\nWorld", **kwargs):
    """Helper: patch all reportlab deps and return (mock_canvas, output_path)."""
    output = tmp_path / "report.pdf"
    fake_font = _FAKE_FONT
    patches = {
        "canvas": patch("echo_personal_tool.infrastructure.measurement_report_pdf.canvas"),
        "pdfmetrics": patch("echo_personal_tool.infrastructure.measurement_report_pdf.pdfmetrics"),
        "TTFont": patch("echo_personal_tool.infrastructure.measurement_report_pdf.TTFont"),
        "A4": patch("echo_personal_tool.infrastructure.measurement_report_pdf.A4", _MOCK_A4),
        "mm": patch("echo_personal_tool.infrastructure.measurement_report_pdf.mm", _MOCK_MM),
        "font_path": patch(
            "echo_personal_tool.infrastructure.measurement_report_pdf.report_cyrillic_font_path",
            return_value=fake_font,
        ),
    }
    mocks = {k: p.start() for k, p in patches.items()}
    mock_c = MagicMock()
    mocks["canvas"].Canvas.return_value = mock_c
    return mock_c, mocks, output, patches


class TestExportMeasurementReportPdf:
    def test_basic_export(self, tmp_path: Path) -> None:
        mock_c, mocks, output, patches = _patch_pdf_deps(tmp_path, "Hello\nWorld")
        try:
            from echo_personal_tool.infrastructure.measurement_report_pdf import (
                export_measurement_report_pdf,
            )

            result = export_measurement_report_pdf("Hello\nWorld", output)
            assert result == output
            mocks["pdfmetrics"].registerFont.assert_called_once()
            mocks["TTFont"].assert_called_once_with("ReportCyrillic", str(_FAKE_FONT))
            mock_c.setFont.assert_called_with("ReportCyrillic", 10)
            mock_c.save.assert_called_once()
            # drawString was called once per line
            assert mock_c.drawString.call_count == 2
            # First call: "Hello" at correct position
            first_call = mock_c.drawString.call_args_list[0]
            assert first_call[0][2] == "Hello"
            # Second call: "World" one line_height lower
            second_call = mock_c.drawString.call_args_list[1]
            assert second_call[0][2] == "World"
            # y positions should differ by line_height (5 * mm)
            assert first_call[0][1] - second_call[0][1] == pytest.approx(5 * _MOCK_MM)
        finally:
            for p in patches.values():
                p.stop()

    def test_empty_line_replaced_with_space(self, tmp_path: Path) -> None:
        mock_c, mocks, output, patches = _patch_pdf_deps(tmp_path)
        try:
            from echo_personal_tool.infrastructure.measurement_report_pdf import (
                export_measurement_report_pdf,
            )

            export_measurement_report_pdf("line1\n\nline3", output)
            calls = mock_c.drawString.call_args_list
            assert calls[1][0][2] == " "  # second line is empty → " "
        finally:
            for p in patches.values():
                p.stop()

    def test_font_size_clamped_min(self, tmp_path: Path) -> None:
        mock_c, mocks, output, patches = _patch_pdf_deps(tmp_path)
        try:
            from echo_personal_tool.infrastructure.measurement_report_pdf import (
                export_measurement_report_pdf,
            )

            export_measurement_report_pdf("text", output, font_size=2)
            mock_c.setFont.assert_called_with("ReportCyrillic", 8)  # clamped to 8
        finally:
            for p in patches.values():
                p.stop()

    def test_font_size_clamped_max(self, tmp_path: Path) -> None:
        mock_c, mocks, output, patches = _patch_pdf_deps(tmp_path)
        try:
            from echo_personal_tool.infrastructure.measurement_report_pdf import (
                export_measurement_report_pdf,
            )

            export_measurement_report_pdf("text", output, font_size=99)
            mock_c.setFont.assert_called_with("ReportCyrillic", 16)  # clamped to 16
        finally:
            for p in patches.values():
                p.stop()

    def test_page_break(self, tmp_path: Path) -> None:
        """When y goes below margin, a new page is started."""
        mock_c, mocks, output, patches = _patch_pdf_deps(tmp_path)
        try:
            from echo_personal_tool.infrastructure.measurement_report_pdf import (
                export_measurement_report_pdf,
            )

            # A4: 841.89pt. margin_y=18mm≈51.02pt, line_height=5mm≈14.17pt
            # Lines per page: (841.89 - 51.02) / 14.17 ≈ 56 lines
            lines = "\n".join([f"line{i}" for i in range(60)])
            export_measurement_report_pdf(lines, output, font_size=10)
            mock_c.showPage.assert_called()
        finally:
            for p in patches.values():
                p.stop()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        output = tmp_path / "subdir" / "deep" / "report.pdf"
        mock_c, mocks, _, patches = _patch_pdf_deps(tmp_path)
        try:
            from echo_personal_tool.infrastructure.measurement_report_pdf import (
                export_measurement_report_pdf,
            )

            # Use the actual output path
            result = export_measurement_report_pdf("text", output)
            assert result == output
            assert output.parent.exists()
        finally:
            for p in patches.values():
                p.stop()

    def test_pdf_export_error_class_exists(self) -> None:
        from echo_personal_tool.infrastructure.measurement_report_pdf import PdfExportError

        assert issubclass(PdfExportError, RuntimeError)

    def test_register_cyrillic_font(self) -> None:
        from echo_personal_tool.infrastructure.measurement_report_pdf import (
            _register_cyrillic_font,
        )

        mock_pm = MagicMock()
        mock_tf = MagicMock()
        fake_font = _FAKE_FONT
        with patch(
            "echo_personal_tool.infrastructure.measurement_report_pdf.report_cyrillic_font_path",
            return_value=fake_font,
        ):
            result = _register_cyrillic_font(mock_pm, mock_tf)
            assert result == "ReportCyrillic"
            mock_pm.registerFont.assert_called_once()
            mock_tf.assert_called_once_with("ReportCyrillic", str(fake_font))

    def test_set_title(self, tmp_path: Path) -> None:
        mock_c, mocks, output, patches = _patch_pdf_deps(tmp_path)
        try:
            from echo_personal_tool.infrastructure.measurement_report_pdf import (
                export_measurement_report_pdf,
            )

            export_measurement_report_pdf("title test", output)
            mock_c.setTitle.assert_called_once_with("Результаты измерений")
        finally:
            for p in patches.values():
                p.stop()

    def test_string_font_set_before_each_page(self, tmp_path: Path) -> None:
        """After page break, setFont should be called again."""
        mock_c, mocks, output, patches = _patch_pdf_deps(tmp_path)
        try:
            from echo_personal_tool.infrastructure.measurement_report_pdf import (
                export_measurement_report_pdf,
            )

            lines = "\n".join([f"L{i}" for i in range(60)])
            export_measurement_report_pdf(lines, output, font_size=10)
            # setFont called at least twice (initial + after page break)
            assert mock_c.setFont.call_count >= 2
        finally:
            for p in patches.values():
                p.stop()
