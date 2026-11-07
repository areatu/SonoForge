"""Study profiles (item 11 of the 2026-11-06 list).

The owner asked for buttons «Эхокардиография / УЗИ артерий / УЗИ ОБП и почек /
УЗИ щитовидной железы» that change the tool panel and the report.  A profile is
a *statement about the study*, so it filters the stored layout instead of
rewriting it: switching loses nothing, a measurement made before the switch
stays in the study, and switching back restores the previous panel exactly.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.study_profiles import (
    DEFAULT_PROFILE_ID,
    PROFILE_ORDER,
    PROFILES,
    SECTION_VESSELS,
    STUDY_PROFILE_ABDOMEN,
    STUDY_PROFILE_ECHO,
    STUDY_PROFILE_KIDNEY,
    STUDY_PROFILE_THYROID,
    STUDY_PROFILE_VASCULAR,
    is_explicit,
    normalize_profile_id,
    section_keys,
    study_profile,
)
from echo_personal_tool.domain.tool_layout_v3 import default_layout
from echo_personal_tool.domain.tool_panel_view import panel_view


def _sections(profile_id: str) -> list[str]:
    view = panel_view(default_layout(), "2d", study_profile_id=profile_id)
    return [section.key for section in view.sections]


def test_the_five_profiles_are_the_ones_the_owner_listed() -> None:
    assert PROFILE_ORDER == (
        STUDY_PROFILE_ECHO,
        STUDY_PROFILE_VASCULAR,
        STUDY_PROFILE_ABDOMEN,
        STUDY_PROFILE_KIDNEY,
        STUDY_PROFILE_THYROID,
    )
    assert set(PROFILES) == set(PROFILE_ORDER)
    assert DEFAULT_PROFILE_ID == STUDY_PROFILE_ECHO


def test_every_profile_names_itself_and_its_report_format() -> None:
    for profile_id, profile in PROFILES.items():
        assert profile.id == profile_id
        assert profile.title_key == f"study_profile.{profile_id.split('.', 1)[1]}"
    # A kidney study prints a kidney protocol, not a generic ultrasound one.
    assert PROFILES[STUDY_PROFILE_VASCULAR].report_profile_id == "vascular"
    assert PROFILES[STUDY_PROFILE_ABDOMEN].report_profile_id == "abdomen"
    assert PROFILES[STUDY_PROFILE_KIDNEY].report_profile_id == "kidney"
    assert PROFILES[STUDY_PROFILE_THYROID].report_profile_id == "thyroid"
    assert PROFILES[STUDY_PROFILE_ECHO].report_profile_id == "echo"


def test_the_cardiac_profile_does_not_show_the_vascular_block() -> None:
    """The owner's complaint: «Сосуды» crowded the echocardiography panel."""
    assert SECTION_VESSELS not in section_keys(STUDY_PROFILE_ECHO)
    assert SECTION_VESSELS in section_keys(STUDY_PROFILE_VASCULAR)
    assert SECTION_VESSELS not in _sections(STUDY_PROFILE_ECHO)
    assert SECTION_VESSELS in _sections(STUDY_PROFILE_VASCULAR)


def test_the_vascular_profile_drops_the_cardiac_sections() -> None:
    sections = _sections(STUDY_PROFILE_VASCULAR)
    assert "lv" not in sections
    assert "diastolic" not in sections
    assert "general" in sections


def test_the_non_cardiac_profiles_keep_calipers_and_planimetry() -> None:
    """Abdominal and thyroid studies need the general tools, not the echo ones."""
    for profile_id in (STUDY_PROFILE_ABDOMEN, STUDY_PROFILE_THYROID):
        sections = _sections(profile_id)
        assert "general" in sections
        assert "lv" not in sections


def test_only_the_cardiac_profile_claims_a_cardiac_study() -> None:
    assert study_profile(STUDY_PROFILE_ECHO).cardiac is True
    assert all(not PROFILES[profile_id].cardiac for profile_id in PROFILE_ORDER[1:])


def test_the_report_format_follows_the_profile() -> None:
    assert study_profile(STUDY_PROFILE_ECHO).report_profile_id == "echo"
    # Each organ study prints its own protocol, not the generic ultrasound one.
    assert study_profile(STUDY_PROFILE_VASCULAR).report_profile_id == "vascular"
    assert study_profile(STUDY_PROFILE_ABDOMEN).report_profile_id == "abdomen"
    assert study_profile(STUDY_PROFILE_KIDNEY).report_profile_id == "kidney"
    assert study_profile(STUDY_PROFILE_THYROID).report_profile_id == "thyroid"


def test_an_unknown_id_reads_as_the_default() -> None:
    assert normalize_profile_id("thyroid") == STUDY_PROFILE_ECHO
    assert normalize_profile_id("") == STUDY_PROFILE_ECHO
    assert normalize_profile_id(None) == STUDY_PROFILE_ECHO
    assert study_profile("nope").id == STUDY_PROFILE_ECHO


def test_only_a_real_choice_is_explicit() -> None:
    assert is_explicit(STUDY_PROFILE_VASCULAR) is True
    assert is_explicit("") is False
    assert is_explicit(None) is False
    # An unknown id is not a choice: it falls back to the default.
    assert is_explicit("thyroid") is False


def test_user_sections_survive_every_profile() -> None:
    profile = study_profile(STUDY_PROFILE_ECHO)
    assert profile.allows("custom.1") is True
    assert profile.allows("custom.12") is True


def test_switching_back_restores_the_panel_exactly() -> None:
    before = [section.key for section in panel_view(default_layout(), "2d").sections]
    _sections(STUDY_PROFILE_VASCULAR)
    after = [section.key for section in panel_view(default_layout(), "2d").sections]
    assert after == before


def test_the_hidden_tools_counter_survives_the_filter() -> None:
    """A filter is not a deletion: the layout document is untouched."""
    layout = default_layout()
    keys_before = [section.key for section in layout.context("common").sections]
    panel_view(layout, "2d", study_profile_id=STUDY_PROFILE_THYROID)
    assert [section.key for section in layout.context("common").sections] == keys_before


def test_the_vessels_context_is_still_reachable_in_the_vascular_profile() -> None:
    view = panel_view(default_layout(), "vessels", study_profile_id=STUDY_PROFILE_VASCULAR)
    assert [section.key for section in view.sections] == ["general", SECTION_VESSELS, "precerebral", "kidney"]


@pytest.mark.parametrize("profile_id", PROFILE_ORDER)
def test_every_profile_always_shows_something(profile_id: str) -> None:
    assert _sections(profile_id)


def test_the_vascular_context_is_never_filtered_away() -> None:
    """Choosing «Сосуды» is asking for that block, whatever the study type."""
    for profile_id in ("", STUDY_PROFILE_ECHO, STUDY_PROFILE_ABDOMEN):
        view = panel_view(default_layout(), "vessels", study_profile_id=profile_id)
        assert SECTION_VESSELS in [section.key for section in view.sections]
