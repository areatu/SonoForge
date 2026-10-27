"""Settings 2.0 domain layer (TP-5 PR-1, spec 2026-10-15 §7-§8).

The module owns everything the Tools settings editor changes: profiles and
their contexts, per-tool properties, shortcut conflicts, import/export and the
undo history.  It is pure domain: no Qt import, no persistence.  The editor
(TP-5 PR-2) renders this model and writes the returned :class:`Layout` back to
``UserPreferences.tool_layout_v3_json``.

Shortcut conflicts are checked against two sources:

* other tool bindings of the same profile (the editor can reassign those);
* the registered application shortcuts, passed in as :class:`KeyBinding`
  values so the domain stays independent of the presentation registry.

A conflicting assignment is never stored silently: :func:`set_tool_key`
raises :class:`KeyConflictError` unless the caller explicitly passes
``force=True`` (the «Назначить» choice of the conflict dialog).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from echo_personal_tool.domain.measurement_catalog import (
    SECTIONS,
    tools_in_section,
)
from echo_personal_tool.domain.tool_layout_v3 import (
    BUILTIN_PROFILE_ID,
    CONTEXT_COMMON,
    CUSTOM_SECTION_PREFIX,
    LAYOUT_VERSION,
    MAX_CUSTOM_SECTIONS,
    Context,
    Layout,
    Profile,
    Protocols,
    Section,
    ToolItem,
    ToolProps,
    decode_layout,
    default_layout,
    encode_layout,
)

#: Contexts the Tools editor exposes, including the explicit spatial vessel override.
SETTINGS_CONTEXTS: tuple[str, ...] = (CONTEXT_COMMON, "2d", "m", "doppler", "vessels")

#: Quick tiles (spec §7: up to four) and favourites (up to nine).
MAX_QUICK = 4
MAX_FAVORITES = 9

#: Sectors of the radial menu (spec §7: eight per context).
RADIAL_SECTORS = 8

#: Values of the «поведение после измерения» switch.
AFTER_RETURN = "return"
AFTER_STAY = "stay"
AFTER_OPTIONS: tuple[str, ...] = (AFTER_RETURN, AFTER_STAY)

#: Where a tool is shown (spec §7: panel, quick tiles, radial menu, palette).
SHOW_IN_OPTIONS: tuple[str, ...] = ("panel", "quick", "radial", "palette")

_UNSET = object()

#: Label of an external binding in the conflict dialog.
_SHORTCUT_SOURCE = "shortcut"
_TOOL_SOURCE = "tool"


# ── Key bindings and conflicts ──────────────────────────────────────


@dataclass(frozen=True)
class KeyBinding:
    """A key already claimed outside the layout (an application shortcut)."""

    owner: str
    label: str
    sequence: str
    scope: str = "main-window"


@dataclass(frozen=True)
class KeyConflict:
    """The binding that blocks a requested key."""

    sequence: str
    owner: str
    owner_label: str
    candidate_tool_id: str
    source: str


class KeyConflictError(ValueError):
    """Raised when a key is already taken and ``force`` was not requested."""

    def __init__(self, conflict: KeyConflict) -> None:
        self.conflict = conflict
        super().__init__(f"{conflict.sequence} is already bound to {conflict.owner_label} ({conflict.owner})")


def normalize_key(sequence: str | None) -> str:
    """Normalize modifiers/key aliases before comparing two bindings."""
    if not sequence or not sequence.strip():
        return ""
    value = sequence.strip()
    if value in {"+", "=", "-", "[", "]", "`", "/"}:
        return value.casefold()
    pieces = value.split("+")
    if not pieces or any(not piece for piece in pieces):
        return value.casefold()
    aliases = {"escape": "esc", "return": "enter", "control": "ctrl", "del": "delete"}
    modifiers = {aliases.get(piece.casefold(), piece.casefold()) for piece in pieces[:-1]}
    order = ("ctrl", "shift", "alt", "meta")
    ordered = [modifier for modifier in order if modifier in modifiers]
    ordered.extend(sorted(modifiers - set(ordered)))
    key = aliases.get(pieces[-1].casefold(), pieces[-1].casefold())
    return "+".join((*ordered, key))


def _clean_key(sequence: str | None) -> str | None:
    value = (sequence or "").strip()
    return value or None


def tool_key_bindings(layout: Layout, profile_id: str | None = None) -> tuple[KeyBinding, ...]:
    """Every assigned tool key of one profile."""
    profile = layout.profile(profile_id)
    if profile is None:
        return ()
    return tuple(
        KeyBinding(owner=tool_id, label=tool_id, sequence=props.key or "", scope="main-window")
        for tool_id, props in profile.tool_props.items()
        if props.key
    )


def find_key_conflict(
    layout: Layout,
    tool_id: str,
    sequence: str | None,
    *,
    external: Iterable[KeyBinding] = (),
    profile_id: str | None = None,
    scope: str = "main-window",
) -> KeyConflict | None:
    """The binding that already uses *sequence*, or ``None``.

    The current binding of *tool_id* is not a conflict with itself.  Tool
    bindings are global to the profile, so the same key cannot be assigned to
    two tools even when they live in different contexts.
    """
    wanted = normalize_key(sequence)
    if not wanted:
        return None
    for binding in external:
        if binding.scope != scope or binding.owner == tool_id:
            continue
        if normalize_key(binding.sequence) == wanted:
            return KeyConflict(
                sequence=wanted,
                owner=binding.owner,
                owner_label=binding.label or binding.owner,
                candidate_tool_id=tool_id,
                source=_SHORTCUT_SOURCE,
            )
    profile = layout.profile(profile_id)
    if profile is not None:
        for owner, props in profile.tool_props.items():
            if owner == tool_id or not props.key:
                continue
            if normalize_key(props.key) == wanted:
                return KeyConflict(
                    sequence=wanted,
                    owner=owner,
                    owner_label=owner,
                    candidate_tool_id=tool_id,
                    source=_TOOL_SOURCE,
                )
    return None


def set_tool_key(
    layout: Layout,
    tool_id: str,
    sequence: str | None,
    *,
    force: bool = False,
    external: Iterable[KeyBinding] = (),
    profile_id: str | None = None,
) -> Layout:
    """Assign a key to a tool; refuse a conflict unless *force* is set.

    ``force=True`` is the «Назначить» branch of the conflict dialog.  When the
    conflict is another tool, that tool loses the key so the profile never
    keeps two identical bindings.  A conflict with an application shortcut is
    allowed to shadow it, because the dialog told the user which action it is.
    """
    conflict = find_key_conflict(layout, tool_id, sequence, external=external, profile_id=profile_id)
    if conflict is not None and not force:
        raise KeyConflictError(conflict)
    profile = _require_editable_profile(layout, profile_id)
    props = dict(profile.tool_props)
    if conflict is not None and conflict.source == _TOOL_SOURCE and conflict.owner in props:
        props[conflict.owner] = replace(props[conflict.owner], key=None)
    current = props.get(tool_id, ToolProps())
    props[tool_id] = replace(current, key=_clean_key(sequence))
    return _with_profile(layout, replace(profile, tool_props=MappingProxyType(props)))


def set_tool_after(layout: Layout, tool_id: str, after: str | None, *, profile_id: str | None = None) -> Layout:
    """Set «вернуться к выбору» / «оставить инструмент активным»."""
    if after is not None and after not in AFTER_OPTIONS:
        raise ValueError(f"Unknown after-measurement action: {after}")
    return _update_props(layout, tool_id, after=after, profile_id=profile_id)


def set_tool_labels(
    layout: Layout,
    tool_id: str,
    *,
    label_ru: str | None = None,
    label_en: str | None = None,
    profile_id: str | None = None,
) -> Layout:
    """Set optional per-language labels (an empty value restores the catalog one)."""
    return _update_props(
        layout,
        tool_id,
        label_ru=_clean_key(label_ru),
        label_en=_clean_key(label_en),
        profile_id=profile_id,
    )


def set_tool_show_in(
    layout: Layout,
    tool_id: str,
    show_in: Iterable[str],
    *,
    profile_id: str | None = None,
) -> Layout:
    """Set where the tool is offered (panel / quick / radial / palette)."""
    wanted = tuple(dict.fromkeys(item for item in show_in if item in SHOW_IN_OPTIONS))
    return _update_props(layout, tool_id, show_in=wanted, profile_id=profile_id)


def set_tool_hint(layout: Layout, tool_id: str, hint: str | None, *, profile_id: str | None = None) -> Layout:
    """Set the optional user hint shown in the tooltip."""
    return _update_props(layout, tool_id, hint=_clean_key(hint), profile_id=profile_id)


def tool_props(layout: Layout, tool_id: str, profile_id: str | None = None) -> ToolProps:
    """Properties of a tool (empty when the tool has none yet)."""
    profile = layout.profile(profile_id)
    if profile is None:
        return ToolProps()
    return profile.tool_props.get(tool_id, ToolProps())


def _update_props(
    layout: Layout,
    tool_id: str,
    *,
    profile_id: str | None = None,
    **changes: Any,
) -> Layout:
    profile = _require_editable_profile(layout, profile_id)
    props = dict(profile.tool_props)
    current = props.get(tool_id, ToolProps())
    filtered = {key: value for key, value in changes.items() if value is not _UNSET}
    props[tool_id] = replace(current, **filtered)
    return _with_profile(layout, replace(profile, tool_props=MappingProxyType(props)))


# ── Profiles ────────────────────────────────────────────────────────


def is_builtin_profile(profile: Profile) -> bool:
    """The built-in profile is read-only; users edit a duplicate."""
    return profile.id == BUILTIN_PROFILE_ID


def duplicate_profile(
    layout: Layout,
    source_id: str | None = None,
    *,
    new_id: str | None = None,
    name: str | None = None,
) -> Layout:
    """Create an editable copy of *source_id* and make it active."""
    source = _require_profile(layout, source_id)
    identifier = new_id or f"user-{uuid.uuid4().hex[:8]}"
    if layout.profile(identifier) is not None:
        raise ValueError(f"Profile already exists: {identifier}")
    copy = replace(
        source,
        id=identifier,
        name=(name or f"{source.name} (копия)").strip() or identifier,
        base=source.base or BUILTIN_PROFILE_ID,
    )
    return replace(
        layout,
        active_profile=identifier,
        profiles=(*layout.profiles, copy),
    )


def rename_profile(layout: Layout, name: str, *, profile_id: str | None = None) -> Layout:
    """Rename a user profile; the built-in one cannot be renamed."""
    profile = _require_profile(layout, profile_id)
    if is_builtin_profile(profile):
        raise ValueError("The built-in profile is read-only")
    wanted = name.strip()
    if not wanted:
        raise ValueError("A profile name cannot be empty")
    return _with_profile(layout, replace(profile, name=wanted))


def reset_profile(layout: Layout, *, profile_id: str | None = None) -> Layout:
    """Restore a user profile to the built-in defaults, keeping its identity."""
    profile = _require_profile(layout, profile_id)
    if is_builtin_profile(profile):
        raise ValueError("The built-in profile is read-only")
    builtin = _builtin_profile()
    restored = replace(
        profile,
        contexts=builtin.contexts,
        tool_props=MappingProxyType({}),
        radial=MappingProxyType({}),
        protocols=Protocols(),
    )
    return _with_profile(layout, restored)


def active_profile(layout: Layout) -> Profile:
    """The active profile; raises when the document is inconsistent."""
    return _require_profile(layout, None)


def use_profile(layout: Layout, profile_id: str) -> Layout:
    """Switch the active profile."""
    _require_profile(layout, profile_id)
    return replace(layout, active_profile=profile_id)


# ── Contexts ────────────────────────────────────────────────────────


def update_context(
    layout: Layout,
    context: str,
    *,
    inherit: bool | None = None,
    quick: Iterable[str] | None = None,
    favorites: Iterable[str] | None = None,
    sections: Iterable[Section] | None = None,
    profile_id: str | None = None,
) -> Layout:
    """Change one context of a profile.

    A context inherits «Общий» until the editor changes one of its lists or
    sections; changing data therefore turns inheritance off unless the caller
    explicitly asks for ``inherit=True``.
    """
    name = _require_context(context)
    profile = _require_editable_profile(layout, profile_id)
    current = profile.contexts.get(name, Context(name, inherit=name != CONTEXT_COMMON))
    data_changed = quick is not None or favorites is not None or sections is not None
    wanted_inherit = current.inherit if inherit is None else bool(inherit)
    if name == CONTEXT_COMMON:
        wanted_inherit = False
    elif data_changed and inherit is None:
        wanted_inherit = False
    updated = replace(
        current,
        inherit=wanted_inherit,
        quick=_unique(quick) if quick is not None else current.quick,
        favorites=_unique(favorites) if favorites is not None else current.favorites,
        sections=tuple(sections) if sections is not None else current.sections,
    )
    _validate_limits(updated)
    contexts = dict(profile.contexts)
    contexts[name] = updated
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts)))


def materialize_context(layout: Layout, context: str, *, profile_id: str | None = None) -> Layout:
    """Copy «Общий» into an inheriting context before the first local edit."""
    name = _require_context(context)
    if name == CONTEXT_COMMON:
        return layout
    profile = _require_editable_profile(layout, profile_id)
    current = profile.contexts.get(name)
    if current is not None and not current.inherit:
        return layout
    common = profile.contexts.get(CONTEXT_COMMON)
    if common is None:
        common = _builtin_profile().contexts[CONTEXT_COMMON]
    copied = Context(
        name,
        inherit=False,
        quick=common.quick,
        favorites=common.favorites,
        sections=common.sections,
    )
    contexts = dict(profile.contexts)
    contexts[name] = copied
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts)))


def set_context_quick(layout: Layout, context: str, tools: Iterable[str], *, profile_id: str | None = None) -> Layout:
    values = _unique(tools)
    _check_length(values, MAX_QUICK, "quick")
    layout = materialize_context(layout, context, profile_id=profile_id)
    return update_context(layout, context, quick=values, profile_id=profile_id)


def set_context_favorites(
    layout: Layout, context: str, tools: Iterable[str], *, profile_id: str | None = None
) -> Layout:
    values = _unique(tools)
    _check_length(values, MAX_FAVORITES, "favorites")
    layout = materialize_context(layout, context, profile_id=profile_id)
    return update_context(layout, context, favorites=values, profile_id=profile_id)


def set_tool_visible(
    layout: Layout,
    context: str,
    tool_id: str,
    visible: bool,
    *,
    profile_id: str | None = None,
) -> Layout:
    """Show or hide a tool in one context (materializing an inherited one)."""
    name = _require_context(context)
    layout = materialize_context(layout, name, profile_id=profile_id)
    profile = _require_editable_profile(layout, profile_id)
    current = profile.contexts[name]
    found = False
    blocks: list[Section] = []
    for block in current.sections:
        items = tuple(replace(item, visible=visible) if item.id == tool_id else item for item in block.items)
        found = found or any(item.id == tool_id for item in block.items)
        blocks.append(replace(block, items=items))
    if not found:
        raise KeyError(tool_id)
    contexts = dict(profile.contexts)
    contexts[name] = replace(current, sections=tuple(blocks))
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts)))


def set_section_visible(
    layout: Layout,
    context: str,
    section_key: str,
    visible: bool,
    *,
    profile_id: str | None = None,
) -> Layout:
    name = _require_context(context)
    layout = materialize_context(layout, name, profile_id=profile_id)
    profile = _require_editable_profile(layout, profile_id)
    current = profile.contexts[name]
    blocks = tuple(replace(block, visible=visible) if block.key == section_key else block for block in current.sections)
    if not any(block.key == section_key for block in current.sections):
        raise KeyError(section_key)
    contexts = dict(profile.contexts)
    contexts[name] = replace(current, sections=blocks)
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts)))


def add_tool(
    layout: Layout,
    context: str,
    tool_id: str,
    *,
    section_key: str | None = None,
    profile_id: str | None = None,
) -> Layout:
    """Place a catalog tool into a section of the context (idempotent)."""
    name = _require_context(context)
    layout = materialize_context(layout, name, profile_id=profile_id)
    profile = _require_editable_profile(layout, profile_id)
    current = profile.contexts[name]
    if any(item.id == tool_id for block in current.sections for item in block.items):
        return layout
    target = section_key or _default_section_for(tool_id, current.sections)
    if target is None and current.sections:
        target = current.sections[0].key
    if target is None:
        raise ValueError("The context has no sections")
    blocks = [
        replace(block, items=(*block.items, ToolItem(tool_id, True))) if block.key == target else block
        for block in current.sections
    ]
    contexts = dict(profile.contexts)
    contexts[name] = replace(current, sections=tuple(blocks))
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts)))


def move_tool(
    layout: Layout,
    context: str,
    tool_id: str,
    section_key: str,
    *,
    index: int | None = None,
    profile_id: str | None = None,
) -> Layout:
    """Move a tool into another section of the context (or reorder it)."""
    name = _require_context(context)
    layout = materialize_context(layout, name, profile_id=profile_id)
    profile = _require_editable_profile(layout, profile_id)
    current = profile.contexts[name]
    if not any(block.key == section_key for block in current.sections):
        raise KeyError(section_key)
    moved: ToolItem | None = None
    blocks: list[Section] = []
    for block in current.sections:
        kept: list[ToolItem] = []
        for item in block.items:
            if item.id == tool_id and moved is None:
                moved = item
                continue
            kept.append(item)
        blocks.append(replace(block, items=tuple(kept)))
    if moved is None:
        raise KeyError(tool_id)
    for block_index, block in enumerate(blocks):
        if block.key == section_key:
            items = list(block.items)
            position = len(items) if index is None else max(0, min(index, len(items)))
            items.insert(position, moved)
            blocks[block_index] = replace(block, items=tuple(items))
            break
    contexts = dict(profile.contexts)
    contexts[name] = replace(current, sections=tuple(blocks))
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts)))


def reset_context(layout: Layout, context: str, *, profile_id: str | None = None) -> Layout:
    """Restore one context: «Общий» to the built-in sections, others to inherit."""
    name = _require_context(context)
    profile = _require_editable_profile(layout, profile_id)
    contexts = dict(profile.contexts)
    if name == CONTEXT_COMMON:
        builtin = _builtin_profile().contexts[CONTEXT_COMMON]
        contexts[name] = replace(builtin, name=name)
    else:
        contexts.pop(name, None)
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts)))


def add_custom_section(
    layout: Layout,
    context: str,
    title: str,
    *,
    key: str | None = None,
    profile_id: str | None = None,
) -> tuple[Layout, str]:
    """Append a user section; returns the layout and the new section key."""
    name = _require_context(context)
    layout = materialize_context(layout, name, profile_id=profile_id)
    profile = _require_editable_profile(layout, profile_id)
    if _custom_sections(layout, profile_id=profile.id) >= MAX_CUSTOM_SECTIONS:
        raise ValueError(f"At most {MAX_CUSTOM_SECTIONS} user sections are allowed")
    section_key = key or f"{CUSTOM_SECTION_PREFIX}{uuid.uuid4().hex[:8]}"
    current = profile.contexts[name]
    if any(block.key == section_key for block in current.sections):
        raise ValueError(f"Section already exists: {section_key}")
    block = Section(key=section_key, title=title.strip() or None, items=())
    contexts = dict(profile.contexts)
    contexts[name] = replace(current, sections=(*current.sections, block))
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts))), section_key


def rename_section(
    layout: Layout,
    context: str,
    section_key: str,
    title: str,
    *,
    profile_id: str | None = None,
) -> Layout:
    name = _require_context(context)
    profile = _require_editable_profile(layout, profile_id)
    current = profile.contexts[name]
    if not section_key.startswith(CUSTOM_SECTION_PREFIX):
        raise ValueError("Built-in sections cannot be renamed")
    if not any(block.key == section_key for block in current.sections):
        raise KeyError(section_key)
    blocks = tuple(
        replace(block, title=title.strip() or None) if block.key == section_key else block for block in current.sections
    )
    contexts = dict(profile.contexts)
    contexts[name] = replace(current, sections=blocks)
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts)))


def delete_section(
    layout: Layout,
    context: str,
    section_key: str,
    *,
    profile_id: str | None = None,
) -> Layout:
    """Delete a user section; its tools return to their catalog sections."""
    name = _require_context(context)
    profile = _require_editable_profile(layout, profile_id)
    current = profile.contexts[name]
    if not section_key.startswith(CUSTOM_SECTION_PREFIX):
        raise ValueError("Built-in sections cannot be deleted")
    victim = next((block for block in current.sections if block.key == section_key), None)
    if victim is None:
        raise KeyError(section_key)
    dropped = {item.id for item in victim.items}
    blocks = [
        replace(block, items=tuple(item for item in block.items if item.id not in dropped))
        for block in current.sections
        if block.key != section_key
    ]
    by_key = {block.key: block for block in blocks}
    for item in victim.items:
        target = _default_section_for(item.id, blocks)
        if target is None:
            continue
        block = by_key[target]
        by_key[target] = replace(block, items=(*block.items, item))
    ordered = tuple(by_key[block.key] for block in blocks)
    contexts = dict(profile.contexts)
    contexts[name] = replace(current, sections=ordered)
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts)))


def move_section(
    layout: Layout,
    context: str,
    section_key: str,
    delta: int,
    *,
    profile_id: str | None = None,
) -> Layout:
    name = _require_context(context)
    profile = _require_editable_profile(layout, profile_id)
    current = profile.contexts[name]
    keys = [block.key for block in current.sections]
    if section_key not in keys:
        raise KeyError(section_key)
    source = keys.index(section_key)
    target = max(0, min(source + delta, len(keys) - 1))
    if target == source:
        return layout
    blocks = list(current.sections)
    blocks[source], blocks[target] = blocks[target], blocks[source]
    contexts = dict(profile.contexts)
    contexts[name] = replace(current, sections=tuple(blocks))
    return _with_profile(layout, replace(profile, contexts=MappingProxyType(contexts)))


# ── Radial menu ─────────────────────────────────────────────────────


def set_radial(
    layout: Layout,
    context: str,
    tools: Iterable[str],
    *,
    profile_id: str | None = None,
) -> Layout:
    """Set up to ``RADIAL_SECTORS`` tools for one context's radial menu."""
    name = _require_context(context)
    values = _unique(tools)
    _check_length(values, RADIAL_SECTORS, "radial")
    profile = _require_editable_profile(layout, profile_id)
    radial = dict(profile.radial)
    radial[name] = tuple(values)
    return _with_profile(layout, replace(profile, radial=MappingProxyType(radial)))


def radial(layout: Layout, context: str, profile_id: str | None = None) -> tuple[str, ...]:
    profile = layout.profile(profile_id)
    if profile is None:
        return ()
    return profile.radial.get(_require_context(context), ())


# ── Import / export ─────────────────────────────────────────────────


class LayoutImportError(ValueError):
    """A version-3 document could not be imported; current settings stay intact."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def export_layout(layout: Layout) -> str:
    """Serialize the current layout as the version-3 JSON document."""
    return encode_layout(layout)


def import_layout(text: str) -> Layout:
    """Parse a version-3 document strictly, or raise :class:`LayoutImportError`.

    Unlike :func:`decode_layout`, which treats malformed input as absent, an
    import failure must be explicit: the editor keeps its current model and
    shows the reason instead of silently replacing the user's settings.
    """
    if not isinstance(text, str) or not text.strip():
        raise LayoutImportError("empty")
    try:
        raw = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise LayoutImportError("json", str(exc)) from exc
    if not isinstance(raw, Mapping):
        raise LayoutImportError("not_object")
    if raw.get("version") != LAYOUT_VERSION:
        raise LayoutImportError("version", str(raw.get("version")))
    _validate_import_document(raw)
    layout = decode_layout(text)
    if layout is None:
        raise LayoutImportError("profiles")
    return layout


def _validate_import_document(raw: Mapping[str, object]) -> None:
    profiles = raw.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise LayoutImportError("profiles")
    identifiers: list[str] = []
    custom_sections = 0
    for entry in profiles:
        if not isinstance(entry, Mapping):
            raise LayoutImportError("profile")
        profile_id = entry.get("id")
        name = entry.get("name")
        if not isinstance(profile_id, str) or not profile_id:
            raise LayoutImportError("profile", "id")
        if not isinstance(name, str) or not name.strip():
            raise LayoutImportError("profile", "name")
        if profile_id in identifiers:
            raise LayoutImportError("duplicate_profile", profile_id)
        identifiers.append(profile_id)
        contexts = entry.get("contexts")
        if contexts is None:
            continue
        if not isinstance(contexts, Mapping):
            raise LayoutImportError("contexts", profile_id)
        for context_name, context in contexts.items():
            if context_name not in SETTINGS_CONTEXTS:
                raise LayoutImportError("context", str(context_name))
            if not isinstance(context, Mapping):
                raise LayoutImportError("context", str(context_name))
            _validate_id_list(context.get("quick"), "quick", MAX_QUICK)
            _validate_id_list(context.get("favorites"), "favorites", MAX_FAVORITES)
            sections = context.get("sections")
            if sections is None:
                continue
            if not isinstance(sections, list):
                raise LayoutImportError("sections", str(context_name))
            for block in sections:
                if not isinstance(block, Mapping):
                    raise LayoutImportError("sections", str(context_name))
                key = block.get("key")
                if not isinstance(key, str) or not key:
                    raise LayoutImportError("sections", "key")
                if key.startswith(CUSTOM_SECTION_PREFIX):
                    custom_sections += 1
                items = block.get("items", [])
                if not isinstance(items, list):
                    raise LayoutImportError("sections", key)
                for item in items:
                    if not isinstance(item, Mapping):
                        raise LayoutImportError("sections", key)
                    item_id = item.get("id")
                    if not isinstance(item_id, str) or not item_id:
                        raise LayoutImportError("sections", "id")
    if custom_sections > MAX_CUSTOM_SECTIONS * len(SETTINGS_CONTEXTS):
        raise LayoutImportError("sections", "too many user sections")
    for entry in profiles:
        radial = entry.get("radial")
        if radial is None:
            continue
        if not isinstance(radial, Mapping):
            raise LayoutImportError("radial")
        for context_name, tools in radial.items():
            if context_name not in SETTINGS_CONTEXTS:
                raise LayoutImportError("context", str(context_name))
            _validate_id_list(tools, "radial", RADIAL_SECTORS)
    active = raw.get("active_profile")
    if not isinstance(active, str) or active not in identifiers:
        raise LayoutImportError("active_profile", str(active))
    unknown = raw.get("unknown_items", [])
    if not isinstance(unknown, list) or any(not isinstance(item, str) for item in unknown):
        raise LayoutImportError("unknown_items")


def _validate_id_list(value: object, reason: str, limit: int) -> None:
    if value is None:
        return
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise LayoutImportError(reason)
    if len(value) > limit:
        raise LayoutImportError(reason, f"at most {limit} entries")


# ── Undo / redo ─────────────────────────────────────────────────────


class UndoStack:
    """A bounded undo history over immutable :class:`Layout` snapshots."""

    def __init__(self, state: Layout, *, limit: int = 100) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        self._states: list[Layout] = [state]
        self._index = 0
        self._limit = limit

    @property
    def current(self) -> Layout:
        return self._states[self._index]

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    def push(self, state: Layout) -> bool:
        """Record a new state; returns ``False`` when nothing changed."""
        if state == self.current:
            return False
        del self._states[self._index + 1 :]
        self._states.append(state)
        if len(self._states) > self._limit:
            drop = len(self._states) - self._limit
            del self._states[:drop]
        self._index = len(self._states) - 1
        return True

    def undo(self) -> Layout | None:
        if not self.can_undo:
            return None
        self._index -= 1
        return self.current

    def redo(self) -> Layout | None:
        if not self.can_redo:
            return None
        self._index += 1
        return self.current

    def reset(self, state: Layout) -> None:
        self._states = [state]
        self._index = 0


# ── Helpers ─────────────────────────────────────────────────────────


def _builtin_profile() -> Profile:
    profile = default_layout().profile(BUILTIN_PROFILE_ID)
    if profile is None:  # pragma: no cover - default_layout always has it
        raise RuntimeError("The built-in profile is missing")
    return profile


def _require_profile(layout: Layout, profile_id: str | None) -> Profile:
    profile = layout.profile(profile_id)
    if profile is None:
        raise KeyError(profile_id or layout.active_profile)
    return profile


def _require_editable_profile(layout: Layout, profile_id: str | None) -> Profile:
    profile = _require_profile(layout, profile_id)
    if is_builtin_profile(profile):
        raise ValueError("The built-in profile is read-only")
    return profile


def _with_profile(layout: Layout, profile: Profile) -> Layout:
    profiles = tuple(profile if item.id == profile.id else item for item in layout.profiles)
    return replace(layout, profiles=profiles)


def _require_context(context: str) -> str:
    if context not in SETTINGS_CONTEXTS:
        raise ValueError(f"Unknown settings context: {context}")
    return context


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in values if item))


def _check_length(values: Sequence[str], limit: int, reason: str) -> None:
    if len(values) > limit:
        raise ValueError(f"At most {limit} entries are allowed ({reason})")


def _validate_limits(context: Context) -> None:
    _check_length(context.quick, MAX_QUICK, "quick")
    _check_length(context.favorites, MAX_FAVORITES, "favorites")


def _custom_sections(layout: Layout, *, profile_id: str | None = None) -> int:
    profile = _require_profile(layout, profile_id)
    return sum(
        1
        for context in profile.contexts.values()
        for block in context.sections
        if block.key.startswith(CUSTOM_SECTION_PREFIX)
    )


def _default_section_for(tool_id: str, blocks: Sequence[Section]) -> str | None:
    for block in blocks:
        spec = SECTIONS.get(block.key)
        if spec is None:
            continue
        if any(tool.id == tool_id for tool in tools_in_section(spec.id)):
            return block.key
    return None
