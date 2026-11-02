"""Tool panel layout v3 and the migration of the version-1/2 layout.

TP-0 PR-2 (spec ``2026-10-15-tool-panel-2-spec-ru.md`` §8.2–8.3, A-11):

* the migrated layout shows the same tools in the same order as the panel of
  today (checked against the panel's own rendering path);
* user sections keep their title and their order;
* unknown ids are not dropped;
* the migration is idempotent and the version-2 document is never rewritten.
"""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from echo_personal_tool.domain import tool_layout_v3 as v3
from echo_personal_tool.domain.measurement_catalog import LEGACY_ALIASES
from echo_personal_tool.domain.tool_layout_v3 import (
    BUILTIN_PROFILE_ID,
    CONTEXT_COMMON,
    LAYOUT_VERSION,
    MIGRATED_PROFILE_ID,
    MIGRATED_PROFILE_NAME,
    Layout,
    all_tool_ids,
    decode_layout,
    default_layout,
    encode_layout,
    export_v2_sections,
    migrate_sections,
    migrate_to_v3,
    visible_tool_ids,
)

_MENU_KEYS = (
    "menu.general",
    "menu.lv_diastole_group",
    "menu.lv_auto",
    "menu.aorta",
    "menu.la_group",
    "menu.ra_group",
    "menu.rv_group",
    "menu.diastolic_group",
    "menu.mv_group",
    "menu.tv_group",
    "menu.strain_group",
    "menu.vessels_group",
    "menu.mmode_group",
)

_LEGACY_IDS = tuple(LEGACY_ALIASES)
_GHOST_IDS = ("ghost|A4C|ED||||", "custom:unknown-tool")


# ── Helpers ─────────────────────────────────────────────────────────


def _section_signature(layout: Layout) -> tuple[tuple[object, ...], ...]:
    """Sections of the «Общий» context as comparable tuples."""
    context = layout.context(CONTEXT_COMMON)
    assert context is not None
    return tuple(
        (
            section.key,
            section.title,
            section.visible,
            tuple((item.id, item.visible) for item in section.items),
        )
        for section in context.sections
    )


def _panel_visible_ids(layout: list[dict[str, object]]) -> list[str]:
    """The tools the panel of today would show, in order (legacy ids)."""
    from echo_personal_tool.presentation.measures_menu import _MENU, apply_tool_layout

    return [button.tool_id for _key, buttons in apply_tool_layout(_MENU, layout) for button in buttons]


def _v2_section(key: str, items: list[tuple[str, bool]], title: str | None = None) -> dict[str, object]:
    entry: dict[str, object] = {
        "key": key,
        "title": title,
        "items": [{"id": tool_id, "enabled": enabled} for tool_id, enabled in items],
    }
    return entry


# ── Structure ───────────────────────────────────────────────────────


def test_migrated_profile_and_context() -> None:
    layout = migrate_sections([_v2_section("menu.general", [("caliper|A4C|ED||||", True)])])
    profile = layout.profile()
    assert profile is not None
    assert profile.id == MIGRATED_PROFILE_ID
    assert profile.name == MIGRATED_PROFILE_NAME
    assert profile.base == BUILTIN_PROFILE_ID
    assert layout.active_profile == MIGRATED_PROFILE_ID
    context = layout.context(CONTEXT_COMMON)
    assert context is not None
    assert context.name == CONTEXT_COMMON
    assert context.inherit is False  # the other contexts inherit this one


def test_builtin_section_keys_become_catalog_ids() -> None:
    layout = migrate_sections(
        [
            _v2_section("menu.lv_diastole_group", [("lv2d_all_diastole|A4C|ED||||", True)]),
            _v2_section("menu.mv_group", [("None|A4C|ED||||MV Vmax", True)]),
        ]
    )
    keys = [section.key for section in layout.context(CONTEXT_COMMON).sections]
    assert keys[:2] == ["lv", "mv_av"]
    assert "general" in keys  # sections the layout does not mention are appended


def test_tool_ids_become_catalog_ids() -> None:
    layout = migrate_sections([_v2_section("menu.general", [("caliper|A4C|ED||||", True)])])
    ids = all_tool_ids(layout)
    assert ids[0] == "tool.caliper"


def test_hidden_tools_stay_listed_but_invisible() -> None:
    layout = migrate_sections([_v2_section("menu.general", [("caliper|A4C|ED||||", False)])])
    context = layout.context(CONTEXT_COMMON)
    general = next(section for section in context.sections if section.key == "general")
    item = next(item for item in general.items if item.id == "tool.caliper")
    assert item.visible is False
    assert "tool.caliper" not in visible_tool_ids(layout)


def test_user_sections_keep_title_and_order() -> None:
    layout = migrate_sections(
        [
            _v2_section("custom:ab12cd34", [("caliper|A4C|ED||||", True)], title="Мои"),
            _v2_section("menu.general", [("spline_area|A4C|ED||||", True)]),
        ]
    )
    sections = layout.context(CONTEXT_COMMON).sections
    assert sections[0].key == "custom.1"
    assert sections[0].title == "Мои"
    assert [section.key for section in sections[1:3]] == ["general", "lv"]


def test_user_section_limit_matches_the_settings_dialog() -> None:
    from echo_personal_tool.presentation import measures_menu

    assert v3.MAX_CUSTOM_SECTIONS == measures_menu.MAX_CUSTOM_SECTIONS


def test_too_many_user_sections_are_dropped() -> None:
    sections = [
        _v2_section(f"custom:{index:04x}", [], title=f"Секция {index}") for index in range(v3.MAX_CUSTOM_SECTIONS + 3)
    ]
    layout = migrate_sections(sections)
    custom = [section for section in layout.context(CONTEXT_COMMON).sections if section.key.startswith("custom.")]
    assert len(custom) == v3.MAX_CUSTOM_SECTIONS


def test_unknown_ids_are_kept_in_unknown_items() -> None:
    layout = migrate_sections(
        [
            _v2_section("menu.general", [("caliper|A4C|ED||||", True), ("ghost|A4C|ED||||", True)]),
            _v2_section("custom:1", [("custom:unknown-tool", False)], title="Мои"),
        ]
    )
    assert layout.unknown_items == ("ghost|A4C|ED||||", "custom:unknown-tool")
    ids = all_tool_ids(layout)
    assert "ghost|A4C|ED||||" not in ids
    assert "custom:unknown-tool" not in ids


def test_duplicate_tool_lands_in_one_section() -> None:
    layout = migrate_sections(
        [
            _v2_section("menu.general", [("caliper|A4C|ED||||", True)]),
            _v2_section("menu.lv_diastole_group", [("caliper|A4C|ED||||", True)]),
        ]
    )
    assert all_tool_ids(layout).count("tool.caliper") == 1


def test_empty_layout_gives_the_built_in_layout() -> None:
    layout = migrate_sections([])
    assert layout.active_profile == BUILTIN_PROFILE_ID
    assert layout.unknown_items == ()
    assert len(visible_tool_ids(layout)) == len(_LEGACY_IDS)


def test_migration_completes_missing_sections_and_tools() -> None:
    layout = migrate_sections([_v2_section("menu.general", [("caliper|A4C|ED||||", True)])])
    assert set(all_tool_ids(layout)) == set(LEGACY_ALIASES.values())


# ── Property tests (A-11) ───────────────────────────────────────────


@st.composite
def _v2_layouts(draw) -> list[dict[str, object]]:
    """Random version-2 layouts: sections, tools, visibility and ghost ids."""
    builtin = draw(
        st.lists(
            st.sampled_from(_MENU_KEYS),
            min_size=0,
            max_size=4,
            unique=True,
        )
    )
    custom = draw(st.integers(min_value=0, max_value=3))
    sections: list[dict[str, object]] = []
    for key in builtin:
        ids = draw(st.lists(st.sampled_from(_LEGACY_IDS), min_size=0, max_size=6, unique=True))
        items = [{"id": tool_id, "enabled": draw(st.booleans())} for tool_id in ids]
        if draw(st.booleans()):
            items.append({"id": draw(st.sampled_from(_GHOST_IDS)), "enabled": draw(st.booleans())})
        sections.append({"key": key, "title": None, "items": items})
    for index in range(custom):
        ids = draw(st.lists(st.sampled_from(_LEGACY_IDS), min_size=0, max_size=4, unique=True))
        items = [{"id": tool_id, "enabled": draw(st.booleans())} for tool_id in ids]
        sections.append({"key": f"custom:{index:04x}", "title": f"Секция {index}", "items": items})
    return sections


@settings(max_examples=60, deadline=None)
@given(layout=_v2_layouts())
def test_visible_tools_and_order_survive_the_migration(layout: list[dict[str, object]]) -> None:
    """The migrated layout shows exactly what the panel of today shows."""
    migrated = migrate_sections(layout)
    expected = [LEGACY_ALIASES[legacy] for legacy in _panel_visible_ids(layout)]
    assert list(visible_tool_ids(migrated)) == expected


@settings(max_examples=60, deadline=None)
@given(layout=_v2_layouts())
def test_migration_is_idempotent(layout: list[dict[str, object]]) -> None:
    once = migrate_sections(layout)
    assert migrate_to_v3(once) == once
    assert migrate_to_v3(migrate_to_v3(once)) == once


@settings(max_examples=60, deadline=None)
@given(layout=_v2_layouts())
def test_round_trip_through_version_two_keeps_the_tools(layout: list[dict[str, object]]) -> None:
    once = migrate_sections(layout)
    again = migrate_sections(export_v2_sections(once))
    assert _section_signature(again) == _section_signature(once)
    assert visible_tool_ids(again) == visible_tool_ids(once)


@settings(max_examples=60, deadline=None)
@given(layout=_v2_layouts())
def test_unknown_ids_survive_the_migration(layout: list[dict[str, object]]) -> None:
    expected: list[str] = []
    for section in layout:
        for item in section["items"]:  # type: ignore[union-attr]
            tool_id = item["id"]
            if tool_id not in LEGACY_ALIASES and tool_id not in expected:
                expected.append(tool_id)
    assert list(migrate_sections(layout).unknown_items) == expected


@settings(max_examples=60, deadline=None)
@given(layout=_v2_layouts())
def test_encode_decode_round_trip(layout: list[dict[str, object]]) -> None:
    migrated = migrate_sections(layout)
    decoded = decode_layout(encode_layout(migrated))
    assert decoded == migrated


# ── Encoding ────────────────────────────────────────────────────────


def test_encoded_document_matches_the_spec_shape() -> None:
    data = json.loads(encode_layout(migrate_sections([_v2_section("menu.general", [])])))
    assert data["version"] == LAYOUT_VERSION
    assert data["active_profile"] == MIGRATED_PROFILE_ID
    assert data["unknown_items"] == []
    profile = data["profiles"][0]
    assert profile["id"] == MIGRATED_PROFILE_ID
    assert profile["base"] == BUILTIN_PROFILE_ID
    context = profile["contexts"][CONTEXT_COMMON]
    assert context["inherit"] is False
    assert context["sections"][0]["key"] == "general"
    assert context["sections"][0]["items"][0] == {"id": "tool.caliper", "visible": True}


def test_decode_rejects_broken_documents() -> None:
    assert decode_layout("") is None
    assert decode_layout("not json") is None
    assert decode_layout('{"version": 2, "profiles": []}') is None
    assert decode_layout('{"version": 3, "profiles": []}') is None
    assert decode_layout('{"version": 3, "profiles": [{"id": "p"}]}') is not None


def test_default_layout_lists_every_tool() -> None:
    layout = default_layout()
    assert set(all_tool_ids(layout)) == set(LEGACY_ALIASES.values())


# ── Adapter: the version-2 key is read, never rewritten ─────────────


def test_adapter_migrates_without_touching_the_version_two_document() -> None:
    from echo_personal_tool.presentation.measures_menu import encode_tool_layout, tool_layout_v3_from_v2

    v2 = encode_tool_layout(
        [
            {
                "key": "menu.general",
                "title": None,
                "items": [{"id": "caliper|A4C|ED||||", "enabled": True}],
            }
        ]
    )
    migrated = tool_layout_v3_from_v2(v2)
    assert json.loads(v2)["version"] == 2
    assert json.loads(migrated)["version"] == 3
    assert "tool.caliper" in visible_tool_ids(decode_layout(migrated))


def test_adapter_of_an_empty_layout_gives_the_default_document() -> None:
    from echo_personal_tool.presentation.measures_menu import tool_layout_v3_from_v2

    data = json.loads(tool_layout_v3_from_v2(""))
    assert data["version"] == 3
    assert data["active_profile"] == BUILTIN_PROFILE_ID
