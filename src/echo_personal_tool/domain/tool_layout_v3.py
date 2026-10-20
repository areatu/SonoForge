"""Tool panel layout v3: model, migration from v1/v2, encoding (TP-0 PR-2).

Spec: ``docs/superpowers/specs/2026-10-15-tool-panel-2-spec-ru.md`` §8.2
(format) and §8.3 (migration).  The module is pure domain — no Qt, no
infrastructure — so the migration can be tested with property tests and reused
by the settings editor, the panel of TP-2 and the import/export of TP-5.

What the migration guarantees (spec §8.3):

1. A version-1/2 layout is read by the existing ``decode_tool_layout`` and
   handed over here as plain section dictionaries.
2. Every ``items[].id`` is a *legacy* id (``"<action>|<view>|<phase>|…"``);
   the alias map of the catalog turns it into a stable catalog id.
3. Unknown ids are not dropped: they are collected in ``unknown_items`` and
   exported back by :func:`export_v2_sections`.
4. User sections keep their title and their order (at most
   :data:`MAX_CUSTOM_SECTIONS` of them).
5. The result is the profile «Мой профиль (перенесён)» in the context
   «Общий»; the other contexts inherit it.
6. Version 3 is written to a **new** key (``tool_layout_v3_json``); the old
   ``tool_panel_layout_json`` is not touched, so an older build still reads
   its own settings after a rollback.
7. The migration is idempotent: migrating an already migrated layout returns
   the same document.

The panel itself keeps reading the version-2 layout until TP-2 — this PR has
no visible change.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from echo_personal_tool.domain.measurement_catalog import (
    CATALOG,
    LEGACY_ALIASES,
    SECTION_BY_LEGACY_KEY,
    SECTIONS,
    ToolSpec,
    tools_in_section,
)

#: Version of the document written to ``tool_layout_v3_json``.
LAYOUT_VERSION = 3

#: Id of the built-in profile every user profile is based on.
BUILTIN_PROFILE_ID = "builtin.adult_echo"

#: Id and name of the profile created by the migration of a custom layout.
MIGRATED_PROFILE_ID = "user-1"
MIGRATED_PROFILE_NAME = "Мой профиль (перенесён)"

#: Name of the context the migration fills («Общий»).
CONTEXT_COMMON = "common"

#: Upper bound of user sections; mirrors ``measures_menu.MAX_CUSTOM_SECTIONS``
#: (the test pins both numbers so they cannot drift apart).
MAX_CUSTOM_SECTIONS = 12

#: Prefix of the section keys of user sections in version 3 (``custom.1``).
CUSTOM_SECTION_PREFIX = "custom."

_EMPTY: Mapping[str, str] = MappingProxyType({})


# ── Records ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolItem:
    """One tool inside a section."""

    id: str
    visible: bool = True


@dataclass(frozen=True)
class Section:
    """One section of a context («Левый желудочек», «Мои инструменты» …)."""

    key: str
    title: str | None = None
    visible: bool = True
    items: tuple[ToolItem, ...] = ()


@dataclass(frozen=True)
class Context:
    """One context of a profile (2D, Doppler …).

    ``inherit`` marks a context that takes the sections of another context
    instead of defining its own (spec §8.2, context «doppler»).
    """

    name: str
    inherit: bool = True
    quick: tuple[str, ...] = ()
    favorites: tuple[str, ...] = ()
    sections: tuple[Section, ...] = ()


@dataclass(frozen=True)
class ToolProps:
    """User properties of a tool (shortcut, custom labels and visibility)."""

    key: str | None = None
    after: str | None = None
    label_ru: str | None = None
    label_en: str | None = None
    show_in: tuple[str, ...] = ()
    hint: str | None = None


@dataclass(frozen=True)
class Protocols:
    """Order of the protocol cards and the auto-advance switches."""

    order: tuple[str, ...] = ()
    auto_advance: Mapping[str, bool] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class Profile:
    """One profile: contexts, tool properties, radial menu and protocols."""

    id: str
    name: str
    base: str = BUILTIN_PROFILE_ID
    contexts: Mapping[str, Context] = field(default_factory=lambda: MappingProxyType({}))
    tool_props: Mapping[str, ToolProps] = field(default_factory=lambda: MappingProxyType({}))
    radial: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))
    protocols: Protocols = field(default_factory=Protocols)


@dataclass(frozen=True)
class Layout:
    """The whole version-3 document."""

    version: int = LAYOUT_VERSION
    active_profile: str = BUILTIN_PROFILE_ID
    profiles: tuple[Profile, ...] = ()
    unknown_items: tuple[str, ...] = ()

    def profile(self, profile_id: str | None = None) -> Profile | None:
        """The active profile (or the one with the given id)."""
        wanted = profile_id or self.active_profile
        for profile in self.profiles:
            if profile.id == wanted:
                return profile
        return None

    def context(self, context: str = CONTEXT_COMMON, profile_id: str | None = None) -> Context | None:
        """One context of a profile."""
        profile = self.profile(profile_id)
        if profile is None:
            return None
        return profile.contexts.get(context)


# ── Built-in layout ─────────────────────────────────────────────────


def _catalog_sections() -> tuple[Section, ...]:
    """Built-in sections in catalog order, every tool visible."""
    sections: list[Section] = []
    for section_id in SECTIONS:
        items = tuple(ToolItem(tool.id, True) for tool in tools_in_section(section_id))
        sections.append(Section(key=section_id, items=items))
    return tuple(sections)


def default_layout() -> Layout:
    """The built-in layout: one profile with the catalog sections."""
    profile = Profile(
        id=BUILTIN_PROFILE_ID,
        name="Взрослая эхо",
        contexts=MappingProxyType(
            {CONTEXT_COMMON: Context(CONTEXT_COMMON, inherit=False, sections=_catalog_sections())}
        ),
    )
    return Layout(active_profile=BUILTIN_PROFILE_ID, profiles=(profile,))


# ── Migration ───────────────────────────────────────────────────────


def _section_id_for_legacy_key(key: str) -> str | None:
    """Catalog section id of a version-2 built-in section key."""
    return SECTION_BY_LEGACY_KEY.get(key)


def _migrate_section_keys(sections: Sequence[Mapping[str, object]]) -> list[tuple[int, str, str | None]]:
    """Map version-2 section keys to version-3 keys.

    Built-in keys become their catalog id (``menu.lv_diastole_group`` →
    ``lv``); user sections become ``custom.1``, ``custom.2`` … in the order
    they appear.  Returns ``(index in *sections*, key, title)`` triples; the
    index keeps the source entries and the migrated keys aligned.
    """
    mapped: list[tuple[int, str, str | None]] = []
    custom_index = 0
    for index, entry in enumerate(sections):
        key = entry.get("key")
        if not isinstance(key, str) or not key:
            continue
        title = entry.get("title") if isinstance(entry.get("title"), str) else None
        section_id = _section_id_for_legacy_key(key)
        if section_id is not None:
            mapped.append((index, section_id, None))
            continue
        if not key.startswith("custom:"):
            continue  # unknown built-in key: the version-2 decoder drops it
        if custom_index >= MAX_CUSTOM_SECTIONS:
            continue  # §8.3.4: at most MAX_CUSTOM_SECTIONS user sections
        custom_index += 1
        mapped.append((index, f"{CUSTOM_SECTION_PREFIX}{custom_index}", title))
    return mapped


def _tool_visible(entry: Mapping[str, object]) -> bool:
    """Visibility of a version-2 item (``enabled`` is the stored flag)."""
    return bool(entry.get("enabled", True))


def migrate_sections(
    sections: Sequence[Mapping[str, object]],
    *,
    aliases: Mapping[str, str] | None = None,
) -> Layout:
    """Migrate a version-1/2 layout into a version-3 document (spec §8.3).

    ``sections`` is the output of ``measures_menu.decode_tool_layout``: a list
    of ``{"key", "title", "items": [{"id", "enabled"}]}`` dictionaries with
    *legacy* tool ids.  The result is complete: sections and tools that the
    stored layout does not mention are added in catalog order, exactly as the
    panel of today completes its own layout.
    """
    alias_map = LEGACY_ALIASES if aliases is None else aliases
    if not sections:
        return default_layout()

    mapped_keys = _migrate_section_keys(sections)
    by_section: dict[str, list[ToolItem]] = {key: [] for _index, key, _title in mapped_keys}
    titles: dict[str, str | None] = {key: title for _index, key, title in mapped_keys}
    placed: set[str] = set()
    unknown: list[str] = []

    for index, key, _title in mapped_keys:
        entry = sections[index]
        items = entry.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            tool_id = item.get("id")
            if not isinstance(tool_id, str) or not tool_id:
                continue
            catalog_id = alias_map.get(tool_id)
            if catalog_id is None:
                if tool_id not in unknown:
                    unknown.append(tool_id)
                continue
            if catalog_id in placed:  # a tool lives in exactly one section
                continue
            placed.add(catalog_id)
            by_section[key].append(ToolItem(catalog_id, _tool_visible(item)))

    # Sections and tools the stored layout does not mention are appended in
    # catalog order — the same completion the panel does today.
    for section_id in SECTIONS:
        if section_id not in by_section:
            by_section[section_id] = []
            titles[section_id] = None
    for section_id in SECTIONS:
        for tool in tools_in_section(section_id):
            if tool.id in placed:
                continue
            placed.add(tool.id)
            by_section[section_id].append(ToolItem(tool.id, True))

    ordered_keys = [key for _index, key, _title in mapped_keys]
    ordered_keys += [key for key in SECTIONS if key not in ordered_keys]
    v3_sections = tuple(
        Section(key=key, title=titles.get(key), visible=True, items=tuple(by_section[key])) for key in ordered_keys
    )
    context = Context(CONTEXT_COMMON, inherit=False, sections=v3_sections)
    profile = Profile(
        id=MIGRATED_PROFILE_ID,
        name=MIGRATED_PROFILE_NAME,
        base=BUILTIN_PROFILE_ID,
        contexts=MappingProxyType({CONTEXT_COMMON: context}),
    )
    return Layout(
        active_profile=MIGRATED_PROFILE_ID,
        profiles=(profile,),
        unknown_items=tuple(unknown),
    )


def migrate_to_v3(source: object) -> Layout:
    """Migrate any supported source into a version-3 layout (spec §8.3.7).

    ``source`` is either a :class:`Layout` (already version 3 — returned
    unchanged, which makes the migration idempotent) or the list of sections
    of a version-1/2 layout.
    """
    if isinstance(source, Layout):
        return source
    if isinstance(source, Sequence) and not isinstance(source, (str, bytes)):
        return migrate_sections([entry for entry in source if isinstance(entry, Mapping)])
    return default_layout()


# ── Encoding ────────────────────────────────────────────────────────


def _section_to_dict(section: Section) -> dict[str, object]:
    return {
        "key": section.key,
        "title": section.title,
        "visible": section.visible,
        "items": [{"id": item.id, "visible": item.visible} for item in section.items],
    }


def _context_to_dict(context: Context) -> dict[str, object]:
    return {
        "inherit": context.inherit,
        "quick": list(context.quick),
        "favorites": list(context.favorites),
        "sections": [_section_to_dict(section) for section in context.sections],
    }


def _tool_props_to_dict(props: ToolProps) -> dict[str, object]:
    """Serialize tool properties, omitting empty optional fields."""
    data: dict[str, object] = {"key": props.key, "after": props.after}
    if props.label_ru:
        data["label_ru"] = props.label_ru
    if props.label_en:
        data["label_en"] = props.label_en
    if props.show_in:
        data["show_in"] = list(props.show_in)
    if props.hint:
        data["hint"] = props.hint
    return data


def _profile_to_dict(profile: Profile) -> dict[str, object]:
    return {
        "id": profile.id,
        "name": profile.name,
        "base": profile.base,
        "contexts": {name: _context_to_dict(context) for name, context in profile.contexts.items()},
        "tool_props": {
            tool_id: _tool_props_to_dict(props) for tool_id, props in profile.tool_props.items()
        },
        "radial": {view: list(tools) for view, tools in profile.radial.items()},
        "protocols": {
            "order": list(profile.protocols.order),
            "auto_advance": dict(profile.protocols.auto_advance),
        },
    }


def layout_to_dict(layout: Layout) -> dict[str, object]:
    """The version-3 document as plain dictionaries."""
    return {
        "version": layout.version,
        "active_profile": layout.active_profile,
        "profiles": [_profile_to_dict(profile) for profile in layout.profiles],
        "unknown_items": list(layout.unknown_items),
    }


def encode_layout(layout: Layout) -> str:
    """Serialize a version-3 layout as JSON (the value of the new key)."""
    return json.dumps(layout_to_dict(layout), ensure_ascii=False, sort_keys=False)


def _decode_tool_item(raw: object) -> ToolItem | None:
    if not isinstance(raw, Mapping):
        return None
    tool_id = raw.get("id")
    if not isinstance(tool_id, str) or not tool_id:
        return None
    return ToolItem(tool_id, bool(raw.get("visible", True)))


def _decode_section(raw: object) -> Section | None:
    if not isinstance(raw, Mapping):
        return None
    key = raw.get("key")
    if not isinstance(key, str) or not key:
        return None
    title = raw.get("title") if isinstance(raw.get("title"), str) else None
    items_raw = raw.get("items")
    items: list[ToolItem] = []
    if isinstance(items_raw, list):
        for entry in items_raw:
            item = _decode_tool_item(entry)
            if item is not None:
                items.append(item)
    return Section(key=key, title=title, visible=bool(raw.get("visible", True)), items=tuple(items))


def _decode_context(name: str, raw: object) -> Context | None:
    if not isinstance(raw, Mapping):
        return None
    sections_raw = raw.get("sections")
    sections: list[Section] = []
    if isinstance(sections_raw, list):
        for entry in sections_raw:
            section = _decode_section(entry)
            if section is not None:
                sections.append(section)
    quick = raw.get("quick")
    favorites = raw.get("favorites")
    return Context(
        name=name,
        inherit=bool(raw.get("inherit", True)),
        quick=tuple(item for item in quick if isinstance(item, str)) if isinstance(quick, list) else (),
        favorites=tuple(item for item in favorites if isinstance(item, str)) if isinstance(favorites, list) else (),
        sections=tuple(sections),
    )


def _decode_profile(raw: object) -> Profile | None:
    if not isinstance(raw, Mapping):
        return None
    profile_id = raw.get("id")
    if not isinstance(profile_id, str) or not profile_id:
        return None
    name = raw.get("name") if isinstance(raw.get("name"), str) else profile_id
    base = raw.get("base") if isinstance(raw.get("base"), str) else BUILTIN_PROFILE_ID
    contexts_raw = raw.get("contexts")
    contexts: dict[str, Context] = {}
    if isinstance(contexts_raw, Mapping):
        for context_name, context_raw in contexts_raw.items():
            context = _decode_context(str(context_name), context_raw)
            if context is not None:
                contexts[str(context_name)] = context
    props_raw = raw.get("tool_props")
    props: dict[str, ToolProps] = {}
    if isinstance(props_raw, Mapping):
        for tool_id, value in props_raw.items():
            if isinstance(value, Mapping):
                key = value.get("key") if isinstance(value.get("key"), str) else None
                after = value.get("after") if isinstance(value.get("after"), str) else None
                label_ru = value.get("label_ru") if isinstance(value.get("label_ru"), str) else None
                label_en = value.get("label_en") if isinstance(value.get("label_en"), str) else None
                show_in_raw = value.get("show_in")
                show_in = (
                    tuple(item for item in show_in_raw if isinstance(item, str))
                    if isinstance(show_in_raw, list)
                    else ()
                )
                hint = value.get("hint") if isinstance(value.get("hint"), str) else None
                props[str(tool_id)] = ToolProps(
                    key=key,
                    after=after,
                    label_ru=label_ru,
                    label_en=label_en,
                    show_in=show_in,
                    hint=hint,
                )
    radial_raw = raw.get("radial")
    radial: dict[str, tuple[str, ...]] = {}
    if isinstance(radial_raw, Mapping):
        for view, tools in radial_raw.items():
            if isinstance(tools, list):
                radial[str(view)] = tuple(item for item in tools if isinstance(item, str))
    protocols_raw = raw.get("protocols")
    order: tuple[str, ...] = ()
    auto_advance: dict[str, bool] = {}
    if isinstance(protocols_raw, Mapping):
        raw_order = protocols_raw.get("order")
        if isinstance(raw_order, list):
            order = tuple(item for item in raw_order if isinstance(item, str))
        raw_auto = protocols_raw.get("auto_advance")
        if isinstance(raw_auto, Mapping):
            auto_advance = {str(key): bool(value) for key, value in raw_auto.items()}
    return Profile(
        id=profile_id,
        name=name,
        base=base,
        contexts=MappingProxyType(contexts),
        tool_props=MappingProxyType(props),
        radial=MappingProxyType(radial),
        protocols=Protocols(order=order, auto_advance=MappingProxyType(auto_advance)),
    )


def decode_layout(raw: object) -> Layout | None:
    """Parse a stored version-3 document; ``None`` when it is unusable.

    Malformed input never raises: a broken document is treated as absent, so
    the panel falls back to the built-in layout.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, Mapping):
        return None
    if data.get("version") != LAYOUT_VERSION:
        return None
    profiles_raw = data.get("profiles")
    profiles: list[Profile] = []
    if isinstance(profiles_raw, list):
        for entry in profiles_raw:
            profile = _decode_profile(entry)
            if profile is not None:
                profiles.append(profile)
    if not profiles:
        return None
    active = data.get("active_profile")
    active_profile = active if isinstance(active, str) and active else profiles[0].id
    unknown_raw = data.get("unknown_items")
    unknown = tuple(item for item in unknown_raw if isinstance(item, str)) if isinstance(unknown_raw, list) else ()
    return Layout(
        version=LAYOUT_VERSION,
        active_profile=active_profile,
        profiles=tuple(profiles),
        unknown_items=unknown,
    )


# ── Helpers ─────────────────────────────────────────────────────────


def visible_tool_ids(layout: Layout, context: str = CONTEXT_COMMON) -> tuple[str, ...]:
    """Ids of the visible tools of a context, in display order."""
    section = layout.context(context)
    if section is None:
        return ()
    return tuple(item.id for block in section.sections for item in block.items if item.visible)


def all_tool_ids(layout: Layout, context: str = CONTEXT_COMMON) -> tuple[str, ...]:
    """Ids of all tools of a context, visible or not, in display order."""
    section = layout.context(context)
    if section is None:
        return ()
    return tuple(item.id for block in section.sections for item in block.items)


def _legacy_key_for_section(section_id: str) -> str | None:
    """Version-2 key of a built-in section (``lv`` → ``menu.lv_diastole_group``)."""
    for candidate in SECTIONS.values():
        if candidate.id == section_id:
            return candidate.legacy_key
    return None


def _legacy_id_for_tool(tool_id: str) -> str | None:
    """Version-2 ``tool_id`` of a catalog tool."""
    tool: ToolSpec | None = CATALOG.get(tool_id)
    if tool is None:
        return None
    return tool.legacy_id


def export_v2_sections(layout: Layout, context: str = CONTEXT_COMMON) -> list[dict[str, object]]:
    """Export a version-3 layout back to the version-2 section format.

    Known tools are exported with their legacy ids and their visibility; the
    unknown ids of the layout are *not* part of the version-2 format and stay
    in :attr:`Layout.unknown_items` (spec §8.3.3).
    """
    section = layout.context(context)
    if section is None:
        return []
    exported: list[dict[str, object]] = []
    for block in section.sections:
        legacy_key = _legacy_key_for_section(block.key)
        if legacy_key is None:
            if not block.key.startswith(CUSTOM_SECTION_PREFIX):
                continue
            legacy_key = "custom:" + block.key[len(CUSTOM_SECTION_PREFIX) :]
        items: list[dict[str, object]] = []
        for item in block.items:
            legacy_id = _legacy_id_for_tool(item.id)
            if legacy_id is None:
                continue
            items.append({"id": legacy_id, "enabled": item.visible})
        exported.append({"key": legacy_key, "title": block.title, "items": items})
    return exported


def with_active_profile(layout: Layout, profile_id: str) -> Layout:
    """A copy of the layout with another active profile."""
    if layout.profile(profile_id) is None:
        raise KeyError(profile_id)
    return replace(layout, active_profile=profile_id)


def iter_catalog_tools() -> Iterable[ToolSpec]:
    """Every tool of the catalog (helper for the settings editor of TP-5)."""
    return tuple(CATALOG.values())
