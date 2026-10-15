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
        from echo_personal_tool.infrastructure.i18n import set_language

        set_language("ru")
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


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("stage", ["font", "render", "replace"])
def test_pdf_failure_is_safe_and_preserves_destination(tmp_path, structured, stage):
    from echo_personal_tool.domain.services.report_builder import ReportDocument
    from echo_personal_tool.infrastructure import measurement_report_pdf as pdf

    output = tmp_path / "report.pdf"
    output.write_bytes(b"previous complete PDF")
    sentinel = "PATIENT-SENTINEL /private/patient/file"
    exporter = pdf.export_report_document_pdf if structured else pdf.export_measurement_report_pdf
    payload = ReportDocument() if structured else sentinel

    def fail_render(*args, **kwargs):
        temporary = next(tmp_path.glob(".report-*.pdf"))
        temporary.write_bytes(b"partial PDF")
        raise RuntimeError(sentinel)

    if stage == "font":
        failure = patch.object(pdf, "_register_cyrillic_font", side_effect=OSError(sentinel))
    elif stage == "replace":
        failure = patch.object(pdf.os, "replace", side_effect=PermissionError(sentinel))
    elif structured:
        failure = patch.object(pdf.SimpleDocTemplate, "build", side_effect=fail_render)
    else:
        failure = patch.object(pdf.canvas.Canvas, "save", side_effect=fail_render)
    with failure, pytest.raises(pdf.PdfExportError) as caught:
        exporter(payload, output)
    assert str(caught.value) == "pdf_export_failed"
    assert caught.value.code == "pdf_export_failed"
    assert caught.value.__suppress_context__
    assert output.read_bytes() == b"previous complete PDF"
    assert list(tmp_path.iterdir()) == [output]
