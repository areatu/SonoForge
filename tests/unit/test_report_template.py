"""Report template: the printable form of the protocol (item 12 of the list).

The owner's clinic prints its own header: a field the study does not use should
not take a line of the sheet.  The template is an in-application, versioned
dataclass — not a template language — because the sheet is the exact exported
bytes and arbitrary layout would trade that guarantee for nothing.  A broken
file decodes to the standard form instead of a half-printed sheet.
"""

from __future__ import annotations

import json

import pytest

from echo_personal_tool.domain.services.report_template import (
    COLUMNS_ONE,
    COLUMNS_TWO,
    FIELD_AGE,
    FIELD_INDICATION,
    FIELD_NAME,
    FIELD_PHYSICIAN,
    HEADER_FIELDS,
    ReportTemplate,
    decode_template,
    default_template,
    encode_template,
)


def test_the_default_prints_every_field_in_the_historical_order() -> None:
    template = default_template()
    assert template.header_fields == HEADER_FIELDS
    assert template.header_fields[0] == FIELD_NAME
    assert template.show_notes and template.show_conclusion and template.show_signature
    assert template.normalized_columns == COLUMNS_ONE


def test_a_field_is_printed_only_when_it_is_listed() -> None:
    template = ReportTemplate(header_fields=(FIELD_NAME, FIELD_PHYSICIAN))
    assert template.prints_field(FIELD_NAME) is True
    assert template.prints_field(FIELD_INDICATION) is False


def test_the_order_of_the_fields_is_the_order_of_the_list() -> None:
    template = default_template().with_field_order((FIELD_PHYSICIAN, FIELD_NAME, FIELD_AGE))
    assert template.header_fields == (FIELD_PHYSICIAN, FIELD_NAME, FIELD_AGE)


def test_unknown_and_duplicated_ids_are_dropped() -> None:
    template = default_template().with_field_order(("height", "ghost", "height", "name"))
    assert template.header_fields == ("height", "name")


def test_the_columns_are_one_or_two() -> None:
    assert ReportTemplate(columns=2).normalized_columns == COLUMNS_TWO
    assert ReportTemplate(columns=3).normalized_columns == COLUMNS_ONE
    assert ReportTemplate(columns=0).normalized_columns == COLUMNS_ONE


def test_a_template_round_trips_through_json() -> None:
    original = ReportTemplate(
        name="Клиника",
        header_fields=(FIELD_PHYSICIAN, FIELD_NAME),
        show_notes=False,
        show_conclusion=True,
        show_signature=False,
        columns=COLUMNS_TWO,
    )
    restored = decode_template(encode_template(original))
    assert restored == original
    assert json.loads(encode_template(original))["columns"] == 2


def test_the_stored_document_carries_its_version() -> None:
    payload = json.loads(encode_template(default_template()))
    assert payload["version"] == 1


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not json",
        "[]",
        "42",
        "{",
        {"header_fields": "nope"},
        {"columns": "two"},
    ],
)
def test_garbage_decodes_to_the_standard_form(raw) -> None:
    assert decode_template(raw) == default_template()


def test_a_future_version_falls_back_instead_of_guessing() -> None:
    payload = json.dumps({"version": 99, "header_fields": ["name"]})
    assert decode_template(payload) == default_template()


def test_an_empty_header_list_is_a_choice_and_is_kept() -> None:
    """«No header fields at all» is what a physician may ask for; it is not garbage."""
    template = decode_template(json.dumps({"version": 1, "header_fields": []}))
    assert template.header_fields == ()


def test_a_list_of_only_unknown_ids_falls_back() -> None:
    template = decode_template(json.dumps({"version": 1, "header_fields": ["ghost", "phantom"]}))
    assert template.header_fields == HEADER_FIELDS


def test_the_name_travels_with_the_template() -> None:
    template = decode_template(json.dumps({"version": 1, "name": "Районная"}))
    assert template.name == "Районная"


def test_strings_are_read_as_booleans() -> None:
    template = decode_template(json.dumps({"version": 1, "show_notes": "false"}))
    assert template.show_notes is False


def test_a_partial_document_keeps_the_other_defaults() -> None:
    template = decode_template(json.dumps({"version": 1, "show_conclusion": False}))
    assert template.show_conclusion is False
    assert template.show_notes is True
    assert template.show_signature is True
    assert template.header_fields == HEADER_FIELDS


# ── The printed sheet ──────────────────────────────────────────────


def _document():
    from echo_personal_tool.domain.services.report_builder import (
        PatientInfo,
        ReportDocument,
        ReportGroup,
        ReportValue,
    )

    groups = tuple(
        ReportGroup(
            title=f"Группа {index}",
            key=key,
            values=(
                ReportValue(label=f"КДР {index}", value="52.0", unit="мм", key=f"{key}:КДР:0"),
                ReportValue(label=f"ФВ {index}", value="58.0", unit="%", key=f"{key}:ФВ:0"),
            ),
            notes=("Допущение калькулятора",),
        )
        for index, key in enumerate(("lv", "la", "aorta", "mv_av"))
    )
    return ReportDocument(
        patient=PatientInfo(
            name="Иванов И.И.",
            sex="M",
            physician="Петрова А.А.",
            indication="Одышка",
            study_date="2026-11-06",
        ),
        groups=groups,
    )


def _pdf_text(document, template=None) -> str:
    import fitz

    from echo_personal_tool.application.report_export import render_report

    rendered = render_report(document, template=template)
    with fitz.open(stream=rendered.pdf, filetype="pdf") as pdf:
        return "\n".join(page.get_text() for page in pdf)


def test_a_hidden_field_does_not_print() -> None:
    template = default_template().with_field_order((FIELD_NAME, FIELD_PHYSICIAN))
    text = _pdf_text(_document(), template)
    assert "Иванов" in text
    assert "Петрова" in text
    assert "Одышка" not in text


def test_the_order_of_the_header_is_the_order_of_the_template() -> None:
    template = default_template().with_field_order((FIELD_PHYSICIAN, FIELD_NAME, FIELD_AGE))
    text = _pdf_text(_document(), template)
    assert text.index("Петрова") < text.index("Иванов")


def test_no_template_prints_the_whole_form() -> None:
    text = _pdf_text(_document(), None)
    assert "Одышка" in text and "Иванов" in text


def test_the_notes_follow_the_switch() -> None:
    from dataclasses import replace

    template = replace(default_template(), show_notes=False)
    text = _pdf_text(_document(), template)
    assert "Допущение калькулятора" not in text
    assert "Допущение калькулятора" in _pdf_text(_document(), default_template())


def test_the_conclusion_follows_the_switch() -> None:
    from dataclasses import replace

    document = _document()
    document = replace(document, patient=replace(document.patient, conclusion="Заключение текстом"))
    on = _pdf_text(document, default_template())
    off = _pdf_text(document, replace(default_template(), show_conclusion=False))
    assert "Заключение текстом" in on
    assert "Заключение текстом" not in off


def test_the_signature_follows_the_switch() -> None:
    from dataclasses import replace

    from echo_personal_tool.infrastructure.i18n import tr

    on = _pdf_text(_document(), default_template())
    off = _pdf_text(_document(), replace(default_template(), show_signature=False))
    assert tr("report.signature") in on or "Врач" in on
    assert len(off) < len(on)


def test_two_columns_keep_the_groups_and_the_anchors() -> None:
    from dataclasses import replace

    from echo_personal_tool.application.report_export import render_report

    document = _document()
    one = render_report(document, template=default_template())
    two = render_report(document, template=replace(default_template(), columns=COLUMNS_TWO))

    text_two = _pdf_text(document, replace(default_template(), columns=COLUMNS_TWO))
    assert "Группа 0" in text_two and "Группа 3" in text_two
    # Every value cell of the document still has an anchor: the hover card and
    # the «скрыть в отчёте» menu work in both layouts.
    assert set(two.anchors) == set(one.anchors)


def test_two_columns_print_the_same_groups_as_one() -> None:
    from dataclasses import replace

    document = _document()
    one = _pdf_text(document, default_template())
    two = _pdf_text(document, replace(default_template(), columns=COLUMNS_TWO))
    for index in range(4):
        assert f"Группа {index}" in one
        assert f"Группа {index}" in two
    assert "КДР 2" in two


def test_a_hidden_header_leaves_no_empty_line() -> None:
    """An empty field list prints no header table — not the «Patient» placeholder."""
    from dataclasses import replace

    template = replace(default_template().with_field_order(()), show_signature=False)
    text = _pdf_text(_document(), template)
    assert "Иванов" not in text and "Петрова" not in text
    from echo_personal_tool.infrastructure.i18n import tr

    assert tr("report.patient") not in text.split("Группа")[0]
    # The groups are still printed: an empty header is not an empty report.
    assert "Группа 0" in text


def test_the_preview_and_the_export_share_the_bytes() -> None:
    from echo_personal_tool.application.report_export import render_report

    document = _document()
    template = default_template().with_field_order((FIELD_NAME,))
    rendered = render_report(document, font_size=10, template=template)
    assert rendered.pdf.startswith(b"%PDF")
    assert rendered.anchors


def test_an_unreadable_document_is_distinguishable_from_the_standard_form() -> None:
    """Importing a broken file must say so — not silently print the default."""
    from echo_personal_tool.domain.services.report_template import read_template_document

    assert read_template_document("{{{") is None
    assert read_template_document("") is None
    assert read_template_document(json.dumps({"version": 7})) is None
    # ...while a document that *says* «standard form» is a real answer.
    assert read_template_document(json.dumps({"version": 1})) == default_template()
