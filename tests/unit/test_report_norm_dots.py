"""Norm dots of the report values (issue #277, spec §4.7).

The report rows carry their gradation as data (``ReportValue.norm_grade``) so
the PDF sheet can paint the dot next to the value and the preview card can
repeat it — the same handbook scale the panel rows and the S2 card show.  The
``how_to`` texts of the handbook stay with the clinician and are not part of
this slice.
"""

from __future__ import annotations

from echo_personal_tool.domain.services.report_builder import _value
from echo_personal_tool.domain.services.report_grades import norm_grade_for
from echo_personal_tool.domain.services.report_document import ReportGroup, ReportValue
from echo_personal_tool.domain.services.reference_topics import grade_fill_hex


def test_norm_grade_for_returns_the_handbook_gradation() -> None:
    # КДР ЛЖ: 48 мм у женщины — норма, 70 мм у мужчины — тяжёлое расширение.
    assert norm_grade_for("lvedd", 48.0, "F") == "Normal"
    assert norm_grade_for("lvedd", 70.0, "M") == "Severe"


def test_norm_grade_for_is_empty_without_binding_or_value() -> None:
    assert norm_grade_for("lvedd", None, "F") == ""
    assert norm_grade_for("no such label", 5.0, "") == ""
    # A value below every cut has no gradation — the dot stays off.  (The
    # severe cut is open-ended upwards, so a huge value *is* «Severe».)
    assert norm_grade_for("lvedd", 1.0, "F") == ""


def test_grade_fill_hex_matches_the_ui_scale() -> None:
    assert grade_fill_hex("Normal") == "#16a34a"
    assert grade_fill_hex("Норма") == "#16a34a"
    assert grade_fill_hex("Severe") == "#dc2626"
    assert grade_fill_hex("Тяжёлое") == "#dc2626"
    assert grade_fill_hex("") is None


def test_report_value_carries_the_grade() -> None:
    row = _value("LVIDd", "lv.lvedd", 48.0, "mm", sex="F")
    assert row is not None
    assert row.norm, "the norm column must stay"
    assert row.norm_grade == "Normal"
    row = _value("LVIDd", "lv.lvedd", None, "mm", sex="F")
    assert row is None, "no value — no row at all"


def test_pdf_value_cell_paints_the_norm_dot() -> None:
    from echo_personal_tool.infrastructure.measurement_report_pdf import _group_table, _report_styles

    styles = _report_styles("Helvetica", 10)
    group = ReportGroup(
        title="LV",
        key="lv",
        values=(
            ReportValue(label="LVIDd", value="48", unit="mm", norm="36–51 мм", norm_grade="Normal"),
            ReportValue(label="IVSd", value="12", unit="mm", norm="6–10 мм", norm_grade=""),
        ),
    )
    table = _group_table(group, styles, 10)
    first_value = table._cellvalues[1][1]  # noqa: SLF001 - the test reads the built cell
    second_value = table._cellvalues[2][1]  # noqa: SLF001
    assert "●" in first_value.text and "#16a34a" in first_value.text
    assert "●" not in second_value.text, "a row without a grade gets no dot"
