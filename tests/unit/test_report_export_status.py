"""Draft/stale/unreviewed status travels with every export (#555, 6.2)."""

from __future__ import annotations

import json
from pathlib import Path

from echo_personal_tool.application.report_export import (
    export_report_document_pdf,
    render_report_csv,
    render_report_json,
)
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.report_builder import (
    ReportDocument,
    ReportValue,
    build_report_document,
    with_extra_values,
)


def _document(*, draft: bool) -> ReportDocument:
    snapshot = MeasurementSnapshot(spacing_calibrated=False, unreviewed_contours=2)
    document = build_report_document(snapshot, draft=draft)
    return with_extra_values(document, (ReportValue(label="LVEDD", value="50", unit="мм"),))


def test_a_draft_export_lists_its_warnings(tmp_path: Path) -> None:
    document = _document(draft=True)

    assert document.draft is True
    assert len(document.notices) == 3, "draft, no scale and two unreviewed contours"

    payload = json.loads(render_report_json(document, tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "draft"
    assert payload["status_text"] == document.status_text
    assert payload["notices"] == list(document.notices)

    csv_text = render_report_csv(document, tmp_path / "report.csv").read_text(encoding="utf-8")
    assert "status" in csv_text.splitlines()[0]
    assert document.status_text in csv_text


def test_a_final_export_of_a_scaled_reviewed_study_has_no_warnings() -> None:
    document = build_report_document(MeasurementSnapshot(spacing_calibrated=True), draft=False)

    assert document.draft is False
    assert document.notices == ()


def test_the_pdf_prints_the_status_and_every_notice(tmp_path: Path) -> None:
    import fitz

    document = _document(draft=True)
    path = export_report_document_pdf(document, tmp_path / "report.pdf")
    with fitz.open(path) as pdf:
        text = "\n".join(page.get_text() for page in pdf)

    flat = " ".join(text.split())
    assert " ".join(document.status_text.split()) in flat
    for notice in document.notices:
        assert " ".join(notice.split()) in flat
