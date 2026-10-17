"""Layout v2: the migration of the 16 flag combinations, the document and the slot table.

UI-2 PR-1, spec §8.1. PR-2 drops the v1 projection (``flags_for``) with the
checkbox menu and pins the stored-key precedence (``resolve_document``).
Pure tests: no Qt, no window.
"""

from __future__ import annotations

import itertools
import json

import pytest

from echo_personal_tool.presentation.layout.presets import (
    LAYOUT_VERSION,
    PRESET_CLASSIC,
    PRESET_FILMSTRIP,
    PRESET_MIRRORED,
    PRESETS,
    SLOT_GALLERY,
    SLOT_PANES,
    SLOT_RAIL,
    SLOT_SPLIT,
    SLOT_TABLE,
    SLOT_TOOL_PANEL,
    SLOT_VIEWER,
    LayoutConfigV2,
    migrate_v1,
    resolve_document,
    slot_plan,
)

_FLAG_NAMES = ("swap_places", "gallery_horizontal", "activity_bar", "status_bar_visible")


def _spec_expectation(swap: bool, gallery: bool, activity: bool, status: bool) -> tuple[str, str, bool]:
    """The rules of spec §8.1, written out independently of the code under test."""
    if gallery:
        preset = PRESET_FILMSTRIP  # the filmstrip wins over the mirror
    elif swap:
        preset = PRESET_MIRRORED
    else:
        preset = PRESET_CLASSIC
    tool_buttons = "rail" if activity else "auto"  # the rail sits over the preset
    return preset, tool_buttons, status


# ── Migration v1 → v2: all 16 combinations of the four persisted flags ────────


@pytest.mark.parametrize(
    ("swap", "gallery", "activity", "status"),
    list(itertools.product((False, True), repeat=4)),
    ids=lambda value: str(value),
)
def test_migration_covers_all_sixteen_combinations(swap: bool, gallery: bool, activity: bool, status: bool) -> None:
    flags = {
        "swap_places": swap,
        "gallery_horizontal": gallery,
        "activity_bar": activity,
        "status_bar_visible": status,
    }
    document = migrate_v1(flags)
    preset, tool_buttons, status_visible = _spec_expectation(swap, gallery, activity, status)
    assert document.preset == preset
    assert document.tool_buttons == tool_buttons
    assert document.status_bar_visible is status_visible


def test_all_off_is_the_classic_preset_with_automatic_buttons() -> None:
    assert migrate_v1({}) == LayoutConfigV2()
    assert migrate_v1({"swap_places": False, "gallery_horizontal": False, "activity_bar": False}) == LayoutConfigV2()


def test_multiview_is_not_part_of_the_migration() -> None:
    assert migrate_v1({"multiview": True}) == LayoutConfigV2()


def test_migration_ignores_non_boolean_values() -> None:
    document = migrate_v1({"swap_places": "yes", "gallery_horizontal": 1, "status_bar_visible": None})
    assert document == LayoutConfigV2()


# ── The version-2 document ────────────────────────────────────────────────────


def test_document_round_trips_through_json() -> None:
    document = LayoutConfigV2(preset=PRESET_MIRRORED, tool_buttons="rail", status_bar_visible=False)
    restored = LayoutConfigV2.from_json(document.to_json())
    assert restored == document


def test_document_carries_the_version_number() -> None:
    raw = json.loads(LayoutConfigV2().to_json())
    assert raw["version"] == LAYOUT_VERSION == 2


@pytest.mark.parametrize("raw", ["", "not json", "[]", "42", json.dumps({"preset": "classic"})])
def test_non_version_two_text_is_not_a_document(raw: str) -> None:
    assert LayoutConfigV2.from_json(raw) is None


def test_unknown_preset_falls_back_to_the_default_without_losing_other_fields() -> None:
    raw = json.dumps({"version": 2, "preset": "future-preset", "status_bar_visible": False})
    document = LayoutConfigV2.from_json(raw)
    assert document is not None
    assert document.preset == PRESET_CLASSIC
    assert document.status_bar_visible is False


def test_wrong_type_falls_back_to_the_default() -> None:
    raw = json.dumps({"version": 2, "status_bar_visible": "no", "tool_buttons": 3})
    assert LayoutConfigV2.from_json(raw) == LayoutConfigV2()


def test_constructor_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        LayoutConfigV2(preset="sideways")
    with pytest.raises(ValueError):
        LayoutConfigV2(tool_buttons="floating")
    with pytest.raises(ValueError):
        LayoutConfigV2(tool_labels="big")


def test_rail_is_true_only_for_the_rail_mode() -> None:
    assert LayoutConfigV2(tool_buttons="rail").rail is True
    assert LayoutConfigV2(tool_buttons="auto").rail is False
    # «row» and «panel» belong to UI-2 PR-3; until then they are not the rail.
    assert LayoutConfigV2(tool_buttons="panel").rail is False


# ── The slot table ─────────────────────────────────────────────────────────────


def test_table_has_one_plan_per_preset_rail_and_multiview_state() -> None:
    assert len(SLOT_TABLE) == len(PRESETS) * 2 * 2
    for preset, rail, multiview in itertools.product(PRESETS, (False, True), (False, True)):
        assert (preset, rail, multiview) in SLOT_TABLE


@pytest.mark.parametrize(("preset", "rail", "multiview"), list(SLOT_TABLE))
def test_every_plan_places_each_part_once(preset: str, rail: bool, multiview: bool) -> None:
    plan = SLOT_TABLE[(preset, rail, multiview)]
    side = [slot for slot in (plan.left, plan.right, plan.bottom) if slot is not None]
    assert len(side) == len(set(side)), side
    # The gallery is always on screen, and the tool panel or the rail too.
    assert SLOT_GALLERY in side
    assert SLOT_TOOL_PANEL in side or SLOT_RAIL in side or plan.center == SLOT_SPLIT


@pytest.mark.parametrize(("preset", "rail", "multiview"), list(SLOT_TABLE))
def test_centre_is_the_viewer_column(preset: str, rail: bool, multiview: bool) -> None:
    plan = SLOT_TABLE[(preset, rail, multiview)]
    if multiview:
        assert plan.center == SLOT_PANES
    else:
        assert plan.center in (SLOT_VIEWER, SLOT_SPLIT)


def test_only_the_classic_panel_layout_keeps_the_tool_panel_in_the_splitter() -> None:
    split = [key for key, plan in SLOT_TABLE.items() if plan.center == SLOT_SPLIT]
    assert split == [(PRESET_CLASSIC, False, False)]


def test_bottom_strip_belongs_to_the_filmstrip_only() -> None:
    for (preset, _rail, _multiview), plan in SLOT_TABLE.items():
        assert (plan.bottom == SLOT_GALLERY) is (preset == PRESET_FILMSTRIP)


def test_multiview_changes_only_the_centre_and_the_classic_right_slot() -> None:
    """Pins the v1 rendering: Multiview replaces the viewer, sides stay as they were."""
    for preset, rail in itertools.product(PRESETS, (False, True)):
        single = SLOT_TABLE[(preset, rail, False)]
        multi = SLOT_TABLE[(preset, rail, True)]
        assert multi.bottom == single.bottom
        if (preset, rail) == (PRESET_CLASSIC, False):
            assert single.right is None and multi.right == SLOT_TOOL_PANEL
        else:
            assert multi.left == single.left
            assert multi.right == single.right


def test_slot_plan_reads_the_document_and_the_session_flag() -> None:
    document = LayoutConfigV2(preset=PRESET_FILMSTRIP)
    assert slot_plan(document, multiview=False) == SLOT_TABLE[(PRESET_FILMSTRIP, False, False)]
    assert slot_plan(document, multiview=True) == SLOT_TABLE[(PRESET_FILMSTRIP, False, True)]


# ── resolve_document: the stored-key precedence (UI-2 PR-2) ────────────────


def test_resolve_prefers_the_version_two_document() -> None:
    v2 = LayoutConfigV2(preset=PRESET_MIRRORED).to_json()
    v1 = json.dumps({"gallery_horizontal": True})
    assert resolve_document(v2, v1) == LayoutConfigV2(preset=PRESET_MIRRORED)


def test_resolve_migrates_version_one_when_version_two_is_empty() -> None:
    v1 = json.dumps({"gallery_horizontal": True, "swap_places": True, "activity_bar": True})
    assert resolve_document("", v1) == LayoutConfigV2(preset=PRESET_FILMSTRIP, tool_buttons="rail")


def test_resolve_falls_back_to_version_one_when_version_two_is_unreadable() -> None:
    v1 = json.dumps({"swap_places": True})
    assert resolve_document("not json", v1) == LayoutConfigV2(preset=PRESET_MIRRORED)


def test_resolve_defaults_when_both_keys_are_empty() -> None:
    assert resolve_document("", "") == LayoutConfigV2()


def test_resolve_defaults_when_both_keys_are_garbage() -> None:
    assert resolve_document("42", "{oops") == LayoutConfigV2()


def test_resolve_ignores_a_non_dict_version_one_key() -> None:
    assert resolve_document("", "[1, 2]") == LayoutConfigV2()
