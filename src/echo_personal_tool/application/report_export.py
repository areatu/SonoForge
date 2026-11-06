"""Application facade for rendering and exporting study-report PDFs.

Presentation code works with the application-owned report artifact types below;
ReportLab, font registration and atomic filesystem publication stay behind the
infrastructure adapter. This module intentionally has no Qt dependency.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

from echo_personal_tool.domain.services.report_builder import ReportDocument
from echo_personal_tool.infrastructure import measurement_report_pdf as _pdf_adapter

if TYPE_CHECKING:
    from echo_personal_tool.domain.services.report_template import ReportTemplate

ValueId: TypeAlias = tuple[int, int]


@dataclass(frozen=True)
class PageRect:
    """Value-cell rectangle in PDF points, with a top-left origin."""

    page: int
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class RenderedReport:
    """PDF bytes and the value-cell anchors used by the report preview."""

    pdf: bytes
    anchors: dict[ValueId, list[PageRect]]


class ReportExportError(RuntimeError):
    """Safe public failure raised when report rendering or export fails."""

    code = "pdf_export_failed"


def render_report(
    document: ReportDocument, *, font_size: int = 10, template: ReportTemplate | None = None
) -> RenderedReport:
    """Render a report for preview without exposing the infrastructure DTO.

    ``template`` is the printable form of the protocol (item 12 of the
    2026-11-06 list); ``None`` keeps the full form of older builds.
    """
    try:
        rendered = _pdf_adapter.render_report(document, font_size=font_size, template=template)
    except _pdf_adapter.PdfExportError:
        raise ReportExportError("pdf_export_failed") from None

    anchors = {
        value_id: [PageRect(page=rect.page, x=rect.x, y=rect.y, w=rect.w, h=rect.h) for rect in rectangles]
        for value_id, rectangles in rendered.anchors.items()
    }
    return RenderedReport(pdf=rendered.pdf, anchors=anchors)


def export_report_document_pdf(
    document: ReportDocument,
    output_path: Path,
    *,
    font_size: int = 10,
) -> Path:
    """Atomically export a study report and return its destination path."""
    try:
        return _pdf_adapter.export_report_document_pdf(document, output_path, font_size=font_size)
    except _pdf_adapter.PdfExportError:
        raise ReportExportError("pdf_export_failed") from None


def publish_report_pdf(pdf: bytes, output_path: Path) -> Path:
    """Publish already rendered PDF bytes; the destination appears atomically.

    The background export worker (S3-04, #313) renders on its own thread, checks
    whether the user cancelled, and only then calls this — so a cancelled export
    never writes a file and a failed one leaves an existing report untouched.
    """
    try:
        return _pdf_adapter.write_report_pdf(pdf, output_path)
    except _pdf_adapter.PdfExportError:
        raise ReportExportError("pdf_export_failed") from None


# ── CSV / JSON export of the report sheet (Этап 2 backlog) ──────────


def _document_to_dict(document: ReportDocument) -> dict[str, Any]:
    """Flatten a :class:`ReportDocument` into a JSON-friendly dict."""
    patient = asdict(document.patient)
    groups: list[dict[str, Any]] = []
    for group in document.groups:
        groups.append(
            {
                "key": group.key,
                "title": group.title,
                "notes": list(group.notes),
                "values": [
                    {
                        "label": value.label,
                        "value": value.value,
                        "unit": value.unit,
                        "norm": value.norm,
                        "pathological": value.pathological,
                        "group": value.group,
                        "sample_count": value.sample_count,
                    }
                    for value in group.values
                ],
            }
        )
    return {"patient": patient, "groups": groups}


def render_report_json(document: ReportDocument, output_path: Path) -> Path:
    """Write a study report as a structured JSON document."""
    payload = _document_to_dict(document)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    tmp.replace(output_path)
    return output_path


def render_report_csv(document: ReportDocument, output_path: Path) -> Path:
    """Write a study report as a flat CSV table (group, label, value, unit, norm)."""
    header = ["group", "label", "value", "unit", "norm", "pathological", "sample_count"]
    rows: list[list[Any]] = []
    for group in document.groups:
        for value in group.values:
            rows.append(
                [
                    group.key,
                    value.label,
                    value.value,
                    value.unit,
                    value.norm,
                    "1" if value.pathological else "",
                    value.sample_count if value.sample_count is not None else "",
                ]
            )
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    tmp.replace(output_path)
    return output_path
