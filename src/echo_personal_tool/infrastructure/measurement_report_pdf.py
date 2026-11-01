"""Export the structured measurement report to PDF.

The report dialog preview and the exported PDF share :func:`render_report`:
the A4 sheet on screen is exactly the document that gets saved, and the
recorded page rectangles power the "where did this value come from" hover.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from functools import wraps
from io import BytesIO
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, TypeVar, cast
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from echo_personal_tool.domain.services.report_builder import ReportDocument, ReportGroup, format_sex
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.resources.bundled_fonts import report_cyrillic_font_path

#: Values outside the reference range are printed in this colour.
PATHOLOGY_COLOR = colors.HexColor("#C0392B")
_GROUP_COLOR = colors.HexColor("#34495E")
_GRID_COLOR = colors.HexColor("#B9C2CB")


class PdfExportError(RuntimeError):
    """Safe public failure: never contains report content or filesystem paths."""

    code = "pdf_export_failed"


#: Identity of one report row for the preview hover ("where did this value
#: come from"): ``(group index, value index)`` in the source :class:`ReportDocument`.
#: Positional on purpose — :class:`~echo_personal_tool.domain.services.report_builder.ReportValue`
#: has no stable id yet; when QH-1b provenance ids reach the report builder the
#: preview maps them through the document it was rendered from.
ValueId = tuple[int, int]


@dataclass(frozen=True)
class PageRect:
    """Rectangle on one PDF page.

    Coordinates are PDF points with the origin at the **top-left** corner of
    the page (y grows downward) — the same space as page rasterisation, so a
    preview widget can map a hover to a cell without flipping the axis.
    """

    page: int
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class RenderedReport:
    """PDF bytes of the report plus the page rectangles of its value cells."""

    pdf: bytes
    anchors: dict[ValueId, list[PageRect]]


_PayloadT = TypeVar("_PayloadT")
_ExportParams = ParamSpec("_ExportParams")


def _atomic_pdf_export(
    exporter: Callable[Concatenate[_PayloadT, Path, _ExportParams], Path],
) -> Callable[Concatenate[_PayloadT, Path, _ExportParams], Path]:
    """Publish only complete PDFs; keep an existing destination on failure.

    Annotated with ``ParamSpec`` so the decorated function keeps its own
    signature for callers: the wrapper used to be untyped, which under
    ``disallow_untyped_decorators`` made every export function it wrapped
    untyped too (issue 325).
    """

    @wraps(exporter)
    def export(
        payload: _PayloadT,
        output_path: Path,
        *args: _ExportParams.args,
        **kwargs: _ExportParams.kwargs,
    ) -> Path:
        temporary = None
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".report-", suffix=".pdf", dir=output_path.parent)
            temporary = Path(name)
            os.close(fd)
            exporter(payload, temporary, *args, **kwargs)
            os.replace(temporary, output_path)
            return output_path
        except Exception:  # noqa: BLE001 - reportlab and filesystem boundary
            raise PdfExportError("pdf_export_failed") from None
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)

    # ``functools.wraps`` hands back a ``_Wrapped[...]`` whose ``__call__`` mypy
    # cannot re-collapse into the declared ParamSpec; the cast restates what the
    # wrapper already does at runtime.
    return cast("Callable[Concatenate[_PayloadT, Path, _ExportParams], Path]", export)


def _report_story(
    document: ReportDocument,
    styles: dict[str, ParagraphStyle],
    size: int,
    anchors: dict[ValueId, list[PageRect]] | None = None,
) -> list:
    """Platypus flowables of the study protocol; value cells record their rects."""
    story: list = [Paragraph(_xml_escape(tr("report.title")), styles["title"])]
    story.append(Spacer(1, 4 * mm))
    story.append(_patient_header(document, styles, size))
    story.append(Spacer(1, 5 * mm))

    if not document.has_measurements:
        story.append(Paragraph(_xml_escape(tr("report.no_measurements")), styles["note"]))
    for group_index, group in enumerate(document.groups):
        story.append(Paragraph(_xml_escape(group.title), styles["group"]))
        story.append(_group_table(group, styles, size, anchors=anchors, group_index=group_index))
        for note in group.notes:
            story.append(Paragraph(_xml_escape(note), styles["note"]))
        story.append(Spacer(1, 4 * mm))

    conclusion = (document.patient.conclusion or "").strip()
    if conclusion:
        story.append(Paragraph(_xml_escape(tr("report.conclusion")), styles["group"]))
        story.append(Paragraph(_xml_escape(conclusion).replace("\n", "<br/>"), styles["body"]))

    story.append(Spacer(1, 8 * mm))
    story.append(_signature_block(document, styles))
    return story


class _AnchoredParagraph(Paragraph):  # type: ignore[misc]  # reportlab ships no type stubs, so its base class is Any
    """Value cell that records where it was painted (UI-4.0, spec §8.4).

    :class:`Table` draws cell flowables through ``drawOn``, at which point the
    canvas transform is positioned on the cell, so the absolute page position is
    known exactly — no second layout pass and no way for the recorded rectangle
    to drift from what the PDF shows.
    """

    def __init__(
        self,
        text: str,
        style: ParagraphStyle,
        *,
        value_id: ValueId,
        sink: dict[ValueId, list[PageRect]],
    ) -> None:
        super().__init__(text, style)
        self._value_id = value_id
        self._sink = sink

    def drawOn(self, canv: Any, x: float, y: float, _sW: float = 0, **kwargs: Any) -> Any:
        result = super().drawOn(canv, x, y, _sW, **kwargs)
        width = getattr(self, "width", 0.0) or 0.0
        height = getattr(self, "height", 0.0) or 0.0
        _page_width, page_height = getattr(canv, "_pagesize", A4)
        left, bottom = canv.absolutePosition(x, y)
        self._sink.setdefault(self._value_id, []).append(
            PageRect(
                page=canv.getPageNumber() - 1,
                x=left,
                y=page_height - bottom - height,
                w=width,
                h=height,
            )
        )
        return result


def render_report(document: ReportDocument, *, font_size: int = 10) -> RenderedReport:
    """Build the PDF preview and the value-cell anchors in one pass.

    Preview contract for the report mode (UI-4.0, spec §8.4): the returned
    bytes are exactly what :func:`export_report_document_pdf` writes, so the A4
    sheet on screen cannot diverge from the exported document. ``anchors``
    locates every value cell on its page for the "where did this value come
    from" hover; markers that must not print are a separate screen layer and
    are never drawn into the PDF.

    Failures raise :class:`PdfExportError`, the same safe error as the export.
    """
    try:
        font_name = _register_cyrillic_font(pdfmetrics, TTFont)
        size = max(8, min(16, int(font_size)))
        styles = _report_styles(font_name, size)
        anchors: dict[ValueId, list[PageRect]] = {}
        story = _report_story(document, styles, size, anchors)
        buffer = BytesIO()
        pdf = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            title=tr("report.title"),
        )
        pdf.build(story)
        return RenderedReport(pdf=buffer.getvalue(), anchors=anchors)
    except Exception:  # noqa: BLE001 - reportlab and in-memory buffer boundary
        raise PdfExportError("pdf_export_failed") from None


@_atomic_pdf_export
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
    The bytes come from :func:`render_report` — the same render the preview
    shows — and the file is published atomically (UI-4 PR-5): a failed export
    leaves an existing report untouched instead of truncating it.
    """
    rendered = render_report(document, font_size=font_size)
    output_path.write_bytes(rendered.pdf)
    return output_path


def write_report_pdf(pdf: bytes, output_path: Path) -> Path:
    """Publish already rendered PDF bytes atomically (S3-04, #313).

    Split from :func:`export_report_document_pdf` so a background worker can
    render (the slow part) on its own thread, honour a cancellation request, and
    only then publish — the same all-or-nothing rule, with the same safe error.
    """
    temporary: Path | None = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".report-", suffix=".pdf", dir=output_path.parent)
        temporary = Path(name)
        os.close(fd)
        temporary.write_bytes(pdf)
        os.replace(temporary, output_path)
        temporary = None
        return output_path
    except OSError:
        raise PdfExportError("pdf_export_failed") from None
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


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


def _group_table(
    group: ReportGroup,
    styles: dict[str, ParagraphStyle],
    size: int,
    *,
    anchors: dict[ValueId, list[PageRect]] | None = None,
    group_index: int = 0,
) -> Table:
    header = [
        Paragraph(f"<b>{_xml_escape(tr('report.col_parameter'))}</b>", styles["small"]),
        Paragraph(f"<b>{_xml_escape(tr('report.col_value'))}</b>", styles["small"]),
        Paragraph(f"<b>{_xml_escape(tr('report.col_norm'))}</b>", styles["small"]),
    ]
    data: list[list] = [header]
    pathology_rows: list[int] = []
    for index, value in enumerate(group.values, start=1):
        text = _xml_escape(value.display_value)
        if value.unit:
            text = f"{text} {_xml_escape(value.unit)}"
        if value.pathological:
            text = f"<font color='#C0392B'><b>{text}</b></font>"
            pathology_rows.append(index)
        value_cell: Paragraph
        if anchors is None:
            value_cell = Paragraph(text, styles["small"])
        else:
            value_cell = _AnchoredParagraph(
                text,
                styles["small"],
                value_id=(group_index, index - 1),
                sink=anchors,
            )
        data.append(
            [
                Paragraph(_xml_escape(value.label), styles["small"]),
                value_cell,
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
        Paragraph(
            f"{_xml_escape(tr('report.study_date'))}: {_xml_escape(document.patient.study_date)}", styles["small"]
        ),
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
    pdfmetrics.registerFont(TTFont("ReportCyrillic", str(font_path)))  # type: ignore
    return "ReportCyrillic"
