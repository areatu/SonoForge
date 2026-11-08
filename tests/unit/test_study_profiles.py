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
    SECTION_ABDOMEN,
    SECTION_KIDNEY,
    SECTION_THYROID,
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


def _tool_ids(profile_id: str, context: str = "2d") -> list[str]:
    view = panel_view(default_layout(), context, study_profile_id=profile_id)
    return [tool.id for section in view.sections for tool in section.items]


def test_the_kidney_profile_shows_exactly_the_requested_measurements() -> None:
    """Five linear kidney sizes per side plus the bladder set (item 11)."""
    view = panel_view(default_layout(), "2d", study_profile_id=STUDY_PROFILE_KIDNEY)
    assert [section.key for section in view.sections] == ["general", "kidney"]
    assert [tool.id for tool in view.sections[0].items] == [
        "tool.caliper",
        "tool.area",
        "tool.organ_volume",
    ]
    assert [tool.id for tool in view.sections[1].items] == [
        "kidney.right_length",
        "kidney.right_width",
        "kidney.right_thickness",
        "kidney.right_parenchyma",
        "kidney.right_sinus",
        "kidney.left_length",
        "kidney.left_width",
        "kidney.left_thickness",
        "kidney.left_parenchyma",
        "kidney.left_sinus",
        "bladder.length",
        "bladder.width",
        "bladder.depth",
        "bladder.wall",
    ]
    # The old «высота» and the echo tools are not part of the renal study.
    assert "bladder.height" not in _tool_ids(STUDY_PROFILE_KIDNEY)
    assert "hr.auto" not in _tool_ids(STUDY_PROFILE_KIDNEY)
    assert "tool.volume" not in _tool_ids(STUDY_PROFILE_KIDNEY)


def test_the_kidney_ri_is_reachable_on_a_doppler_frame() -> None:
    """RI is two clicks (PSV/EDV) and only makes sense with a spectrum."""
    assert _tool_ids(STUDY_PROFILE_KIDNEY, "doppler") == [
        "vessel.renal_right",
        "vessel.renal_left",
    ]


def test_the_abdomen_profile_no_longer_carries_the_renal_block() -> None:
    view = panel_view(default_layout(), "2d", study_profile_id=STUDY_PROFILE_ABDOMEN)
    assert [section.key for section in view.sections] == ["general", "abdomen"]
    ids = [tool.id for tool in view.sections[1].items]
    assert ids == [
        "liver.llt",
        "liver.rlt",
        "liver.kvr",
        "gallbladder.length",
        "gallbladder.width",
        "gallbladder.wall",
        "portal_vein.diameter",
        "bile_duct.diameter",
        "pancreas.head",
        "pancreas.body",
        "pancreas.tail",
        "pancreas.duct",
        "abd_aorta.diameter",
    ]
    assert not any(tool_id.startswith(("kidney.", "bladder.")) for tool_id in ids)


def test_the_thyroid_profile_shows_both_lobes_and_the_isthmus() -> None:
    view = panel_view(default_layout(), "2d", study_profile_id=STUDY_PROFILE_THYROID)
    assert [section.key for section in view.sections] == ["general", "thyroid"]
    assert [tool.id for tool in view.sections[1].items] == [
        "thyroid.r_thick",
        "thyroid.r_width",
        "thyroid.r_height",
        "thyroid.l_thick",
        "thyroid.l_width",
        "thyroid.l_height",
        "thyroid.isthmus",
    ]


@pytest.mark.parametrize("profile_id", (STUDY_PROFILE_ABDOMEN, STUDY_PROFILE_KIDNEY, STUDY_PROFILE_THYROID))
def test_the_organ_profiles_keep_only_the_general_tools_they_need(profile_id: str) -> None:
    """The owner's rule: no heart rate, M-mode, comparisons or spline volume."""
    ids = set(_tool_ids(profile_id))
    assert {"tool.caliper", "tool.area", "tool.organ_volume"} <= ids
    assert not ids & {"hr.auto", "hr.doppler", "tool.volume", "tool.diameter_compare", "tool.area_compare"}


def test_each_study_prints_only_its_own_protocol() -> None:
    """The sheet header must not offer «ЭхоКГ» on a renal protocol."""
    assert study_profile(STUDY_PROFILE_KIDNEY).report_profile_ids == ("kidney",)
    assert study_profile(STUDY_PROFILE_ABDOMEN).report_profile_ids == ("abdomen",)
    assert study_profile(STUDY_PROFILE_THYROID).report_profile_ids == ("thyroid",)
    # The cardiac study keeps the generic format for its DICOM auto-choice.
    assert study_profile(STUDY_PROFILE_ECHO).report_profile_ids == ("echo", "ultrasound_generic")


def _panel_tool_ids(profile_id: str) -> set[str]:
    view = panel_view(default_layout(), "2d", study_profile_id=profile_id)
    return {item.id for section in view.sections for item in section.items}


def test_the_organ_volume_tool_is_offered_by_the_organ_studies_only() -> None:
    """Ordinary-ultrasound volumetry belongs to the organ studies.

    The cardiac and vascular panels keep their own volume instruments; the
    «объём по трём измерениям» button next to them would be an extra one.
    """
    for profile_id in (STUDY_PROFILE_ABDOMEN, STUDY_PROFILE_KIDNEY, STUDY_PROFILE_THYROID):
        assert "tool.organ_volume" in _panel_tool_ids(profile_id), profile_id
    for profile_id in (STUDY_PROFILE_ECHO, STUDY_PROFILE_VASCULAR):
        assert "tool.organ_volume" not in _panel_tool_ids(profile_id), profile_id


def test_the_general_section_of_an_organ_study_is_caliper_area_and_volume() -> None:
    """«Общие» of a non-cardiac organ study: line, area, volume by three sizes."""
    for profile_id in (STUDY_PROFILE_ABDOMEN, STUDY_PROFILE_KIDNEY, STUDY_PROFILE_THYROID):
        view = panel_view(default_layout(), "2d", study_profile_id=profile_id)
        general = next(section for section in view.sections if section.key == "general")
        assert [item.id for item in general.items] == ["tool.caliper", "tool.area", "tool.organ_volume"]


def _profile_caliper_tools(profile_id: str) -> list[object]:
    """Distance tools the profile shows, with their stored caliper label."""
    from echo_personal_tool.domain.measurement_catalog import CATALOG

    profile = study_profile(profile_id)
    tools = []
    for tool_id in profile.tools or ():
        tool = CATALOG[tool_id]
        if tool.payload.caliper_label:
            tools.append(tool)
    return tools


@pytest.mark.parametrize(
    "profile_id",
    [STUDY_PROFILE_ABDOMEN, STUDY_PROFILE_KIDNEY, STUDY_PROFILE_THYROID],
    ids=["abdomen", "kidney", "thyroid"],
)
def test_every_indicator_of_a_profile_reaches_the_report(profile_id: str) -> None:
    """The owner's acceptance criterion: a button and a report row for each size.

    Each distance tool of the profile draws a caliper; the same caliper must
    come out of the report of that study under its own label, or the physician
    measures into nothing.
    """
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import PatientInfo, build_report_document
    from echo_personal_tool.infrastructure.i18n import set_language, tr

    set_language("ru")
    tools = _profile_caliper_tools(profile_id)
    assert tools
    snapshot = MeasurementSnapshot(
        linear_measurements=tuple(
            LinearMeasurement(label=tool.payload.caliper_label, pixel_length=40.0, millimeter_length=20.0)
            for tool in tools
        )
    )
    document = build_report_document(
        snapshot,
        PatientInfo(sex="M"),
        sex="M",
        profile_id=study_profile(profile_id).report_profile_id,
    )
    rows = {value.label for group in document.groups for value in group.values}
    missing = [tr(tool.label_key) for tool in tools if tr(tool.label_key) not in rows]
    assert missing == []


def _legacy_document_without_organ_blocks():
    """A stored layout written before the organ sections existed.

    The version-3 document of an older build can only name the sections it
    knew; the renal, abdominal and thyroid blocks were new in item 11, and
    «объём по трём измерениям» was a new tool of the general section.
    """
    from types import MappingProxyType

    from echo_personal_tool.domain.tool_layout_v3 import (
        BUILTIN_PROFILE_ID,
        CONTEXT_COMMON,
        Context,
        Layout,
        Profile,
        Section,
        ToolItem,
    )

    profile = Profile(
        id=BUILTIN_PROFILE_ID,
        name="Старый документ",
        contexts=MappingProxyType(
            {
                CONTEXT_COMMON: Context(
                    CONTEXT_COMMON,
                    inherit=False,
                    sections=(
                        Section(key="general", items=(ToolItem("tool.caliper"), ToolItem("tool.area"))),
                        Section(key="lv", items=(ToolItem("lv.linear_ed"),)),
                    ),
                )
            }
        ),
    )
    return Layout(active_profile=BUILTIN_PROFILE_ID, profiles=(profile,))


@pytest.mark.parametrize(
    "profile_id",
    [STUDY_PROFILE_ABDOMEN, STUDY_PROFILE_KIDNEY, STUDY_PROFILE_THYROID],
    ids=["abdomen", "kidney", "thyroid"],
)
def test_an_old_layout_still_shows_the_block_of_the_chosen_profile(profile_id: str) -> None:
    """The panel must add the tools of a profile, not only hide the others.

    The owner opened «УЗИ почек» and saw «Общие» with two calipers: the stored
    layout predated the renal block, so filtering alone had nothing to keep.
    """
    from echo_personal_tool.domain.measurement_catalog import CATALOG, CTX_2D

    profile = study_profile(profile_id)
    view = panel_view(_legacy_document_without_organ_blocks(), "2d", study_profile_id=profile_id)
    keys = [section.key for section in view.sections]
    organ_section = profile.sections[-1]
    assert organ_section in keys
    shown = {item.id for section in view.sections for item in section.items}

    # Every organ tool the profile lists, in the 2D context, is on the panel.
    expected = {
        tool_id
        for tool_id in profile.tools or ()
        if CATALOG[tool_id].section == organ_section and CTX_2D in CATALOG[tool_id].contexts
    }
    assert expected
    assert expected <= shown
    # The general section of an organ study also gains «объём по 3».
    assert "tool.organ_volume" in shown


def test_an_old_layout_does_not_leak_the_organ_blocks_into_echocardiography() -> None:
    view = panel_view(_legacy_document_without_organ_blocks(), "2d", study_profile_id=STUDY_PROFILE_ECHO)
    keys = [section.key for section in view.sections]
    assert SECTION_KIDNEY not in keys
    assert SECTION_THYROID not in keys
    assert SECTION_ABDOMEN not in keys
