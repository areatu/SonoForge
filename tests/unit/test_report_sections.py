"""Tests for report-mode sections and «not filled» recommendations (UI-4 PR-2)."""

from __future__ import annotations

from echo_personal_tool.domain.protocols import ProjectionValue, StudyProjection
from echo_personal_tool.domain.services.report_sections import (
    RECOMMENDATIONS,
    SectionStatus,
    build_report_sections,
)


def _projection(*keys: str) -> StudyProjection:
    return StudyProjection(values={key: ProjectionValue(value=1.0) for key in keys})


def _by_id(sections):
    return {section.id: section for section in sections}


def test_empty_projection_lists_every_section_as_not_filled() -> None:
    sections = build_report_sections(None)
    assert [section.id for section in sections] == ["lv", "la", "ra", "diastolic", "mv_av", "tv_pv"]
    assert all(section.status is SectionStatus.EMPTY for section in sections)
    assert all(section.filled == 0 for section in sections)
    assert [section.total for section in sections] == [8, 3, 1, 5, 4, 1]


def test_partial_section_counts_only_present_keys() -> None:
    sections = _by_id(build_report_sections(_projection("lv.ivsd", "lv.lvedd")))
    lv = sections["lv"]
    assert lv.status is SectionStatus.PARTIAL
    assert (lv.filled, lv.total) == (2, 8)
    assert sum(item.filled for item in lv.items) == 2


def test_section_is_done_when_every_recommendation_is_present() -> None:
    lv_keys = [item.key for item in _by_id(build_report_sections(None))["lv"].items]
    lv = _by_id(build_report_sections(_projection(*lv_keys)))["lv"]
    assert lv.status is SectionStatus.DONE
    assert (lv.filled, lv.total) == (8, 8)
    assert all(item.filled for item in lv.items)


def test_recommendations_are_the_union_of_non_optional_protocol_steps() -> None:
    keys = [item.key for item in RECOMMENDATIONS]
    assert len(keys) == len(set(keys))
    assert len(keys) == 22
    # IVRT is optional in the diastolic protocol and must not be recommended.
    assert "lv.ivrt" not in keys
    # TR Vmax is shared by two protocols but listed once (tv_pv, first occurrence).
    assert keys.count("tr.vmax") == 1


def test_tool_less_steps_fall_into_their_anatomical_section() -> None:
    sections = _by_id(build_report_sections(None))
    assert "la.lavi" in [item.key for item in sections["la"].items]
    assert "ra.rap" in [item.key for item in sections["ra"].items]


def test_all_recommendations_present_makes_every_section_done() -> None:
    keys = [item.key for item in RECOMMENDATIONS]
    sections = build_report_sections(_projection(*keys))
    assert all(section.status is SectionStatus.DONE for section in sections)
    assert sum(section.total for section in sections) == len(keys)


def test_labels_follow_the_language() -> None:
    ru = _by_id(build_report_sections(None, "ru"))
    en = _by_id(build_report_sections(None, "en"))
    assert ru["lv"].title == "Левый желудочек"
    assert en["lv"].title == "Left Ventricle"
    assert ru["lv"].items[0].label == "МЖП"
    assert en["lv"].items[0].label == "IVSD"


def test_the_checklist_follows_the_study_profile() -> None:
    from echo_personal_tool.domain.services.report_sections import recommendations_for_profile

    echo = recommendations_for_profile("builtin.adult_echo")
    vascular = recommendations_for_profile("builtin.vascular")
    thyroid = recommendations_for_profile("builtin.thyroid")

    assert len(echo) == 22
    assert [item.key for item in vascular] == ["cca.imt_right", "cca.imt_left"]
    assert {item.section for item in vascular} == {"precerebral"}
    assert {item.section for item in thyroid} == {"thyroid"}
    assert all(item.tool_id for item in thyroid)
    assert any(item.protocol_id for item in echo)


def test_a_profile_section_lists_only_its_own_measurements() -> None:
    sections = build_report_sections(None, profile_id="builtin.kidney")
    assert [section.id for section in sections] == ["kidney"]
    assert sections[0].total == len(sections[0].items) == 14


def test_a_stale_value_is_visible_but_not_filled() -> None:
    projection = StudyProjection(values={"lv.ivsd": ProjectionValue(value=1.0, stale=True)})
    lv = _by_id(build_report_sections(projection))["lv"]

    assert lv.items[0].stale is True
    assert lv.items[0].filled is False
    assert (lv.filled, lv.total) == (0, 8)
    assert lv.status is SectionStatus.PARTIAL


def test_an_explicit_decision_is_not_missing_and_not_filled() -> None:
    from echo_personal_tool.domain.services.report_sections import CHECK_NOT_APPLICABLE, ChecklistDecision

    decision = ChecklistDecision(CHECK_NOT_APPLICABLE, "не входит в протокол")
    sections = build_report_sections(None, decisions={"lv.ivsd": decision})
    lv = _by_id(sections)["lv"]
    item = lv.items[0]

    assert (item.filled, item.stale, item.decision, item.reason) == (
        False,
        False,
        CHECK_NOT_APPLICABLE,
        "не входит в протокол",
    )
    assert lv.status is SectionStatus.PARTIAL
    assert lv.filled == 0


def test_a_section_is_done_when_every_item_is_measured_or_decided() -> None:
    from echo_personal_tool.domain.services.report_sections import CHECK_NOT_OBTAINED, ChecklistDecision

    keys = [item.key for item in RECOMMENDATIONS]
    decisions = {key: ChecklistDecision(CHECK_NOT_OBTAINED, "плохая визуализация") for key in keys[:3]}
    projection = _projection(*keys[3:])
    sections = build_report_sections(projection, decisions=decisions)

    assert all(section.status is SectionStatus.DONE for section in sections)


def test_summary_separates_all_five_states() -> None:
    from echo_personal_tool.domain.services.report_sections import (
        CHECK_NOT_APPLICABLE,
        ChecklistDecision,
        checklist_summary,
    )

    projection = StudyProjection(
        values={
            "lv.ivsd": ProjectionValue(value=1.0),
            "lv.lvedd": ProjectionValue(value=1.0, stale=True),
        }
    )
    sections = build_report_sections(
        projection,
        decisions={"lv.lvpwd": ChecklistDecision(CHECK_NOT_APPLICABLE, "не входит в протокол")},
    )
    summary = checklist_summary(sections, unreviewed=4)

    assert (summary.missing, summary.stale, summary.unreviewed) == (19, 1, 4)
    assert (summary.not_applicable, summary.not_obtained) == (1, 0)
    assert summary.complete is False
    assert summary.decided == 1


def test_the_summary_is_complete_only_without_missing_stale_or_unreviewed() -> None:
    from echo_personal_tool.domain.services.report_sections import checklist_summary

    complete = checklist_summary(
        build_report_sections(_projection(*(item.key for item in RECOMMENDATIONS))), unreviewed=0
    )
    assert complete.complete is True
    assert checklist_summary(build_report_sections(None)).complete is False


def test_an_incomplete_sheet_prints_a_warning() -> None:
    from echo_personal_tool.domain.services.report_sections import checklist_notices, checklist_summary
    from echo_personal_tool.domain.translation import tr

    incomplete = checklist_summary(build_report_sections(None), unreviewed=3)
    assert checklist_notices(incomplete) == (tr("report.notice.checklist_incomplete", missing=22, stale=0),)
    stale = checklist_summary(
        build_report_sections(StudyProjection(values={"lv.ivsd": ProjectionValue(value=1.0, stale=True)}))
    )
    assert checklist_notices(stale) == (tr("report.notice.checklist_incomplete", missing=21, stale=1),)
    complete = checklist_summary(build_report_sections(_projection(*(item.key for item in RECOMMENDATIONS))))
    assert checklist_notices(complete) == ()


def test_not_evaluated_values_print_the_reason_and_skip_stale_rows() -> None:
    from echo_personal_tool.domain.services.report_sections import (
        CHECK_NOT_APPLICABLE,
        CHECK_NOT_OBTAINED,
        ChecklistDecision,
        not_evaluated_values,
    )
    from echo_personal_tool.domain.translation import tr

    projection = StudyProjection(values={"lv.lvedd": ProjectionValue(value=1.0, stale=True)})
    sections = build_report_sections(projection)
    decisions = {
        "lv.ivsd": ChecklistDecision(CHECK_NOT_APPLICABLE, "не входит в протокол"),
        "lv.lvedd": ChecklistDecision(CHECK_NOT_OBTAINED, "плохая визуализация"),
    }
    rows = not_evaluated_values(sections, set(decisions), value_text="не оценивалось", decisions=decisions)

    assert [row.label for row in rows] == ["МЖП"]
    assert rows[0].value == f"{tr('report.checklist.not_applicable')} — не входит в протокол"


def test_protocol_steps_carry_view_and_frame_hints() -> None:
    lv = _by_id(build_report_sections(None))["lv"]
    ivsd = next(item for item in lv.items if item.key == "lv.ivsd")
    edv = next(item for item in lv.items if item.key == "lv.edv_a4c")

    assert ivsd.frame_hint == "ed"
    assert (edv.view, edv.frame_hint) == ("A4C", "ed")
