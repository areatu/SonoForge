"""Tests for the active structured measurement-report PDF export."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from echo_personal_tool.domain.services.report_builder import ReportDocument

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
    children = getattr(flowable, "_content", None)
    if children:
        return "\n".join(_flowable_text(child) for child in children if child is not None)
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


def _two_group_document():
    from echo_personal_tool.domain.services.report_builder import (
        PatientInfo,
        ReportDocument,
        ReportGroup,
        ReportValue,
    )

    return ReportDocument(
        patient=PatientInfo(name="Иванов И.И.", patient_id="12345"),
        groups=(
            ReportGroup(
                title="Левый желудочек",
                key="lv",
                values=(ReportValue(label="КДО ЛЖ", value="120.0", unit="мл", group="lv"),),
            ),
            ReportGroup(
                title="Левое предсердие",
                key="la",
                values=(ReportValue(label="КДР ЛП", value="42.0", unit="мм", group="la"),),
            ),
        ),
    )


def test_two_column_template_rebuilds_the_sheet(tmp_path: Path) -> None:
    """«Колонки измерений — две» must visibly change the sheet (2026-11-16, п.6).

    The renderer lays two or more groups side by side for the two-column
    template; a template that changes nothing in the bytes is exactly the bug
    the owner reported.
    """
    from echo_personal_tool.domain.services.report_template import COLUMNS_TWO, ReportTemplate
    from echo_personal_tool.infrastructure.measurement_report_pdf import render_report

    document = _two_group_document()
    one_column = render_report(document, template=ReportTemplate(columns=1))
    two_column = render_report(document, template=ReportTemplate(columns=COLUMNS_TWO))

    assert one_column.pdf != two_column.pdf

    import fitz

    with fitz.open(stream=two_column.pdf, filetype="pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
    flat = " ".join(text.split())
    assert "Левый желудочек" in flat
    assert "Левое предсердие" in flat
    assert "120.0" in flat and "42.0" in flat


# ── Layout: title/table blocks, column alignment, conclusion spacing ──────────


def _four_group_document(conclusion: str = "Дилатация ЛП. ФВ ЛЖ сохранена.") -> ReportDocument:
    from echo_personal_tool.domain.services.report_builder import (
        PatientInfo,
        ReportDocument,
        ReportGroup,
        ReportValue,
    )

    def group(title: str, key: str, rows):
        return ReportGroup(
            title=title,
            key=key,
            values=tuple(
                ReportValue(label=label, value=value, unit=unit, norm=norm, group=key)
                for label, value, unit, norm in rows
            ),
        )

    return ReportDocument(
        patient=PatientInfo(
            name="Иванов И.И.", patient_id="1", sex="M", study_date="17.05.2024", conclusion=conclusion
        ),
        groups=(
            group("Левый желудочек", "lv", [("КДО ЛЖ", "120", "мл", "62–150"), ("ФВ ЛЖ", "60", "%", "52–72")]),
            group("Левое предсердие", "la", [("КДР ЛП", "42", "мм", "30–40")]),
            group("Правый желудочек", "rv", [("Базальный РЖ", "32", "мм", "25–41")]),
            group("Правое предсердие", "ra", [("Площадь ПП", "18", "см²", "≤19")]),
        ),
    )


def _text_blocks(pdf_bytes: bytes) -> list[tuple[float, float, float, float, str]]:
    """(x0, y0, x1, y1, text) of every text block of the first PDF page."""
    import fitz

    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        return [(x0, y0, x1, y1, " ".join(text.split())) for x0, y0, x1, y1, text, *_ in pdf[0].get_text("blocks")]


def _block_containing(blocks, needle: str):
    for block in blocks:
        if needle in block[4]:
            return block
    raise AssertionError(f"no text block contains {needle!r}")


def test_two_column_headings_stay_with_their_tables_and_line_up() -> None:
    """П. 2 + 11 (2026-11-18): «Названия таблиц и сами таблицы переносятся одним
    блоком», а верхние заголовки колонок стоят на одной линии.

    The two-column sheet once could leave a heading in one column while its
    table sat in the other, and the columns could start at different heights
    (a leftover spacer opened the second column lower than the first).
    """
    from echo_personal_tool.domain.services.report_template import COLUMNS_TWO, ReportTemplate
    from echo_personal_tool.infrastructure.measurement_report_pdf import render_report

    rendered = render_report(_four_group_document(), template=ReportTemplate(columns=COLUMNS_TWO))
    blocks = _text_blocks(rendered.pdf)

    for title, first_row in (
        ("Левый желудочек", "КДО ЛЖ"),
        ("Левое предсердие", "КДР ЛП"),
        ("Правый желудочек", "Базальный РЖ"),
        ("Правое предсердие", "Площадь ПП"),
    ):
        title_block = _block_containing(blocks, title)
        row_block = _block_containing(blocks, first_row)
        # Same column means the two blocks start within one column width of
        # each other horizontally — the columns sit tens of points apart.
        assert abs(title_block[0] - row_block[0]) < 30, f"{title}: heading and table are in different columns"
        assert row_block[1] > title_block[1], f"{title}: the table must be below its heading"

    # The columns' top headings share one baseline (same y, ± 2 pt).
    left_top = _block_containing(blocks, "Левый желудочек")
    right_top = _block_containing(blocks, "Правый желудочек")
    assert abs(left_top[1] - right_top[1]) < 2.0


def test_single_column_headings_stay_with_their_tables() -> None:
    """П. 2: even in the one-column layout the heading never separates."""
    from echo_personal_tool.domain.services.report_template import ReportTemplate
    from echo_personal_tool.infrastructure.measurement_report_pdf import render_report

    rendered = render_report(_four_group_document(), template=ReportTemplate(columns=1))
    blocks = _text_blocks(rendered.pdf)

    for title, first_row in (
        ("Левый желудочек", "КДО ЛЖ"),
        ("Левое предсердие", "КДР ЛП"),
        ("Правый желудочек", "Базальный РЖ"),
        ("Правое предсердие", "Площадь ПП"),
    ):
        title_block = _block_containing(blocks, title)
        row_block = _block_containing(blocks, first_row)
        # Table starts right under its heading — a gap of one heading height,
        # never a foreign block in between.
        assert 0 < row_block[1] - title_block[1] < 40, f"{title}: table drifted away from its heading"


def test_conclusion_heading_is_spaced_and_kept_with_its_text() -> None:
    """П. 10 (2026-11-18): «Заключение» не прилипает к таблице и не сиротеет."""
    from echo_personal_tool.domain.services.report_template import COLUMNS_TWO, ReportTemplate
    from echo_personal_tool.infrastructure.measurement_report_pdf import render_report

    for template in (ReportTemplate(columns=1), ReportTemplate(columns=COLUMNS_TWO)):
        rendered = render_report(_four_group_document(), template=template)
        blocks = _text_blocks(rendered.pdf)
        conclusion = next(block for block in blocks if "Заключение" in block[4] or "Conclusion" in block[4])
        # The heading keeps a deliberate gap (>= 5 mm) from the last table …
        above = max(block[3] for block in blocks if block[3] <= conclusion[1] + 0.5)
        gap = conclusion[1] - above
        assert gap >= 5 * 2.83, f"conclusion heading hugs the table (gap {gap:.1f} pt)"
        # … and it is one block together with its text (no widow heading).
        assert "Дилатация ЛП." in conclusion[4]
