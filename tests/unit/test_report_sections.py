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
