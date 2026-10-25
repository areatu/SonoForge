"""Tests for the active structured measurement-report PDF export."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_FAKE_FONT = Path("/fake/font.ttf")


def test_pdf_export_error_class_exists() -> None:
    from echo_personal_tool.infrastructure.measurement_report_pdf import PdfExportError

    assert issubclass(PdfExportError, RuntimeError)


def test_register_cyrillic_font() -> None:
    from echo_personal_tool.infrastructure.measurement_report_pdf import _register_cyrillic_font

    mock_pm = MagicMock()
    mock_tf = MagicMock()
    with patch(
        "echo_personal_tool.infrastructure.measurement_report_pdf.report_cyrillic_font_path",
        return_value=_FAKE_FONT,
    ):
        result = _register_cyrillic_font(mock_pm, mock_tf)
    assert result == "ReportCyrillic"
    mock_pm.registerFont.assert_called_once()
    mock_tf.assert_called_once_with("ReportCyrillic", str(_FAKE_FONT))


class TestExportReportDocumentPdf:
    """The structured study protocol export (real reportlab run, no mocks)."""

    @staticmethod
    def _document():
        from echo_personal_tool.domain.services.report_builder import (
            PatientInfo,
            ReportDocument,
            ReportGroup,
            ReportValue,
        )

        return ReportDocument(
            patient=PatientInfo(
                name="Иванов И.И.",
                patient_id="12345",
                sex="M",
                study_date="17.05.2024",
                conclusion="Дилатация ЛП.",
            ),
            groups=(
                ReportGroup(
                    title="Левый желудочек",
                    key="lv",
                    values=(
                        ReportValue(
                            label="КДО ЛЖ",
                            value="120.0",
                            unit="мл",
                            norm="56–104",
                            group="lv",
                        ),
                        ReportValue(
                            label="ФВ ЛЖ",
                            value="48.0",
                            unit="%",
                            norm="52–72",
                            pathological=True,
                            group="lv",
                        ),
                    ),
                ),
            ),
        )

    def test_writes_a_pdf_file(self, tmp_path: Path) -> None:
        from echo_personal_tool.infrastructure.measurement_report_pdf import (
            export_report_document_pdf,
        )

        output = tmp_path / "sub" / "report.pdf"
        result = export_report_document_pdf(self._document(), output)
        assert result == output
        assert output.exists()
        assert output.read_bytes()[:5] == b"%PDF-"
        assert output.stat().st_size > 1000

    def test_empty_document_still_exports(self, tmp_path: Path) -> None:
        from echo_personal_tool.domain.services.report_builder import ReportDocument
        from echo_personal_tool.infrastructure.measurement_report_pdf import (
            export_report_document_pdf,
        )

        output = tmp_path / "empty.pdf"
        export_report_document_pdf(ReportDocument(), output)
        assert output.read_bytes()[:5] == b"%PDF-"

    def test_wraps_reportlab_failures_in_pdf_export_error(self, tmp_path: Path) -> None:
        from echo_personal_tool.infrastructure import measurement_report_pdf
        from echo_personal_tool.infrastructure.measurement_report_pdf import (
            PdfExportError,
            export_report_document_pdf,
        )

        output = tmp_path / "report.pdf"
        with patch.object(
            measurement_report_pdf,
            "_register_cyrillic_font",
            side_effect=OSError("no font"),
        ):
            with pytest.raises(PdfExportError):
                export_report_document_pdf(self._document(), output)


def test_bsa_provenance_reaches_the_pdf_story(tmp_path: Path) -> None:
    """QH-1b.2 slice 2: the printed protocol carries the BSA provenance.

    The export itself is a real reportlab run; the story it renders is built
    from the document, so the assertion walks the flowables that were added for
    the indexed group.
    """
    from unittest.mock import patch

    from echo_personal_tool.domain.models.measurements import IndexedMeasurements, MeasurementSnapshot
    from echo_personal_tool.domain.models.result_provenance import (
        BSA_SOURCE_DERIVED,
        BSA_SOURCE_MANUAL,
        REASON_MANUAL_OVERRIDE,
        BsaBasis,
        BsaRecordStatus,
        Freshness,
    )
    from echo_personal_tool.domain.services.report_builder import build_report_document
    from echo_personal_tool.infrastructure import measurement_report_pdf as pdf

    snapshot = MeasurementSnapshot(
        indexed=IndexedMeasurements(
            bsa_m2=1.55,
            simpson_edvi_ml_m2=77.4,
            bsa_basis=BsaBasis(1.55, BSA_SOURCE_MANUAL, 170.0, 70.0),
        ),
        bsa_record_status=BsaRecordStatus(
            Freshness.STALE.value,
            (REASON_MANUAL_OVERRIDE,),
            BsaBasis(1.93, BSA_SOURCE_DERIVED, 178.0, 80.0),
            BsaBasis(1.55, BSA_SOURCE_MANUAL, 170.0, 70.0),
        ),
    )
    document = build_report_document(snapshot, sex="M")

    story: list = []
    original = pdf.SimpleDocTemplate

    class _Capture:
        def __init__(self, *args, **kwargs):
            self._inner = original(*args, **kwargs)

        def build(self, flowables, **kwargs):
            story.extend(flowables)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    with patch.object(pdf, "SimpleDocTemplate", _Capture):
        pdf.export_report_document_pdf(document, tmp_path / "protocol.pdf")

    texts = [_flowable_text(item) for item in story]
    blob = "\n".join(texts)
    assert "1.55" in blob
    assert "1.93" in blob  # the note about the record's BSA


def _flowable_text(flowable) -> str:
    """Plain text of a reportlab flowable (table cells, paragraphs, notes)."""
    from reportlab.platypus import Paragraph, Table

    if isinstance(flowable, Paragraph):
        return flowable.getPlainText()
    if isinstance(flowable, Table):
        return "\n".join(_flowable_text(cell) for row in flowable._cellvalues for cell in row if cell is not None)
    return ""


@pytest.mark.parametrize("stage", ["font", "render", "replace"])
def test_pdf_failure_is_safe_and_preserves_destination(tmp_path: Path, stage: str) -> None:
    from echo_personal_tool.domain.services.report_builder import ReportDocument
    from echo_personal_tool.infrastructure import measurement_report_pdf as pdf

    output = tmp_path / "report.pdf"
    output.write_bytes(b"previous complete PDF")
    sentinel = "PATIENT-SENTINEL /private/patient/file"

    def fail_render(*args, **kwargs):
        temporary = next(tmp_path.glob(".report-*.pdf"))
        temporary.write_bytes(b"partial PDF")
        raise RuntimeError(sentinel)

    if stage == "font":
        failure = patch.object(pdf, "_register_cyrillic_font", side_effect=OSError(sentinel))
    elif stage == "replace":
        failure = patch.object(pdf.os, "replace", side_effect=PermissionError(sentinel))
    else:
        failure = patch.object(pdf.SimpleDocTemplate, "build", side_effect=fail_render)
    with failure, pytest.raises(pdf.PdfExportError) as caught:
        pdf.export_report_document_pdf(ReportDocument(), output)
    assert str(caught.value) == "pdf_export_failed"
    assert caught.value.code == "pdf_export_failed"
    assert caught.value.__suppress_context__
    assert output.read_bytes() == b"previous complete PDF"
    assert list(tmp_path.iterdir()) == [output]
