"""Export, print and «Завершить» of the report mode (UI-4 PR-5, §4.6).

The cases pin what the slice promises: only PDF and print exist (UQ-06), the
print job prints the same bytes the sheet shows, and «Завершить» fixes a
read-only version whose editing starts a new draft (UQ-07) — without inventing
version storage on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

UID = "1.2.840.113619.2.55.3.1234567890.77"


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _russian():
    from echo_personal_tool.infrastructure.i18n import set_language

    set_language("ru")
    yield
    set_language("ru")


def _document():
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import build_report_document

    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=120.0,
        millimeter_length=48.0,
        frame_index=7,
        sop_instance_uid=UID,
        measurement_id="m-0001",
    )
    return build_report_document(MeasurementSnapshot(linear_measurements=(measurement,)), None)


def _export_panel(qtbot):
    from echo_personal_tool.presentation.report_mode.export import ReportExportPanel

    panel = ReportExportPanel()
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)
    return panel


def _page(qtbot, document=None):
    from echo_personal_tool.presentation.report_mode.page import ReportModePage

    page = ReportModePage(lambda: document if document is not None else _document())
    qtbot.addWidget(page)
    page.resize(1400, 860)
    page.show()
    qtbot.waitExposed(page)
    page.refresh_now()
    return page


# ── the export block ──────────────────────────────────────────────────


def test_the_block_offers_only_pdf_and_print(qtbot) -> None:
    panel = _export_panel(qtbot)

    from PySide6.QtWidgets import QPushButton

    names = {button.objectName() for button in panel.findChildren(QPushButton)}
    assert {"reportExportPdf", "reportExportPrint", "reportFinish"} <= names
    # UQ-06: DICOM SR and «В PACS» are absent, not disabled stubs.
    assert not any("dicom" in name.lower() or "pacs" in name.lower() for name in names)


@pytest.mark.gui_smoke
def test_pdf_and_print_emit_intent(qtbot) -> None:
    panel = _export_panel(qtbot)
    seen: list[str] = []
    panel.export_requested.connect(lambda: seen.append("pdf"))
    panel.print_requested.connect(lambda: seen.append("print"))

    panel.pdf_button.click()
    panel.print_button.click()

    assert seen == ["pdf", "print"]


@pytest.mark.gui_smoke
def test_finish_turns_into_a_new_draft(qtbot) -> None:
    panel = _export_panel(qtbot)
    seen: list[str] = []
    panel.finish_requested.connect(lambda: seen.append("finish"))
    panel.draft_requested.connect(lambda: seen.append("draft"))

    panel.finish_button.click()
    assert seen == ["finish"]

    panel.set_finished(True)
    assert panel.is_finished is True
    assert panel.finish_button.text() == "Новый черновик"
    panel.finish_button.click()
    assert seen == ["finish", "draft"]


def test_the_banner_explains_the_fixed_version(qtbot) -> None:
    from PySide6.QtWidgets import QLabel

    panel = _export_panel(qtbot)
    assert panel.is_finished is False
    panel.set_finished(True)

    banner = next(label for label in panel.findChildren(QLabel) if label.objectName() == "reportExportBanner")
    assert banner.isVisible() is True
    assert "только чтение" in banner.text()


def test_the_status_line_reports_the_outcome(qtbot) -> None:
    from PySide6.QtWidgets import QLabel

    panel = _export_panel(qtbot)
    panel.set_status("Сохранено: report.pdf")

    status = next(label for label in panel.findChildren(QLabel) if label.objectName() == "reportExportStatus")
    assert status.isVisible() is True
    assert "report.pdf" in status.text()

    panel.set_status("")
    assert status.isVisible() is False


# ── a finished version is read-only ──────────────────────────────────


def test_the_phrases_column_stops_editing_when_frozen(qtbot) -> None:
    from echo_personal_tool.domain.services.report_phrases import PHRASES
    from echo_personal_tool.infrastructure.report_phrase_store import PhraseStore
    from echo_personal_tool.presentation.report_mode.phrases import ReportPhrasesPanel

    panel = ReportPhrasesPanel(PhraseStore(Path("/nonexistent/phrases.json")))
    qtbot.addWidget(panel)
    panel.set_read_only(True)

    panel.insert_phrase(PHRASES[0])

    assert panel.conclusion == ""
    assert panel._editor.isReadOnly() is True


def test_the_sections_column_ignores_marks_when_frozen(qtbot) -> None:
    from echo_personal_tool.presentation.report_mode.sections import ReportSectionsPanel

    panel = ReportSectionsPanel()
    qtbot.addWidget(panel)
    panel.set_projection(None)
    key = panel.sections[0].items[0].key
    panel.set_frozen(True)
    seen: list[int] = []
    panel.not_evaluated_changed.connect(lambda: seen.append(1))

    panel._toggle_not_evaluated(key)

    assert panel.marked_not_evaluated() == frozenset()
    assert seen == []
    assert panel.is_frozen is True


def test_the_sheet_stops_following_the_study_when_frozen(qtbot) -> None:
    page = _page(qtbot)
    assert page.request_refresh() is None  # schedules, does not render now
    page.refresh_now()
    frozen_pdf = page.pdf_bytes
    assert frozen_pdf.startswith(b"%PDF-")

    page.set_finished(True)
    assert page.refresh_now() is False
    assert page.pdf_bytes == frozen_pdf

    page.set_finished(False)
    assert page.refresh_now() is True


def test_finishing_freezes_sections_phrases_and_sheet_together(qtbot) -> None:
    page = _page(qtbot)
    page.set_conclusion("Черновик заключения")

    page.set_finished(True)

    assert page.is_finished is True
    assert page.phrases.is_read_only is True
    assert page.sections.is_frozen is True
    assert page.preview.is_frozen is True
    assert page.export.is_finished is True
    assert page.conclusion == "Черновик заключения"


# ── printing ─────────────────────────────────────────────────────────


@pytest.mark.gui_smoke
def test_printing_writes_the_same_pages_as_the_sheet(qtbot, tmp_path) -> None:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPrintSupport import QPrinter

    from echo_personal_tool.presentation.report_mode.print_job import print_report_pdf

    page = _page(qtbot)
    target = tmp_path / "printed.pdf"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(target))

    assert print_report_pdf(page.pdf_bytes, printer) is True
    assert target.exists() and target.stat().st_size > 0

    printed = QPdfDocument()
    printed.load(str(target))
    assert printed.pageCount() == page.preview.page_count


def test_printing_empty_bytes_fails_honestly() -> None:
    from echo_personal_tool.presentation.report_mode.print_job import print_report_pdf

    assert print_report_pdf(b"", object()) is False
