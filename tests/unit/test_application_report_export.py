"""Application-facing PDF report facade tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.application import report_export
from echo_personal_tool.application.report_export import (
    PageRect,
    RenderedReport,
    ReportExportError,
)
from echo_personal_tool.domain.services.report_builder import ReportDocument


def test_render_returns_application_owned_anchor_types(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter_rect = report_export._pdf_adapter.PageRect(page=1, x=10.0, y=20.0, w=30.0, h=4.0)

    def render(_document: ReportDocument, *, font_size: int):
        assert font_size == 12
        return report_export._pdf_adapter.RenderedReport(
            pdf=b"%PDF-test",
            anchors={(2, 3): [adapter_rect]},
        )

    monkeypatch.setattr(report_export._pdf_adapter, "render_report", render)

    rendered = report_export.render_report(ReportDocument(), font_size=12)

    assert isinstance(rendered, RenderedReport)
    assert rendered.pdf == b"%PDF-test"
    assert rendered.anchors == {(2, 3): [PageRect(page=1, x=10.0, y=20.0, w=30.0, h=4.0)]}
    assert rendered.anchors[(2, 3)][0] is not adapter_rect


def test_render_translates_adapter_failure_to_safe_application_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args, **_kwargs):
        raise report_export._pdf_adapter.PdfExportError("PHI / private/path/report.pdf")

    monkeypatch.setattr(report_export._pdf_adapter, "render_report", fail)

    with pytest.raises(ReportExportError) as caught:
        report_export.render_report(ReportDocument())

    assert str(caught.value) == "pdf_export_failed"
    assert caught.value.__suppress_context__
    assert "PHI" not in str(caught.value)
    assert "private/path" not in str(caught.value)


def test_real_adapter_renders_and_atomically_exports_a_pdf(tmp_path: Path) -> None:
    document = ReportDocument()
    rendered = report_export.render_report(document)
    destination = tmp_path / "study-report.pdf"

    result = report_export.export_report_document_pdf(document, destination)

    assert rendered.pdf.startswith(b"%PDF-")
    assert rendered.anchors == {}
    assert result == destination
    assert destination.read_bytes().startswith(b"%PDF-")


def test_export_delegates_the_document_path_and_font_size(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    document = ReportDocument()
    destination = tmp_path / "study-report.pdf"
    calls = []

    def export(actual_document, actual_path, *, font_size):
        calls.append((actual_document, actual_path, font_size))
        return actual_path

    monkeypatch.setattr(report_export._pdf_adapter, "export_report_document_pdf", export)

    result = report_export.export_report_document_pdf(document, destination, font_size=13)

    assert result == destination
    assert calls == [(document, destination, 13)]


def test_export_translates_adapter_failure_to_safe_application_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(*_args, **_kwargs):
        raise report_export._pdf_adapter.PdfExportError("/private/study/report.pdf")

    monkeypatch.setattr(report_export._pdf_adapter, "export_report_document_pdf", fail)

    with pytest.raises(ReportExportError) as caught:
        report_export.export_report_document_pdf(ReportDocument(), tmp_path / "report.pdf")

    assert str(caught.value) == "pdf_export_failed"
    assert caught.value.__suppress_context__
    assert "/private" not in str(caught.value)
