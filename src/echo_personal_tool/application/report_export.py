"""Application facade for rendering and exporting study-report PDFs.

Presentation code works with the application-owned report artifact types below;
ReportLab, font registration and atomic filesystem publication stay behind the
infrastructure adapter. This module intentionally has no Qt dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from echo_personal_tool.domain.services.report_builder import ReportDocument
from echo_personal_tool.infrastructure import measurement_report_pdf as _pdf_adapter

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


def render_report(document: ReportDocument, *, font_size: int = 10) -> RenderedReport:
    """Render a report for preview without exposing the infrastructure DTO."""
    try:
        rendered = _pdf_adapter.render_report(document, font_size=font_size)
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
