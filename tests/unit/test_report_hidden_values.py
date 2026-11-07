"""Item 9 of the 2026-11-06 list: hide a single parameter in the report.

The owner wants to drop a row from the printed protocol without deleting the
measurement.  The sheet is exact PDF bytes (S-11), so nothing is painted over:
rows carry a stable ``group:label:ordinal`` key, the document is filtered by
that key once, and the preview, the PDF, the CSV and the JSON lose the same
rows.  Hiding is a report edit — it lives in the tab and dies with the study.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.application.calculator_inputs import resolve_standalone_inputs
from echo_personal_tool.domain.calculators import evaluate
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.report_builder import (
    GROUP_CALCULATIONS,
    GROUP_VESSELS,
    PatientInfo,
    ReportGroup,
    ReportValue,
    build_report_document,
    build_report_groups,
    without_values,
)
from echo_personal_tool.infrastructure.i18n import set_language

_EXAMPLE = {"lvot_d": 2.0, "lvot_vti": 20.0, "av_vti": 100.0, "hr": 70.0, "bsa": 1.9}


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


def _snapshot() -> MeasurementSnapshot:
    return MeasurementSnapshot(calculations=evaluate(resolve_standalone_inputs(_EXAMPLE)))


def _document(hidden=()):
    return build_report_document(_snapshot(), PatientInfo(sex="M"), sex="M", hidden_keys=hidden)


def _rows(document) -> list[tuple[str, str]]:
    return [(value.key, value.label) for group in document.groups for value in group.values]


def _calc_key(document) -> str:
    group = next(group for group in document.groups if group.key == GROUP_CALCULATIONS)
    return group.values[0].key


def test_every_row_of_the_builder_carries_a_stable_key() -> None:
    document = _document()
    rows = _rows(document)
    assert rows
    assert all(key for key, _label in rows)
    assert len({key for key, _label in rows}) == len(rows)
    # ``group:label:ordinal`` — the shape the tab stores.
    assert all(key.count(":") >= 2 for key, _label in rows)


def test_the_key_does_not_move_when_another_row_is_hidden() -> None:
    """Positional ids would shift; the key of a row must not."""
    full = _document()
    key = _rows(full)[3][0]
    hidden = _document(hidden=[key])
    assert key not in {row_key for row_key, _label in _rows(hidden)}
    # Every surviving row kept the key it had in the full document.
    assert {row_key for row_key, _ in _rows(hidden)} == {row_key for row_key, _ in _rows(full)} - {key}


def test_hiding_removes_the_row_from_the_document() -> None:
    full = _document()
    key = _calc_key(full)
    label = dict((row_key, row_label) for row_key, row_label in _rows(full))[key]

    hidden = _document(hidden=[key])

    assert label not in [row_label for _key, row_label in _rows(hidden)]
    assert key not in {row_key for row_key, _ in _rows(hidden)}


def test_hiding_is_reversible() -> None:
    full = _document()
    key = _calc_key(full)
    hidden = _document(hidden=[key])
    assert _rows(hidden) != _rows(full)
    restored = _document(hidden=[])
    assert _rows(restored) == _rows(full)


def test_an_unknown_key_changes_nothing() -> None:
    full = _document()
    assert _rows(_document(hidden=["ghost:row:0"])) == _rows(full)
    # A study reload must not resurrect a row that no longer exists, and must
    # not lose the rest of the document either.
    assert without_values(full, ["ghost:row:0"]) is full


def test_a_group_that_loses_every_row_disappears() -> None:
    from echo_personal_tool.domain.services.report_builder import ReportDocument

    document = ReportDocument(
        patient=PatientInfo(),
        groups=(
            ReportGroup(
                title="Сосуды", key=GROUP_VESSELS, values=(ReportValue(label="PSV", value="1.0", key="v:PSV:0"),)
            ),
            ReportGroup(
                title="Расчёты", key=GROUP_CALCULATIONS, values=(ReportValue(label="SV", value="70", key="c:SV:0"),)
            ),
        ),
    )
    trimmed = without_values(document, ["v:PSV:0"])
    assert [group.key for group in trimmed.groups] == [GROUP_CALCULATIONS]


def test_the_filter_keeps_the_notes_of_a_surviving_group() -> None:
    full = _document()
    key = _calc_key(full)
    hidden = _document(hidden=[key])
    full_notes = next(group.notes for group in full.groups if group.key == GROUP_CALCULATIONS)
    hidden_notes = next(group.notes for group in hidden.groups if group.key == GROUP_CALCULATIONS)
    assert hidden_notes == full_notes


def test_without_values_leaves_a_clean_document_untouched() -> None:
    group = ReportGroup(
        title="Прочее",
        key="other",
        values=(ReportValue(label="X", value="1.0", key="other:X:0"),),
    )
    from echo_personal_tool.domain.services.report_builder import ReportDocument

    document = ReportDocument(patient=PatientInfo(), groups=(group,))
    assert without_values(document, []) is document


def test_two_rows_with_the_same_label_get_different_keys() -> None:
    """Two planimeter contours of one frame must stay apart (and the p.10 link)."""
    groups = build_report_groups(_snapshot(), sex="M")
    labels = [value.label for group in groups for value in group.values]
    duplicated = {label for label in labels if labels.count(label) > 1}
    if duplicated:
        keys = [value.key for group in groups for value in group.values if value.label in duplicated]
        assert len(set(keys)) == len(keys)


def test_the_exports_lose_the_same_rows(tmp_path) -> None:
    import json

    import fitz

    from echo_personal_tool.application.report_export import (
        export_report_document_pdf,
        render_report_csv,
        render_report_json,
    )

    full = _document()
    key = _calc_key(full)
    label = dict((row_key, row_label) for row_key, row_label in _rows(full))[key]
    hidden = _document(hidden=[key])

    payload = json.loads(render_report_json(hidden, tmp_path / "report.json").read_text(encoding="utf-8"))
    labels = [row["label"] for group in payload["groups"] for row in group["values"]]
    assert label not in labels

    csv_text = render_report_csv(hidden, tmp_path / "report.csv").read_text(encoding="utf-8")
    assert label not in csv_text

    pdf_path = export_report_document_pdf(hidden, tmp_path / "report.pdf")
    with fitz.open(pdf_path) as pdf:
        text = "\n".join(page.get_text() for page in pdf)
    assert label not in text
