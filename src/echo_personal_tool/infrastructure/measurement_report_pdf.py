"""Export measurement report text to PDF."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from echo_personal_tool.resources.bundled_fonts import report_cyrillic_font_path


class PdfExportError(RuntimeError):
    """Raised when PDF export cannot be completed."""


def export_measurement_report_pdf(
    text: str,
    output_path: Path,
    *,
    font_size: int = 10,
) -> Path:
    """Write report text to a PDF file and return the path."""
    font_name = _register_cyrillic_font(pdfmetrics, TTFont)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    page_width, page_height = A4
    margin_x = 18 * mm
    margin_y = 18 * mm
    line_height = 5 * mm
    font_size = max(8, min(16, int(font_size)))

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    pdf.setTitle("Результаты измерений")
    pdf.setFont(font_name, font_size)

    y = page_height - margin_y
    for raw_line in text.splitlines():
        line = raw_line or " "
        if y < margin_y:
            pdf.showPage()
            pdf.setFont(font_name, font_size)
            y = page_height - margin_y
        pdf.drawString(margin_x, y, line)
        y -= line_height

    pdf.save()
    return output_path


def _register_cyrillic_font(pdfmetrics: object, TTFont: object) -> str:
    font_path = report_cyrillic_font_path()
    pdfmetrics.registerFont(TTFont("ReportCyrillic", str(font_path)))
    return "ReportCyrillic"
