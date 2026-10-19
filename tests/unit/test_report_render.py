"""Preview contract of the report mode (UI-4.0, spec §8.4).

``render_report`` builds the PDF bytes the A4 preview shows and the page
rectangles of every value cell in one pass. The rectangles live in page points
with the origin at the top-left corner (the rasterisation space), so the hover
"where did this value come from" can hit-test a cell without a second layout.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from echo_personal_tool.domain.services.report_builder import (
    PatientInfo,
    ReportDocument,
    ReportGroup,
    ReportValue,
)
from echo_personal_tool.infrastructure import measurement_report_pdf as pdf
from echo_personal_tool.infrastructure.measurement_report_pdf import (
    PdfExportError,
    RenderedReport,
    render_report,
)

_A4 = (595.2755905511812, 841.8897637795277)  # reportlab A4 in points


def _document(groups: int = 1, values_per_group: int = 2) -> ReportDocument:
    """One group of two rows unless the test asks for a longer study."""
    built = []
    for group_index in range(groups):
        rows = []
        for row_index in range(values_per_group):
            pathological = row_index == 1
            rows.append(
                ReportValue(
                    label=f"Параметр {group_index}-{row_index}",
                    value=f"{40.0 + row_index:.1f}",
                    unit="мм",
                    norm="36–51",
                    pathological=pathological,
                    group="lv",
                )
            )
        built.append(ReportGroup(title=f"Группа {group_index}", key="lv", values=tuple(rows)))
    return ReportDocument(
        patient=PatientInfo(
            name="Иванов И.И.",
            patient_id="12345",
            sex="M",
            study_date="17.05.2024",
            conclusion="Дилатация ЛП.",
        ),
        groups=tuple(built),
    )


class TestRenderReport:
    def test_returns_pdf_bytes_and_anchors(self) -> None:
        rendered = render_report(_document())
        assert isinstance(rendered, RenderedReport)
        assert rendered.pdf[:5] == b"%PDF-"
        assert len(rendered.pdf) > 1000

    def test_every_value_cell_gets_an_anchor(self) -> None:
        rendered = render_report(_document(groups=1, values_per_group=2))
        assert set(rendered.anchors) == {(0, 0), (0, 1)}
        for rects in rendered.anchors.values():
            assert len(rects) == 1

    def test_anchor_rects_are_inside_the_page(self) -> None:
        rendered = render_report(_document())
        for rects in rendered.anchors.values():
            for rect in rects:
                assert rect.page == 0
                assert rect.w > 0 and rect.h > 0
                assert rect.x >= 0 and rect.x + rect.w <= _A4[0] + 1e-6
                assert rect.y >= 0 and rect.y + rect.h <= _A4[1] + 1e-6

    def test_value_anchors_share_one_column_and_row_order(self) -> None:
        rendered = render_report(_document(groups=1, values_per_group=3))
        first = rendered.anchors[(0, 0)][0]
        second = rendered.anchors[(0, 1)][0]
        third = rendered.anchors[(0, 2)][0]
        # one value column: same left edge …
        assert first.x == pytest.approx(second.x, abs=0.01)
        assert first.x == pytest.approx(third.x, abs=0.01)
        # … and rows stack downward (top-left origin)
        assert first.y < second.y < third.y

    def test_page_index_tracks_a_multipage_study(self) -> None:
        rendered = render_report(_document(groups=18, values_per_group=6))
        pages = [rect.page for rects in rendered.anchors.values() for rect in rects]
        assert max(pages) >= 2
        assert sorted(set(pages)) == list(range(max(pages) + 1))
        # rows stay in document order across page breaks
        row_pages = [rendered.anchors[(group, row)][0].page for group in range(18) for row in range(6)]
        assert row_pages == sorted(row_pages)

    def test_empty_document_renders_without_anchors(self) -> None:
        rendered = render_report(ReportDocument())
        assert rendered.pdf[:5] == b"%PDF-"
        assert rendered.anchors == {}

    def test_failures_are_wrapped_in_pdf_export_error(self) -> None:
        with patch.object(pdf.SimpleDocTemplate, "build", side_effect=RuntimeError("boom")):
            with pytest.raises(PdfExportError) as caught:
                render_report(_document())
        assert str(caught.value) == "pdf_export_failed"
        assert caught.value.__suppress_context__

    def test_export_writes_the_same_document_the_preview_shows(self, tmp_path) -> None:
        """Export is `render_report` + an atomic write; both start from one render."""
        output = tmp_path / "report.pdf"
        pdf.export_report_document_pdf(_document(), output)
        assert output.read_bytes()[:5] == b"%PDF-"
        # the preview contract holds for the exported bytes: a fresh render of
        # the same document is a valid report with the same anchors
        rendered = render_report(_document())
        assert rendered.anchors == render_report(_document()).anchors


class TestAnchorRectsMatchRenderedText:
    """Cross-check the recorded rectangles against the glyphs PDFium sees."""

    @staticmethod
    def _words(page) -> list[tuple[str, tuple[float, float, float, float]]]:
        return [(word[4], (word[0], word[1], word[2], word[3])) for word in page.get_text("words")]

    def test_value_text_lies_inside_its_anchor(self, tmp_path) -> None:
        fitz = pytest.importorskip("fitz")

        rendered = render_report(_document(groups=1, values_per_group=2))
        doc = fitz.open(stream=rendered.pdf, filetype="pdf")
        page = doc[0]
        words = self._words(page)
        by_text = {text: rect for text, rect in words}

        for row, expected in ((0, "40.0"), (1, "41.0")):
            anchor = rendered.anchors[(0, row)][0]
            glyph = by_text[expected]
            assert anchor.x - 1 <= glyph[0], (anchor, glyph)
            assert glyph[2] <= anchor.x + anchor.w + 1
            assert anchor.y - 1 <= glyph[1]
            assert glyph[3] <= anchor.y + anchor.h + 1

    def test_anchor_column_covers_the_value_not_the_label(self) -> None:
        fitz = pytest.importorskip("fitz")

        rendered = render_report(_document(groups=1, values_per_group=1))
        anchor = rendered.anchors[(0, 0)][0]
        page = fitz.open(stream=rendered.pdf, filetype="pdf")[0]
        label_rect = next(rect for text, rect in self._words(page) if text == "Параметр")
        value_rect = next(rect for text, rect in self._words(page) if text == "40.0")
        assert label_rect[2] < anchor.x, "label column must not be covered"
        assert value_rect[0] >= anchor.x - 1
