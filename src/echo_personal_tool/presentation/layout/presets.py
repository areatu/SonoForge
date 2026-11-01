"""Layout presets, the version-2 layout document and the slot table (UI-2 PR-1, PR-2).

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
3. :data:`SLOT_TABLE` maps ``(preset, tool-button view, multiview)`` to the
   slots ``left / center / right / bottom`` and to the top of the snapshot
   column. The window fills the slots from the table instead of branching on
   flags (``_decide_left`` / ``_decide_right`` are gone).
4. UI-2 PR-2: the window and the settings read the stored keys through
   :func:`resolve_document` (v2 → migrated v1 → defaults), and the five
   version-1 checkboxes are gone from the menu. ``migrate_v1`` stays for old
   installs; the reverse projection (v2 → v1 flags) left with the checkboxes.

UI-2 PR-3 added the rest: ``tool_buttons`` is now resolved by
:func:`resolve_buttons` (``auto`` reads the default of the preset, §4.2), the
snapshot column carries the tool row when the buttons sit above the image
(:data:`SLOT_TOOL_ROW`, painted by ``presentation/tool_buttons/row.py``), and
``rail`` is the new catalog-driven rail (``tool_buttons/rail.py``) rather than the
interim activity bar. ``panel`` still means "no row and no rail": the tools block
of the panel is TP-2's own deliverable.
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

#: The views a document can resolve to (``auto`` is never one of them).
TOOL_BUTTONS_ROW: Final = "row"
TOOL_BUTTONS_RAIL: Final = "rail"
TOOL_BUTTONS_PANEL: Final = "panel"
RESOLVED_TOOL_BUTTON_MODES: Final = (TOOL_BUTTONS_ROW, TOOL_BUTTONS_RAIL, TOOL_BUTTONS_PANEL)

#: §4.2 — the button view a preset starts with when the user chose «Авто».
DEFAULT_TOOL_BUTTONS: Final[Mapping[str, str]] = {
    PRESET_CLASSIC: TOOL_BUTTONS_ROW,
    PRESET_MIRRORED: TOOL_BUTTONS_ROW,
    PRESET_FILMSTRIP: TOOL_BUTTONS_RAIL,
}

TOOL_LABEL_MODES: Final = ("icons_labels", "icons")

# Slot names used by the table. ``split`` is the viewer and the tool panel in
# one splitter (the classic layout); ``panes`` is the two Multiview panes.
SLOT_GALLERY: Final = "gallery"
SLOT_TOOL_PANEL: Final = "tool_panel"
SLOT_RAIL: Final = "rail"
SLOT_VIEWER: Final = "viewer"
SLOT_SPLIT: Final = "split"
SLOT_PANES: Final = "panes"
#: The tool row, which is not a slot of the content row but the top of the
#: snapshot column (§4.1) — hence a separate field of :class:`SlotPlan`.  In
#: Multiview the row is never assembled: stage 1 refuses those tools outright
#: (§10.2 of the comparison spec), so a strip of dim buttons would be noise.
SLOT_TOOL_ROW: Final = "tool_row"


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
    def buttons_mode(self) -> str:
        """The button view actually assembled: ``row``, ``rail`` or ``panel``."""
        return resolve_buttons(self)

    @property
    def rail(self) -> bool:
        """True when the tool buttons sit in the narrow rail left of the image."""
        return resolve_buttons(self) == TOOL_BUTTONS_RAIL

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
            return replace(defaults, **values)  # type: ignore[arg-type]  # mypy does not check this file (outside tool.mypy.files)
        except ValueError:
            return _repair(defaults, values)


def _repair(defaults: LayoutConfigV2, values: Mapping[str, object]) -> LayoutConfigV2:
    """Keep every valid field and reset only the invalid ones."""
    kept: dict[str, object] = {}
    for name, value in values.items():
        try:
            replace(defaults, **{name: value})  # type: ignore[arg-type]  # mypy does not check this file (outside tool.mypy.files)
        except ValueError:
            continue
        kept[name] = value
    return replace(defaults, **kept)  # type: ignore[arg-type]  # mypy does not check this file (outside tool.mypy.files)


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


def resolve_document(v2_raw: str, v1_raw: str) -> LayoutConfigV2:
    """The layout document for the stored keys (spec §8.1).

    Precedence: the version-2 document → the version-1 flags through
    :func:`migrate_v1` → the defaults. An unreadable version-2 text falls
    through to version 1 instead of discarding the user's older settings.
    A fresh install (both keys empty) gets the classic preset.
    """
    if v2_raw:
        document = LayoutConfigV2.from_json(v2_raw)
        if document is not None:
            return document
    if v1_raw:
        try:
            flags = json.loads(v1_raw)
        except (TypeError, ValueError):
            return LayoutConfigV2()
        if isinstance(flags, dict):
            return migrate_v1(flags)
    return LayoutConfigV2()


@dataclass(frozen=True)
class SlotPlan:
    """What sits in each slot of the content row; ``None`` means the slot is empty.

    ``top`` is not a slot of the content row: it is the head of the snapshot
    column (§4.1), which is why the plan names it separately — the row is glued to
    the image and travels with it into the splitter, whatever side slots the preset
    picked.
    """

    left: str | None
    center: str
    right: str | None
    bottom: str | None = None
    top: str | None = None


#: ``(preset, tool-buttons mode, multiview)`` → slots.  Two rules the table
#: encodes instead of the window: the tool panel is glued to the image inside the
#: centre splitter only in the classic preset without Multiview (that is the one
#: arrangement with a resize handle between the image and the panel), and the rail
#: takes the side slot where the panel would sit — except in the filmstrip, where
#: both sides are free and the rail goes left of the snapshot (§4.2).
SLOT_TABLE: Final[Mapping[tuple[str, str, bool], SlotPlan]] = {
    (PRESET_CLASSIC, TOOL_BUTTONS_ROW, False): SlotPlan(SLOT_GALLERY, SLOT_SPLIT, None, None, top=SLOT_TOOL_ROW),
    (PRESET_CLASSIC, TOOL_BUTTONS_RAIL, False): SlotPlan(SLOT_GALLERY, SLOT_VIEWER, SLOT_RAIL),
    (PRESET_CLASSIC, TOOL_BUTTONS_PANEL, False): SlotPlan(SLOT_GALLERY, SLOT_SPLIT, None),
    (PRESET_MIRRORED, TOOL_BUTTONS_ROW, False): SlotPlan(
        SLOT_TOOL_PANEL, SLOT_VIEWER, SLOT_GALLERY, None, top=SLOT_TOOL_ROW
    ),
    (PRESET_MIRRORED, TOOL_BUTTONS_RAIL, False): SlotPlan(SLOT_RAIL, SLOT_VIEWER, SLOT_GALLERY),
    (PRESET_MIRRORED, TOOL_BUTTONS_PANEL, False): SlotPlan(SLOT_TOOL_PANEL, SLOT_VIEWER, SLOT_GALLERY),
    (PRESET_FILMSTRIP, TOOL_BUTTONS_ROW, False): SlotPlan(
        None, SLOT_VIEWER, SLOT_TOOL_PANEL, SLOT_GALLERY, top=SLOT_TOOL_ROW
    ),
    (PRESET_FILMSTRIP, TOOL_BUTTONS_RAIL, False): SlotPlan(SLOT_RAIL, SLOT_VIEWER, SLOT_TOOL_PANEL, SLOT_GALLERY),
    (PRESET_FILMSTRIP, TOOL_BUTTONS_PANEL, False): SlotPlan(None, SLOT_VIEWER, SLOT_TOOL_PANEL, SLOT_GALLERY),
    (PRESET_CLASSIC, TOOL_BUTTONS_ROW, True): SlotPlan(SLOT_GALLERY, SLOT_PANES, SLOT_TOOL_PANEL),
    (PRESET_CLASSIC, TOOL_BUTTONS_RAIL, True): SlotPlan(SLOT_GALLERY, SLOT_PANES, SLOT_RAIL),
    (PRESET_CLASSIC, TOOL_BUTTONS_PANEL, True): SlotPlan(SLOT_GALLERY, SLOT_PANES, SLOT_TOOL_PANEL),
    (PRESET_MIRRORED, TOOL_BUTTONS_ROW, True): SlotPlan(SLOT_TOOL_PANEL, SLOT_PANES, SLOT_GALLERY),
    (PRESET_MIRRORED, TOOL_BUTTONS_RAIL, True): SlotPlan(SLOT_RAIL, SLOT_PANES, SLOT_GALLERY),
    (PRESET_MIRRORED, TOOL_BUTTONS_PANEL, True): SlotPlan(SLOT_TOOL_PANEL, SLOT_PANES, SLOT_GALLERY),
    (PRESET_FILMSTRIP, TOOL_BUTTONS_ROW, True): SlotPlan(None, SLOT_PANES, SLOT_TOOL_PANEL, SLOT_GALLERY),
    (PRESET_FILMSTRIP, TOOL_BUTTONS_RAIL, True): SlotPlan(SLOT_RAIL, SLOT_PANES, SLOT_TOOL_PANEL, SLOT_GALLERY),
    (PRESET_FILMSTRIP, TOOL_BUTTONS_PANEL, True): SlotPlan(None, SLOT_PANES, SLOT_TOOL_PANEL, SLOT_GALLERY),
}


def resolve_buttons(config: LayoutConfigV2) -> str:
    """The button view of ``config``, with ``auto`` read against its preset.

    §4.2: «Классическая» and «Зеркальная» start with the row over the image,
    «Лента снизу» — with the rail left of it.  A user who picked a view
    explicitly is never overridden by the preset.
    """
    if config.tool_buttons != TOOL_BUTTONS_AUTO:
        return config.tool_buttons
    return DEFAULT_TOOL_BUTTONS[config.preset]


def slot_plan(config: LayoutConfigV2, *, multiview: bool) -> SlotPlan:
    """The slots of ``config`` with or without Multiview (a session mode, not stored)."""
    return SLOT_TABLE[(config.preset, resolve_buttons(config), multiview)]


#: On physically narrow windows the classic side gallery gives up its two-column
#: grid for a one-tile filmstrip, leaving room for the viewer and right panel.
COMPACT_SIDE_GALLERY_MAX_PHYSICAL_WIDTH = 1600


def gallery_mode_for_plan(plan: SlotPlan, *, physical_window_width: float) -> tuple[bool, bool]:
    """Return ``(horizontal, compact_side_panel)`` for the plan and window width.

    A gallery in the right side slot is always a compact horizontal strip. The
    classic left gallery stays a grid on wide windows, but switches to the same
    one-tile strip below 1600 physical pixels. Using the physical width keeps
    1366 px displays consistent at both 100 % (1366 logical px) and 150 %
    (about 911 logical px).
    """
    gallery_in_side_slot = SLOT_GALLERY in (plan.left, plan.right)
    narrow_side_gallery = gallery_in_side_slot and physical_window_width < COMPACT_SIDE_GALLERY_MAX_PHYSICAL_WIDTH
    right_gallery = plan.right == SLOT_GALLERY
    compact_side_panel = right_gallery or narrow_side_gallery
    horizontal = plan.bottom == SLOT_GALLERY or right_gallery or narrow_side_gallery
    return horizontal, compact_side_panel
