"""Settings 2.0 domain (TP-5 PR-1): profiles, contexts, keys, import/export."""

from __future__ import annotations

import json

import pytest

from echo_personal_tool.domain import tool_settings as s
from echo_personal_tool.domain.tool_layout_v3 import (
    BUILTIN_PROFILE_ID,
    CONTEXT_COMMON,
    Layout,
    decode_layout,
    default_layout,
    encode_layout,
)
from echo_personal_tool.domain.tool_panel_view import panel_view


def _profile(layout: Layout, profile_id: str | None = None):
    profile = layout.profile(profile_id)
    assert profile is not None
    return profile


# ── Profiles ────────────────────────────────────────────────────────


def test_builtin_profile_is_read_only() -> None:
    layout = default_layout()
    with pytest.raises(ValueError):
        s.rename_profile(layout, "Новое имя", profile_id=BUILTIN_PROFILE_ID)
    with pytest.raises(ValueError):
        s.reset_profile(layout, profile_id=BUILTIN_PROFILE_ID)


def test_duplicate_profile_becomes_active_and_editable() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7", name="Моя эхо")
    assert layout.active_profile == "user-7"
    assert [profile.id for profile in layout.profiles] == [BUILTIN_PROFILE_ID, "user-7"]
    duplicated = _profile(layout, "user-7")
    assert duplicated.name == "Моя эхо"
    assert duplicated.base == BUILTIN_PROFILE_ID
    assert duplicated.contexts.keys() == _profile(layout).contexts.keys()

    renamed = s.rename_profile(layout, "Рабочая", profile_id="user-7")
    assert _profile(renamed, "user-7").name == "Рабочая"
    assert _profile(renamed, BUILTIN_PROFILE_ID).name == _profile(default_layout(), BUILTIN_PROFILE_ID).name


def test_reset_profile_returns_the_builtin_contexts_and_clears_overrides() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7", name="Моя эхо")
    layout = s.set_tool_key(layout, "tool.caliper", "V", profile_id="user-7")
    layout = s.set_context_quick(layout, CONTEXT_COMMON, ("tool.caliper",), profile_id="user-7")
    reset = s.reset_profile(layout, profile_id="user-7")
    profile = _profile(reset, "user-7")
    assert profile.name == "Моя эхо"
    assert profile.tool_props == {}
    builtin = _profile(reset, BUILTIN_PROFILE_ID)
    assert profile.contexts == builtin.contexts
    assert s.export_layout(reset) != s.export_layout(layout)


def test_unknown_profile_is_explicit() -> None:
    with pytest.raises(KeyError):
        s.use_profile(default_layout(), "missing")


# ── Contexts ────────────────────────────────────────────────────────


def test_context_inherits_common_until_it_is_changed() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7")
    view = panel_view(layout, "2d")
    assert not view.quick == ()  # defaults still render
    assert "2d" not in _profile(layout).contexts

    layout = s.set_context_quick(layout, "2d", ("tool.caliper", "tool.area"), profile_id="user-7")
    context = _profile(layout).contexts["2d"]
    assert context.inherit is False
    assert context.quick == ("tool.caliper", "tool.area")
    assert context.sections == _profile(layout).contexts[CONTEXT_COMMON].sections
    assert _profile(layout).contexts[CONTEXT_COMMON].quick == ()


def test_context_limits_are_enforced() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7")
    with pytest.raises(ValueError):
        s.set_context_quick(layout, "2d", [f"tool.{index}" for index in range(5)], profile_id="user-7")
    with pytest.raises(ValueError):
        s.set_context_favorites(layout, "2d", [f"tool.{index}" for index in range(10)], profile_id="user-7")
    with pytest.raises(ValueError):
        s.set_radial(layout, "2d", [f"tool.{index}" for index in range(9)], profile_id="user-7")


def test_unknown_context_is_rejected() -> None:
    with pytest.raises(ValueError):
        s.update_context(default_layout(), "vessel")


def test_hiding_a_tool_materializes_an_inherited_context_only() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7")
    common_before = _profile(layout).contexts[CONTEXT_COMMON]
    layout = s.set_tool_visible(layout, "2d", "lv.linear_ed", False, profile_id="user-7")
    profile = _profile(layout)
    assert profile.contexts["2d"].inherit is False
    assert profile.contexts[CONTEXT_COMMON] == common_before
    ids = {item.id: item.visible for block in profile.contexts["2d"].sections for item in block.items}
    assert ids["lv.linear_ed"] is False


def test_custom_section_add_rename_delete_returns_tools() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7")
    layout, key = s.add_custom_section(layout, CONTEXT_COMMON, "Мои", profile_id="user-7")
    assert key.startswith("custom.")
    layout = s.move_tool(layout, CONTEXT_COMMON, "tool.caliper", key, profile_id="user-7")
    section = next(block for block in layout.context(CONTEXT_COMMON).sections if block.key == key)
    assert [item.id for item in section.items] == ["tool.caliper"]

    layout = s.rename_section(layout, CONTEXT_COMMON, key, "Мои инструменты", profile_id="user-7")
    section = next(block for block in layout.context(CONTEXT_COMMON).sections if block.key == key)
    assert section.title == "Мои инструменты"

    layout = s.delete_section(layout, CONTEXT_COMMON, key, profile_id="user-7")
    assert all(block.key != key for block in layout.context(CONTEXT_COMMON).sections)
    placed = [item.id for block in layout.context(CONTEXT_COMMON).sections for item in block.items]
    assert "tool.caliper" in placed


def test_builtin_sections_cannot_be_renamed_or_deleted() -> None:
    with pytest.raises(ValueError):
        s.rename_section(default_layout(), CONTEXT_COMMON, "general", "X")
    with pytest.raises(ValueError):
        s.delete_section(default_layout(), CONTEXT_COMMON, "general")


def test_sections_can_be_reordered() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7")
    before = [block.key for block in layout.context(CONTEXT_COMMON).sections]
    layout = s.move_section(layout, CONTEXT_COMMON, before[1], -1, profile_id="user-7")
    after = [block.key for block in layout.context(CONTEXT_COMMON).sections]
    assert after[:2] == [before[1], before[0]]


# ── Shortcut conflicts ──────────────────────────────────────────────


def test_key_conflict_with_application_shortcut_requires_force() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7")
    external = (s.KeyBinding("caliper", "Калипер", "L"),)
    with pytest.raises(s.KeyConflictError) as error:
        s.set_tool_key(layout, "lv.linear_ed", "L", external=external, profile_id="user-7")
    assert error.value.conflict.owner == "caliper"
    assert error.value.conflict.source == "shortcut"
    assert s.tool_props(layout, "lv.linear_ed", "user-7").key is None

    forced = s.set_tool_key(layout, "lv.linear_ed", "L", force=True, external=external, profile_id="user-7")
    assert s.tool_props(forced, "lv.linear_ed", "user-7").key == "L"


def test_key_conflict_with_another_tool_is_cleared_by_assign() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7")
    layout = s.set_tool_key(layout, "lv.linear_ed", "V", profile_id="user-7")
    with pytest.raises(s.KeyConflictError):
        s.set_tool_key(layout, "lv.lvesd", "V", profile_id="user-7")
    layout = s.set_tool_key(layout, "lv.lvesd", "V", force=True, profile_id="user-7")
    assert s.tool_props(layout, "lv.lvesd", "user-7").key == "V"
    assert s.tool_props(layout, "lv.linear_ed", "user-7").key is None
    assert s.find_key_conflict(layout, "lv.lvesd", "V", profile_id="user-7") is None


def test_key_normalization_matches_aliases_and_modifier_order() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7")
    layout = s.set_tool_key(layout, "lv.linear_ed", "Shift+Ctrl+V", profile_id="user-7")
    assert s.find_key_conflict(layout, "lv.lvesd", "Ctrl+Shift+V", profile_id="user-7") is not None
    assert s.normalize_key("Return") == s.normalize_key("Enter")


def test_clearing_a_key_releases_it() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7")
    layout = s.set_tool_key(layout, "lv.linear_ed", "V", profile_id="user-7")
    layout = s.set_tool_key(layout, "lv.linear_ed", None, profile_id="user-7")
    assert s.tool_props(layout, "lv.linear_ed", "user-7").key is None
    assert s.find_key_conflict(layout, "lv.lvesd", "V", profile_id="user-7") is None


# ── Tool properties ─────────────────────────────────────────────────


def test_labels_show_in_and_hint_survive_the_round_trip() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7")
    layout = s.set_tool_labels(layout, "lv.linear_ed", label_ru="КДР", label_en="LVEDD", profile_id="user-7")
    layout = s.set_tool_show_in(layout, "lv.linear_ed", ("panel", "quick"), profile_id="user-7")
    layout = s.set_tool_hint(layout, "lv.linear_ed", "Конец диастолы", profile_id="user-7")
    layout = s.set_tool_after(layout, "lv.linear_ed", s.AFTER_STAY, profile_id="user-7")

    decoded = decode_layout(encode_layout(layout))
    assert decoded is not None
    props = s.tool_props(decoded, "lv.linear_ed", "user-7")
    assert props.label_ru == "КДР"
    assert props.label_en == "LVEDD"
    assert props.show_in == ("panel", "quick")
    assert props.hint == "Конец диастолы"
    assert props.after == s.AFTER_STAY

    data = json.loads(encode_layout(layout))
    raw = data["profiles"][1]["tool_props"]["lv.linear_ed"]
    assert raw["label_ru"] == "КДР"


def test_invalid_after_value_is_rejected() -> None:
    with pytest.raises(ValueError):
        s.set_tool_after(default_layout(), "lv.linear_ed", "later")


# ── Import / export ─────────────────────────────────────────────────


def test_import_round_trips_a_complete_document() -> None:
    layout = s.duplicate_profile(default_layout(), new_id="user-7", name="Моя эхо")
    layout = s.set_tool_key(layout, "mv.vti", "V", profile_id="user-7")
    layout = s.set_context_quick(layout, "doppler", ("mv.e", "mv.vti"), profile_id="user-7")
    layout = s.set_radial(layout, "2d", ("tool.caliper", "tool.area"), profile_id="user-7")
    restored = s.import_layout(s.export_layout(layout))
    assert restored == layout


@pytest.mark.parametrize(
    ("document", "reason"),
    [
        ("", "empty"),
        ("not json", "json"),
        ("[]", "not_object"),
        ('{"version": 2, "profiles": []}', "version"),
        ('{"version": 3, "profiles": []}', "profiles"),
        (
            '{"version": 3, "active_profile": "a", "profiles": [{"id": "a", "name": "A"}, {"id": "a", "name": "B"}]}',
            "duplicate_profile",
        ),
        (
            '{"version": 3, "active_profile": "a", "profiles": [{"id": "a", "name": "A", "contexts": {"vessel": {}}}]}',
            "context",
        ),
        (
            '{"version": 3, "active_profile": "b", "profiles": [{"id": "a", "name": "A"}]}',
            "active_profile",
        ),
    ],
)
def test_invalid_import_is_explicit_and_keeps_the_current_layout(document: str, reason: str) -> None:
    current = s.duplicate_profile(default_layout(), new_id="user-7")
    before = s.export_layout(current)
    with pytest.raises(s.LayoutImportError) as error:
        s.import_layout(document)
    assert error.value.reason == reason
    assert s.export_layout(current) == before


def test_import_rejects_a_too_long_quick_row() -> None:
    document = json.dumps(
        {
            "version": 3,
            "active_profile": "a",
            "profiles": [
                {
                    "id": "a",
                    "name": "A",
                    "contexts": {"common": {"quick": ["a", "b", "c", "d", "e"]}},
                }
            ],
        }
    )
    with pytest.raises(s.LayoutImportError) as error:
        s.import_layout(document)
    assert error.value.reason == "quick"


# ── Undo / redo ─────────────────────────────────────────────────────


def test_undo_stack_walks_states_and_drops_redo_on_a_new_edit() -> None:
    first = default_layout()
    second = s.duplicate_profile(first, new_id="user-7")
    third = s.set_tool_key(second, "tool.caliper", "V", profile_id="user-7")
    stack = s.UndoStack(first)
    assert stack.push(first) is False
    assert stack.push(second) is True
    assert stack.push(third) is True
    assert stack.can_undo is True
    assert stack.undo() == second
    assert stack.undo() == first
    assert stack.undo() is None
    assert stack.redo() == second
    stack.push(first)
    assert stack.can_redo is False
