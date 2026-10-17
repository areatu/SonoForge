"""Layout presets, the version-2 layout document and the slot table (UI-2 PR-1).

Spec: ``docs/superpowers/specs/2026-10-16-ui-redesign-spec-plan-ru.md`` §4.2
(presets), §8.1 (``LayoutConfig`` v2, migration v1 → v2, assembly).

The module is pure: no Qt and no infrastructure, so the migration and the
table can be tested without a window.

What this PR guarantees:

1. ``LayoutConfigV2`` is stored under a **new** key (``layout_state_v2_json``).
   The version-1 key ``layout_state_json`` is only read for migration and is
   never overwritten, so a rollback to an older build still sees its own
   settings.
2. :func:`migrate_v1` is a deterministic function of the four persisted v1
   flags (``swap_places``, ``gallery_horizontal``, ``activity_bar``,
   ``status_bar_visible``); the 16 combinations are pinned by tests.
3. :data:`SLOT_TABLE` maps ``(preset, rail, multiview)`` to the slots
   ``left / center / right / bottom``. The window fills the slots from the
   table instead of branching on flags (``_decide_left`` / ``_decide_right``
   are gone).

``tool_buttons`` values ``row`` and ``panel`` belong to UI-2 PR-3 (the tool
row and the tools block of the panel). They are accepted by the document but
the assembly treats them as ``auto`` until that PR lands.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Final

#: Version of the document stored in ``layout_state_v2_json``.
LAYOUT_VERSION: Final = 2

PRESET_CLASSIC: Final = "classic"
PRESET_MIRRORED: Final = "mirrored"
PRESET_FILMSTRIP: Final = "filmstrip"
PRESETS: Final = (PRESET_CLASSIC, PRESET_MIRRORED, PRESET_FILMSTRIP)

TOOL_BUTTONS_AUTO: Final = "auto"
TOOL_BUTTON_MODES: Final = (TOOL_BUTTONS_AUTO, "row", "rail", "panel")

TOOL_LABEL_MODES: Final = ("icons_labels", "icons")

# Slot names used by the table. ``split`` is the viewer and the tool panel in
# one splitter (the classic layout); ``panes`` is the two Multiview panes.
SLOT_GALLERY: Final = "gallery"
SLOT_TOOL_PANEL: Final = "tool_panel"
SLOT_RAIL: Final = "rail"
SLOT_VIEWER: Final = "viewer"
SLOT_SPLIT: Final = "split"
SLOT_PANES: Final = "panes"


@dataclass(frozen=True)
class LayoutConfigV2:
    """The user-facing layout document (spec §8.1). Immutable: replace, never mutate."""

    preset: str = PRESET_CLASSIC
    tool_buttons: str = TOOL_BUTTONS_AUTO
    tool_labels: str = "icons_labels"
    status_bar_visible: bool = True
    single_file_focus: bool = True

    def __post_init__(self) -> None:
        if self.preset not in PRESETS:
            raise ValueError(f"unknown layout preset: {self.preset!r}")
        if self.tool_buttons not in TOOL_BUTTON_MODES:
            raise ValueError(f"unknown tool-buttons mode: {self.tool_buttons!r}")
        if self.tool_labels not in TOOL_LABEL_MODES:
            raise ValueError(f"unknown tool-labels mode: {self.tool_labels!r}")

    @property
    def rail(self) -> bool:
        """True when the tool buttons sit in the narrow rail (the old activity bar)."""
        return self.tool_buttons == "rail"

    def to_json(self) -> str:
        document = {
            "version": LAYOUT_VERSION,
            "preset": self.preset,
            "tool_buttons": self.tool_buttons,
            "tool_labels": self.tool_labels,
            "status_bar_visible": self.status_bar_visible,
            "single_file_focus": self.single_file_focus,
        }
        return json.dumps(document, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> LayoutConfigV2 | None:
        """Parse a stored document; ``None`` when the text is not a version-2 document.

        A field with an unknown value falls back to its default instead of
        discarding the whole document: a newer build may have added a value.
        """
        try:
            document = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(document, dict) or document.get("version") != LAYOUT_VERSION:
            return None
        defaults = cls()
        values: dict[str, object] = {}
        for name in ("preset", "tool_buttons", "tool_labels"):
            value = document.get(name)
            if isinstance(value, str):
                values[name] = value
        for name in ("status_bar_visible", "single_file_focus"):
            value = document.get(name)
            if isinstance(value, bool):
                values[name] = value
        try:
            return replace(defaults, **values)  # type: ignore[arg-type]
        except ValueError:
            return _repair(defaults, values)


def _repair(defaults: LayoutConfigV2, values: Mapping[str, object]) -> LayoutConfigV2:
    """Keep every valid field and reset only the invalid ones."""
    kept: dict[str, object] = {}
    for name, value in values.items():
        try:
            replace(defaults, **{name: value})  # type: ignore[arg-type]
        except ValueError:
            continue
        kept[name] = value
    return replace(defaults, **kept)  # type: ignore[arg-type]


def _flag(flags: Mapping[str, object], name: str, *, default: bool) -> bool:
    value = flags.get(name, default)
    return value if isinstance(value, bool) else default


def migrate_v1(flags: Mapping[str, object]) -> LayoutConfigV2:
    """Migrate the version-1 flags to the version-2 document (spec §8.1).

    ``gallery_horizontal`` wins over ``swap_places``: the filmstrip is the more
    prominent change, so a user who had both gets the filmstrip with the tool
    panel on the right. ``activity_bar`` becomes ``tool_buttons = "rail"`` on
    top of the preset. ``status_bar_visible`` is carried over as it is.
    """
    gallery = _flag(flags, "gallery_horizontal", default=False)
    swap = _flag(flags, "swap_places", default=False)
    activity = _flag(flags, "activity_bar", default=False)
    status = _flag(flags, "status_bar_visible", default=True)
    if gallery:
        preset = PRESET_FILMSTRIP
    elif swap:
        preset = PRESET_MIRRORED
    else:
        preset = PRESET_CLASSIC
    return LayoutConfigV2(
        preset=preset,
        tool_buttons="rail" if activity else TOOL_BUTTONS_AUTO,
        status_bar_visible=status,
    )


def flags_for(config: LayoutConfigV2) -> dict[str, bool]:
    """The version-1 flags that describe ``config`` (for the checkbox menu of PR-1)."""
    return {
        "swap_places": config.preset == PRESET_MIRRORED,
        "gallery_horizontal": config.preset == PRESET_FILMSTRIP,
        "activity_bar": config.rail,
        "status_bar_visible": config.status_bar_visible,
    }


@dataclass(frozen=True)
class SlotPlan:
    """What sits in each slot of the content row; ``None`` means the slot is empty."""

    left: str | None
    center: str
    right: str | None
    bottom: str | None


#: ``(preset, rail, multiview)`` → slots. Multiview replaces the centre with the
#: two panes in every preset; the side slots follow the preset as before.
SLOT_TABLE: Final[Mapping[tuple[str, bool, bool], SlotPlan]] = {
    (PRESET_CLASSIC, False, False): SlotPlan(SLOT_GALLERY, SLOT_SPLIT, None, None),
    (PRESET_CLASSIC, True, False): SlotPlan(SLOT_GALLERY, SLOT_VIEWER, SLOT_RAIL, None),
    (PRESET_MIRRORED, False, False): SlotPlan(SLOT_TOOL_PANEL, SLOT_VIEWER, SLOT_GALLERY, None),
    (PRESET_MIRRORED, True, False): SlotPlan(SLOT_RAIL, SLOT_VIEWER, SLOT_GALLERY, None),
    (PRESET_FILMSTRIP, False, False): SlotPlan(None, SLOT_VIEWER, SLOT_TOOL_PANEL, SLOT_GALLERY),
    (PRESET_FILMSTRIP, True, False): SlotPlan(None, SLOT_VIEWER, SLOT_RAIL, SLOT_GALLERY),
    (PRESET_CLASSIC, False, True): SlotPlan(SLOT_GALLERY, SLOT_PANES, SLOT_TOOL_PANEL, None),
    (PRESET_CLASSIC, True, True): SlotPlan(SLOT_GALLERY, SLOT_PANES, SLOT_RAIL, None),
    (PRESET_MIRRORED, False, True): SlotPlan(SLOT_TOOL_PANEL, SLOT_PANES, SLOT_GALLERY, None),
    (PRESET_MIRRORED, True, True): SlotPlan(SLOT_RAIL, SLOT_PANES, SLOT_GALLERY, None),
    (PRESET_FILMSTRIP, False, True): SlotPlan(None, SLOT_PANES, SLOT_TOOL_PANEL, SLOT_GALLERY),
    (PRESET_FILMSTRIP, True, True): SlotPlan(None, SLOT_PANES, SLOT_RAIL, SLOT_GALLERY),
}


def slot_plan(config: LayoutConfigV2, *, multiview: bool) -> SlotPlan:
    """The slots of ``config`` with or without Multiview (a session mode, not stored)."""
    return SLOT_TABLE[(config.preset, config.rail, multiview)]
