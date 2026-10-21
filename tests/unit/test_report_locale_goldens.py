"""UI-4 gate: RU/EN goldens of the report screen and of its PDF (§4.6, S-11).

The gate of the report mode is a pair of texts that must not drift: what the
physician sees next to the A4 sheet, and what the sheet itself prints.  The
screen carries the working markers («измерить», the clip of a value, the
«не заполнено» recommendations); the PDF carries the study only, plus the
explicit «не оценивалось» marks of the physician.  A screen-only marker that
leaks into the PDF is a defect of the paper document, so both directions are
pinned here: the goldens themselves, and the absence of the marker vocabulary
in the extracted text of the rendered sheet.
"""

from __future__ import annotations

from typing import Final

import pytest

UID = "1.2.840.113619.2.55.3.1234567890.77"

#: What the sections and export columns say, exactly, in each language.
SCREEN_GOLDENS: Final[dict[str, dict[str, object]]] = {
    "ru": {
        "sections_title": "Разделы",
        "counter": "0 из 6",
        "section_titles": (
            "Левый желудочек",
            "Левое предсердие",
            "Правое предсердие",
            "Диастолическая функция",
            "Допплер МК/АК",
            "Допплер ТК/ЛК",
        ),
        "section_counters": ("0/8", "0/3", "0/1", "0/5", "0/4", "0/1"),
        "not_filled_header": "Не заполнено",
        "first_missing": ("МЖП", "КДР ЛЖ", "ЗСЛЖ"),
        "measure": "измерить",
        "export_title": "Экспорт",
        "export_buttons": (
            ("reportExportPdf", "PDF…"),
            ("reportExportPrint", "Печать…"),
            ("reportFinish", "Завершить"),
        ),
        "banner": "Версия зафиксирована: только чтение. Правка создаёт новый черновик.",
    },
    "en": {
        "sections_title": "Sections",
        "counter": "0 of 6",
        "section_titles": (
            "Left Ventricle",
            "Left Atrium",
            "Right Atrium",
            "Diastolic Function",
            "MV/AV Doppler",
            "TV/PV Doppler",
        ),
        "section_counters": ("0/8", "0/3", "0/1", "0/5", "0/4", "0/1"),
        "not_filled_header": "Not filled",
        "first_missing": ("IVSD", "LVEDD", "LVPWD"),
        "measure": "measure",
        "export_title": "Export",
        "export_buttons": (
            ("reportExportPdf", "PDF…"),
            ("reportExportPrint", "Print…"),
            ("reportFinish", "Finish"),
        ),
        "banner": "The version is fixed: read-only. Editing starts a new draft.",
    },
}

#: The printed sheet of the fixture below — one measured value and one
#: «не оценивалось» mark.  These are the lines a PDF reader extracts.
PDF_GOLDENS: Final[dict[str, tuple[str, ...]]] = {
    "ru": (
        "Протокол ЭхоКГ",
        "Пациент",
        "Левый желудочек",
        "Показатель",
        "Значение",
        "Норма",
        "КДР ЛЖ",
        "48 mm",
        "42–59",
        "МЖП",
        "не оценивалось",
        "Врач:",
        "Дата исследования:",
    ),
    "en": (
        "Echocardiography report",
        "Patient",
        "Left ventricle",
        "Parameter",
        "Value",
        "Norm",
        "LVIDd",
        "48 mm",
        "42–59",
        "IVSD",
        "not assessed",
        "Physician:",
        "Study date:",
    ),
}


@pytest.fixture
def language(request):
    """Switch the UI language for one test and restore Russian afterwards."""
    from echo_personal_tool.infrastructure.i18n import set_language

    set_language(request.param)
    yield request.param
    set_language("ru")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _measured_snapshot():
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot

    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=120.0,
        millimeter_length=48.0,
        frame_index=7,
        sop_instance_uid=UID,
        measurement_id="m-0001",
    )
    return MeasurementSnapshot(linear_measurements=(measurement,), spacing_calibrated=True)


def _sheet_document(marked_key: str | None = None):
    """The document the sheet renders: values of the study plus the marks."""
    from echo_personal_tool.domain.services.report_builder import build_report_document, with_extra_values
    from echo_personal_tool.domain.services.report_sections import (
        build_report_sections,
        not_evaluated_values,
    )
    from echo_personal_tool.infrastructure.i18n import get_language, tr

    snapshot = _measured_snapshot()
    document = build_report_document(snapshot, None)
    if marked_key is None:
        return document
    # The rows carry the labels of the current UI language, as the sections
    # column of the mode does — the sheet must not mix languages.
    rows = not_evaluated_values(
        build_report_sections(None, get_language()),
        frozenset({marked_key}),
        value_text=tr("report.not_evaluated"),
    )
    return with_extra_values(document, rows)


def _pdf_lines(pdf: bytes) -> tuple[str, ...]:
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as reader:
        return tuple(line for page in reader for line in page.get_text().splitlines())


def _rendered_pdf() -> bytes:
    from echo_personal_tool.infrastructure.measurement_report_pdf import render_report

    return render_report(_sheet_document(marked_key="lv.ivsd")).pdf


def _labels(panel, object_name: str) -> list[str]:
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in panel.findChildren(QLabel) if label.objectName() == object_name]


def _button_texts(panel, object_name: str) -> list[str]:
    from PySide6.QtWidgets import QPushButton

    return [button.text() for button in panel.findChildren(QPushButton) if button.objectName() == object_name]


# ── what the physician reads on screen ────────────────────────────────


@pytest.mark.gui
@pytest.mark.parametrize("language", ("ru", "en"), indirect=True)
def test_the_sections_column_speaks_one_language(language, qapp) -> None:
    golden = SCREEN_GOLDENS[language]
    from echo_personal_tool.presentation.report_mode.sections import ReportSectionsPanel

    panel = ReportSectionsPanel()
    panel.set_projection(None)

    assert _labels(panel, "reportSectionsTitle") == [golden["sections_title"]]
    assert _labels(panel, "reportSectionsCounter") == [golden["counter"]]
    # Section titles, their counters and the recommendation labels are the
    # study vocabulary of the language: the golden keeps them honest.
    assert tuple(_labels(panel, "reportSectionTitle")) == golden["section_titles"]
    assert tuple(_labels(panel, "reportSectionCounter")) == golden["section_counters"]
    assert _labels(panel, "reportSectionsSubheader") == [golden["not_filled_header"]]
    assert tuple(_labels(panel, "reportMissingLabel")[:3]) == golden["first_missing"]
    assert set(_button_texts(panel, "reportMeasureLink")) == {golden["measure"]}
    panel.deleteLater()


@pytest.mark.gui
@pytest.mark.parametrize("language", ("ru", "en"), indirect=True)
def test_the_export_block_speaks_one_language(language, qapp) -> None:
    golden = SCREEN_GOLDENS[language]
    from PySide6.QtWidgets import QPushButton

    from echo_personal_tool.presentation.report_mode.export import ReportExportPanel

    panel = ReportExportPanel()
    buttons = tuple((button.objectName(), button.text()) for button in panel.findChildren(QPushButton))

    assert _labels(panel, "reportExportTitle") == [golden["export_title"]]
    assert buttons == golden["export_buttons"]
    assert panel.is_finished is False
    panel.set_finished(True)
    assert _labels(panel, "reportExportBanner") == [golden["banner"]]
    panel.deleteLater()


# ── what the sheet prints ─────────────────────────────────────────────


@pytest.mark.parametrize("language", ("ru", "en"), indirect=True)
def test_the_printed_sheet_matches_its_golden(language) -> None:
    from echo_personal_tool.infrastructure.measurement_report_pdf import render_report

    document = _sheet_document(marked_key="lv.ivsd")
    rendered = render_report(document)

    assert _pdf_lines(rendered.pdf) == PDF_GOLDENS[language]


@pytest.mark.parametrize("language", ("ru", "en"), indirect=True)
def test_a_printable_mark_is_never_replaced_by_a_screen_marker(language) -> None:
    """The paper says «не оценивалось», never «измерить» (spec §4.6)."""
    from echo_personal_tool.infrastructure.i18n import tr
    from echo_personal_tool.infrastructure.measurement_report_pdf import render_report

    rendered = render_report(_sheet_document(marked_key="lv.ivsd"))
    printed = "\n".join(_pdf_lines(rendered.pdf))

    assert tr("report.not_evaluated") in printed
    assert tr("report.not_evaluated").strip() != ""
    for screen_only in (
        tr("report.measure"),
        tr("report.measure_hint"),
        tr("report.not_filled"),
        tr("report.sections"),
        tr("report.export"),
        tr("report.print"),
        tr("report.finish"),
        UID,
        "clip",
        "клип",
    ):
        assert screen_only and screen_only not in printed


@pytest.mark.parametrize("language", ("ru", "en"), indirect=True)
def test_the_marks_reach_the_sheet_through_the_document(language) -> None:
    """A marked step prints as a row of its own group, with the honest value."""
    from echo_personal_tool.domain.models.value_origin import METHOD_NOT_EVALUATED
    from echo_personal_tool.domain.services.report_sections import build_report_sections
    from echo_personal_tool.infrastructure.i18n import get_language, tr

    document = _sheet_document(marked_key="lv.ivsd")
    sections = build_report_sections(None, get_language())
    step = next(item for item in sections[0].items if item.key == "lv.ivsd")
    lv = next(group for group in document.groups if group.key == "lv")
    marked = [value for value in lv.values if value.label == step.label]

    assert [value.value for value in marked] == [tr("report.not_evaluated")]
    # The mark is a statement of the physician: a method, no clip and no
    # measurement, so the card of PR-4 shows the method and nothing invented.
    origin = marked[0].origin
    assert origin is not None
    assert origin.method_id == METHOD_NOT_EVALUATED
    assert origin.clips == ()


# ── the «откуда значение» card, which only ever exists on screen ──────

CARD_GOLDENS: Final[dict[str, dict[str, str]]] = {
    "ru": {
        "title": "КДР ЛЖ · 48 mm",
        "method": "Метод: Линейный калипер",
        "identity": "ID измерения …m-0001 · ревизия 3",
        "source": "клип …67890.77 · кадр 8",
        "status": "Происхождение записано",
        "open": "Открыть кадры",
        "not_recorded": "Происхождение не записано",
    },
    "en": {
        "title": "LVIDd · 48 mm",
        "method": "Method: Linear caliper",
        "identity": "Measurement ID …m-0001 · revision 3",
        "source": "clip …67890.77 · frame 8",
        "status": "Provenance recorded",
        "open": "Open frames",
        "not_recorded": "Provenance not recorded",
    },
}


def _card_row(*, recorded: bool = True):
    from dataclasses import replace

    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import build_report_groups

    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=120.0,
        millimeter_length=48.0,
        frame_index=7,
        sop_instance_uid=UID,
        measurement_id="m-0001",
        revision=3,
    )
    groups = build_report_groups(MeasurementSnapshot(linear_measurements=(measurement,)))
    value = next(value for group in groups for value in group.values if value.origin is not None)
    # A derived aggregate carries no origin at all — the honest «не записано».
    return value if recorded else replace(value, origin=None)


def _card_texts(card, object_name: str) -> list:
    from PySide6.QtWidgets import QLabel

    return [label for label in card.findChildren(QLabel) if label.objectName() == object_name]


@pytest.mark.gui
@pytest.mark.parametrize("language", ("ru", "en"), indirect=True)
def test_the_value_card_matches_its_golden(language, qapp) -> None:
    goldens = CARD_GOLDENS[language]
    from echo_personal_tool.presentation.report_mode.provenance import ReportValueCard

    card = ReportValueCard()
    card.show_value(_card_row())

    assert [label.text() for label in _card_texts(card, "reportValueCardTitle")] == [goldens["title"]]
    assert [label.text() for label in _card_texts(card, "reportValueCardMethod")] == [goldens["method"]]
    assert [label.text() for label in _card_texts(card, "reportValueCardIdentity")] == [goldens["identity"]]
    assert [label.text() for label in _card_texts(card, "reportValueCardSource")] == [goldens["source"]]
    assert [label.text() for label in _card_texts(card, "reportValueCardStatus")] == [goldens["status"]]
    assert card.open_button.text() == goldens["open"]
    card.deleteLater()


@pytest.mark.gui
@pytest.mark.parametrize("language", ("ru", "en"), indirect=True)
def test_a_value_without_provenance_says_so_and_offers_nothing(language, qapp) -> None:
    goldens = CARD_GOLDENS[language]
    from echo_personal_tool.presentation.report_mode.provenance import ReportValueCard

    card = ReportValueCard()
    card.show_value(_card_row(recorded=False))

    assert [label.text() for label in _card_texts(card, "reportValueCardStatus")] == [goldens["not_recorded"]]
    # No method, no clip, no action: nothing is inferred where nothing was
    # recorded, and «Открыть кадры» cannot jump anywhere.
    assert _card_texts(card, "reportValueCardMethod")[0].isVisible() is False
    assert _card_texts(card, "reportValueCardSource") == []
    assert card.open_button.isVisible() is False
    card.deleteLater()


@pytest.mark.gui
@pytest.mark.parametrize("language", ("ru", "en"), indirect=True)
def test_the_card_text_never_reaches_the_printed_sheet(language, qapp) -> None:
    """The card is a child of the preview: the sheet stays the exported bytes."""
    from echo_personal_tool.presentation.report_mode.provenance import ReportValueCard

    goldens = CARD_GOLDENS[language]
    printed = "\n".join(_pdf_lines(_rendered_pdf()))

    for screen_only in goldens.values():
        assert screen_only not in printed
    card = ReportValueCard()
    assert "Показатель" not in [label.text() for label in _card_texts(card, "reportValueCardTitle")]
    card.deleteLater()
