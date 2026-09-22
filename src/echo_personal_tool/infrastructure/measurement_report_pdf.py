"""Export measurement reports to PDF.

Two exporters live here:

* :func:`export_measurement_report_pdf` — the flat text layout, kept for the
  plain-text reports other windows still produce.
* :func:`export_report_document_pdf` — the structured study protocol: patient
  header, one table per anatomical group, values outside the reference range in
  red, and the physician's conclusion.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from echo_personal_tool.domain.services.report_builder import ReportDocument, ReportGroup, format_sex
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.resources.bundled_fonts import report_cyrillic_font_path

#: Values outside the reference range are printed in this colour.
PATHOLOGY_COLOR = colors.HexColor("#C0392B")
_GROUP_COLOR = colors.HexColor("#34495E")
_GRID_COLOR = colors.HexColor("#B9C2CB")


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
    pdf.setTitle(tr("pdf.report_title"))
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


def export_report_document_pdf(
    document: ReportDocument,
    output_path: Path,
    *,
    font_size: int = 10,
) -> Path:
    """Write the structured study protocol to a PDF file and return the path.

    Layout: patient header block, one table per anatomical group, values outside
    the reference range in red, then the conclusion. Everything reflows onto new
    pages through platypus flowables, so a long study still prints correctly.
    """
    font_name = _register_cyrillic_font(pdfmetrics, TTFont)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    size = max(8, min(16, int(font_size)))
    styles = _report_styles(font_name, size)

    story: list = [Paragraph(_xml_escape(tr("report.title")), styles["title"])]
    story.append(Spacer(1, 4 * mm))
    story.append(_patient_header(document, styles, size))
    story.append(Spacer(1, 5 * mm))

    if not document.has_measurements:
        story.append(Paragraph(_xml_escape(tr("report.no_measurements")), styles["note"]))
    for group in document.groups:
        story.append(Paragraph(_xml_escape(group.title), styles["group"]))
        story.append(_group_table(group, styles, size))
        story.append(Spacer(1, 4 * mm))

    conclusion = (document.patient.conclusion or "").strip()
    if conclusion:
        story.append(Paragraph(_xml_escape(tr("report.conclusion")), styles["group"]))
        story.append(Paragraph(_xml_escape(conclusion).replace("\n", "<br/>"), styles["body"]))

    story.append(Spacer(1, 8 * mm))
    story.append(_signature_block(document, styles))

    pdf = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=tr("report.title"),
    )
    try:
        pdf.build(story)
    except Exception as exc:  # noqa: BLE001 - reportlab raises many shapes
        raise PdfExportError(str(exc)) from exc
    return output_path


def _report_styles(font_name: str, font_size: int) -> dict[str, ParagraphStyle]:
    body = ParagraphStyle(
        "ReportBody",
        fontName=font_name,
        fontSize=font_size,
        leading=font_size * 1.35,
    )
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=body,
            fontSize=font_size + 6,
            leading=(font_size + 6) * 1.3,
            alignment=1,
        ),
        "group": ParagraphStyle(
            "ReportGroup",
            parent=body,
            fontSize=font_size + 1,
            leading=(font_size + 1) * 1.4,
            textColor=_GROUP_COLOR,
            spaceBefore=2,
        ),
        "body": body,
        "note": ParagraphStyle("ReportNote", parent=body, textColor=_GROUP_COLOR),
        "small": ParagraphStyle(
            "ReportSmall",
            parent=body,
            fontSize=font_size - 1,
            leading=(font_size - 1) * 1.3,
        ),
    }


def _patient_rows(document: ReportDocument) -> list[tuple[str, str]]:
    """Filled-in ``(label, value)`` pairs of the header, in print order."""
    patient = document.patient
    rows: list[tuple[str, str]] = []

    def _add(label_key: str, value: str) -> None:
        if (value or "").strip():
            rows.append((tr(label_key), value.strip()))

    _add("report.patient_name", patient.name)
    _add("report.patient_id", patient.patient_id)
    _add("report.sex", format_sex(patient.sex) if patient.sex else "")
    _add("report.birth_date", patient.birth_date)
    _add("report.age", patient.age)
    _add("report.study_date", patient.study_date)
    if patient.height_cm is not None:
        _add("report.height", f"{patient.height_cm:.0f}")
    if patient.weight_kg is not None:
        _add("report.weight", f"{patient.weight_kg:.0f}")
    if patient.bsa_m2 is not None:
        _add("report.bsa", f"{patient.bsa_m2:.2f}")
    _add("report.institution", patient.institution)
    _add("report.equipment", patient.equipment)
    _add("report.physician", patient.physician)
    _add("report.indication", patient.indication)
    return rows


def _patient_header(document: ReportDocument, styles: dict[str, ParagraphStyle], size: int) -> Table:
    rows = _patient_rows(document)
    data: list[list] = []
    # Two label/value pairs per row keeps the header compact on A4.
    for index in range(0, len(rows), 2):
        pair = rows[index : index + 2]
        row: list = []
        for label, value in pair:
            row.append(Paragraph(f"<b>{_xml_escape(label)}:</b> {_xml_escape(value)}", styles["small"]))
        while len(row) < 2:
            row.append(Paragraph("", styles["small"]))
        data.append(row)
    if not data:
        data = [[Paragraph(_xml_escape(tr("report.patient")), styles["small"]), Paragraph("", styles["small"])]]

    width = A4[0] - 36 * mm
    table = Table(data, colWidths=[width * 0.5, width * 0.5])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), styles["small"].fontName),
                ("FONTSIZE", (0, 0), (-1, -1), max(6, size - 1)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LINEBELOW", (0, -1), (-1, -1), 0.5, _GRID_COLOR),
            ]
        )
    )
    return table


def _group_table(group: ReportGroup, styles: dict[str, ParagraphStyle], size: int) -> Table:
    header = [
        Paragraph(f"<b>{_xml_escape(tr('report.col_parameter'))}</b>", styles["small"]),
        Paragraph(f"<b>{_xml_escape(tr('report.col_value'))}</b>", styles["small"]),
        Paragraph(f"<b>{_xml_escape(tr('report.col_norm'))}</b>", styles["small"]),
    ]
    data: list[list] = [header]
    pathology_rows: list[int] = []
    for index, value in enumerate(group.values, start=1):
        text = _xml_escape(value.value)
        if value.unit:
            text = f"{text} {_xml_escape(value.unit)}"
        if value.pathological:
            text = f"<font color='#C0392B'><b>{text}</b></font>"
            pathology_rows.append(index)
        data.append(
            [
                Paragraph(_xml_escape(value.label), styles["small"]),
                Paragraph(text, styles["small"]),
                Paragraph(_xml_escape(value.norm), styles["small"]),
            ]
        )

    width = A4[0] - 36 * mm
    table = Table(data, colWidths=[width * 0.52, width * 0.26, width * 0.22], repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), styles["small"].fontName),
        ("FONTSIZE", (0, 0), (-1, -1), max(6, size - 1)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, _GROUP_COLOR),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, _GRID_COLOR),
    ]
    for row in pathology_rows:
        style.append(("TEXTCOLOR", (0, row), (-1, row), PATHOLOGY_COLOR))
    table.setStyle(TableStyle(style))
    return table


def _signature_block(document: ReportDocument, styles: dict[str, ParagraphStyle]) -> Table:
    physician = (document.patient.physician or "").strip()
    row = [
        Paragraph(f"{_xml_escape(tr('report.physician'))}: {_xml_escape(physician)}", styles["small"]),
        Paragraph(f"{_xml_escape(tr('report.study_date'))}: {_xml_escape(document.patient.study_date)}", styles["small"]),
    ]
    width = A4[0] - 36 * mm
    table = Table([row], colWidths=[width * 0.6, width * 0.4])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), styles["small"].fontName),
                ("FONTSIZE", (0, 0), (-1, -1), max(6, styles["small"].fontSize)),
                ("LINEABOVE", (0, 0), (-1, 0), 0.5, _GRID_COLOR),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _register_cyrillic_font(pdfmetrics: object, TTFont: object) -> str:
    font_path = report_cyrillic_font_path()
    pdfmetrics.registerFont(TTFont("ReportCyrillic", str(font_path)))
    return "ReportCyrillic"
