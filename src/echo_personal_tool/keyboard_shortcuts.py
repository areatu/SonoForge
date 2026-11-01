"""Canonical registry for SonoForge keyboard shortcuts and key hints.

The registry is intentionally dependency-light: shortcut metadata can be used
by the application, domain presentation, native Qt widgets, tooltips, and the
user guide without importing Qt at module import time.  Keep only bindings
that have a real handler in the current application; a key mentioned in an
older document is not evidence that it is active.
"""

from __future__ import annotations

import json
import re
import sys
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

from echo_personal_tool.infrastructure.i18n import get_language, tr_for_language


@dataclass(frozen=True, slots=True)
class ShortcutSpec:
    """One user-facing input binding.

    ``sequences`` use Qt's portable key-sequence notation for keyboard
    shortcuts. A gesture uses the same field for display, but is never passed
    to ``QShortcut``. ``context`` is the collision domain used by the conflict
    checker and is also part of the shortcut's documented scope.
    """

    id: str
    sequences: tuple[str, ...]
    description_key: str
    group_key: str
    context: str
    kind: str = "keyboard"
    main_window_shortcut: bool = False
    profiles: frozenset[str] = frozenset()
    key_label_key: str = ""


# Keep declarations in display order. QShortcut installation, inline hints,
# the in-app guide, and the checked-in HELP shortcut sections all read this
# table rather than maintaining their own key lists.
SHORTCUTS: tuple[ShortcutSpec, ...] = (
    ShortcutSpec(
        "open_folder",
        ("Ctrl+O",),
        "shortcuts.action.open_folder",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "load_server",
        ("Ctrl+P",),
        "shortcuts.action.load_server",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "command_field",
        ("Ctrl+K",),
        "shortcuts.action.command_field",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "panel_search",
        ("/",),
        "shortcuts.action.panel_search",
        "shortcuts.group.main",
        "main-window",
    ),
    ShortcutSpec(
        # UI-5 §4.7: the S2 norm card of the focused measurement row.  The row
        # handles the key itself (no global QShortcut) so N in a text field
        # stays a letter, but the binding lives in the main-window context so
        # the conflict checker keeps it unclaimed.
        "reference_card",
        ("N",),
        "shortcuts.action.reference_card",
        "shortcuts.group.main",
        "main-window",
    ),
    ShortcutSpec(
        "caliper",
        ("L",),
        "shortcuts.action.caliper",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "manual_contour",
        ("C",),
        "shortcuts.action.manual_contour",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "model_contour",
        ("M",),
        "shortcuts.action.model_contour",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "auto_segment",
        ("I",),
        "shortcuts.action.auto_segment",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "finish_tool",
        ("Enter", "Return"),
        "shortcuts.action.finish_tool",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "cancel_tool",
        ("Escape",),
        "shortcuts.action.cancel_tool",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "skip_step",
        ("S",),
        "shortcuts.action.skip_step",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "delete_selection",
        ("Delete", "Backspace"),
        "shortcuts.action.delete_selection",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "measurement_undo",
        ("Ctrl+Z",),
        "shortcuts.action.measurement_undo",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "measurement_redo",
        ("Ctrl+Y", "Ctrl+Shift+Z"),
        "shortcuts.action.measurement_redo",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "toggle_gallery",
        ("`",),
        "shortcuts.action.toggle_gallery",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "toggle_fullscreen",
        ("F11",),
        "shortcuts.action.toggle_fullscreen",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "gallery_previous",
        ("Up",),
        "shortcuts.action.gallery_previous",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "gallery_next",
        ("Down",),
        "shortcuts.action.gallery_next",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "new_tab",
        ("Ctrl+T",),
        "shortcuts.action.new_tab",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "next_tab",
        ("Ctrl+Tab",),
        "shortcuts.action.next_tab",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "previous_tab",
        ("Ctrl+Shift+Tab",),
        "shortcuts.action.previous_tab",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "close_tab",
        ("Ctrl+W",),
        "shortcuts.action.close_tab",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "presenter_toggle",
        ("F10",),
        "shortcuts.action.presenter_toggle",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
        profiles=frozenset({"presenter"}),
    ),
    # UI-4 PR-1 (spec §4.6): the candidate Ctrl+R is free in «main-window» —
    # its only other binding refreshes the Orthanc dialog list, an
    # independent window context (shortcut_conflicts() stays empty).
    ShortcutSpec(
        "toggle_report_mode",
        ("Ctrl+R",),
        "shortcuts.action.toggle_report_mode",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    # UI-6 (spec §4.8, UQ-02): F is the way in and out of the single-file focus
    # view.  F10/F11/F5 are taken; F itself was free in «main-window», and
    # Ctrl+F belongs to the Orthanc dialog's own context.
    ShortcutSpec(
        "toggle_focus_mode",
        ("F",),
        "shortcuts.action.toggle_focus_mode",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    # UI-7 (spec §4.10): Ctrl+F focuses the study-browser search on the start
    # page.  The other Ctrl+F bindings live in independent window contexts
    # («orthanc-dialog», «reference-constructor»); the main-window handler
    # no-ops while a study is open, so the key stays free there in practice.
    ShortcutSpec(
        "start_page_search",
        ("Ctrl+F",),
        "shortcuts.action.start_page_search",
        "shortcuts.group.main",
        "main-window",
        main_window_shortcut=True,
    ),
    ShortcutSpec(
        "play_pause",
        ("Space",),
        "shortcuts.action.play_pause",
        "shortcuts.group.viewer",
        "main-viewer",
        key_label_key="shortcuts.key.space",
    ),
    ShortcutSpec(
        "calibration_toggle",
        ("K",),
        "shortcuts.action.calibration_toggle",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "calibration_clear",
        ("Shift+K",),
        "shortcuts.action.calibration_clear",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "cycle_caliper_label",
        ("Tab",),
        "shortcuts.action.cycle_caliper_label",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "doppler_interval",
        ("T",),
        "shortcuts.action.doppler_interval",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "vti_trace",
        ("V",),
        "shortcuts.action.vti_trace",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "refine_contour",
        ("R",),
        "shortcuts.action.refine_contour",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "ghost_toggle",
        ("G",),
        "shortcuts.action.ghost_toggle",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "ghost_neighbor",
        ("Shift+G",),
        "shortcuts.action.ghost_neighbor",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "ghost_previous",
        ("[",),
        "shortcuts.action.ghost_previous",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "ghost_next",
        ("]",),
        "shortcuts.action.ghost_next",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "magnifier_hold",
        ("Z",),
        "shortcuts.action.magnifier_hold",
        "shortcuts.group.viewer",
        "main-viewer",
    ),
    ShortcutSpec(
        "vessel_psv",
        ("P",),
        "shortcuts.action.vessel_psv",
        "shortcuts.group.viewer_only",
        "viewer",
    ),
    ShortcutSpec(
        "debug_overlay",
        ("Ctrl+Shift+D",),
        "shortcuts.action.debug_overlay",
        "shortcuts.group.viewer_only",
        "viewer",
    ),
    ShortcutSpec(
        "zoom_in",
        ("+", "="),
        "shortcuts.action.zoom_in",
        "shortcuts.group.viewer_only",
        "viewer",
    ),
    ShortcutSpec(
        "zoom_out",
        ("-",),
        "shortcuts.action.zoom_out",
        "shortcuts.group.viewer_only",
        "viewer",
    ),
    ShortcutSpec(
        "zoom_fit",
        ("0",),
        "shortcuts.action.zoom_fit",
        "shortcuts.group.viewer_only",
        "viewer",
    ),
    ShortcutSpec(
        "vessel_previous_cycle",
        ("Left",),
        "shortcuts.action.vessel_previous_cycle",
        "shortcuts.group.viewer_only",
        "viewer",
    ),
    ShortcutSpec(
        "vessel_next_cycle",
        ("Right",),
        "shortcuts.action.vessel_next_cycle",
        "shortcuts.group.viewer_only",
        "viewer",
    ),
    ShortcutSpec(
        "strain_palette",
        ("C",),
        "shortcuts.action.strain_palette",
        "shortcuts.group.other",
        "strain-window",
    ),
    ShortcutSpec(
        "presenter_close",
        ("F10", "Escape"),
        "shortcuts.action.presenter_close",
        "shortcuts.group.other",
        "presenter-window",
        profiles=frozenset({"presenter"}),
    ),
    ShortcutSpec(
        "orthanc_focus_search",
        ("Ctrl+F",),
        "shortcuts.action.orthanc_focus_search",
        "shortcuts.group.other",
        "orthanc-dialog",
    ),
    ShortcutSpec(
        "orthanc_toggle_study",
        ("Space",),
        "shortcuts.action.orthanc_toggle_study",
        "shortcuts.group.other",
        "orthanc-dialog",
        key_label_key="shortcuts.key.space",
    ),
    ShortcutSpec(
        "orthanc_refresh",
        ("F5", "Ctrl+R"),
        "shortcuts.action.orthanc_refresh",
        "shortcuts.group.other",
        "orthanc-dialog",
    ),
    ShortcutSpec(
        "orthanc_select_all",
        ("Ctrl+A",),
        "shortcuts.action.orthanc_select_all",
        "shortcuts.group.other",
        "orthanc-dialog",
    ),
    ShortcutSpec(
        "reference_window_find",
        ("Ctrl+F",),
        "shortcuts.action.reference_window_find",
        "shortcuts.group.other",
        "reference-handbook",
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "reference_window_close",
        ("Escape",),
        "shortcuts.action.reference_window_close",
        "shortcuts.group.other",
        "reference-handbook",
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "reference_next_page",
        ("Right", "Down", "Space"),
        "shortcuts.action.reference_next_page",
        "shortcuts.group.other",
        "references-pdf",
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "reference_previous_page",
        ("Left", "Up"),
        "shortcuts.action.reference_previous_page",
        "shortcuts.group.other",
        "references-pdf",
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "reference_reload_web",
        ("F5",),
        "shortcuts.action.reference_reload_web",
        "shortcuts.group.other",
        "references-web",
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "constructor_save",
        ("Ctrl+S",),
        "shortcuts.action.constructor_save",
        "shortcuts.group.other",
        "reference-constructor",
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "constructor_close",
        ("Ctrl+Q",),
        "shortcuts.action.constructor_close",
        "shortcuts.group.other",
        "reference-constructor",
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "constructor_undo",
        ("Ctrl+Z",),
        "shortcuts.action.constructor_undo",
        "shortcuts.group.other",
        "reference-constructor",
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "constructor_find",
        ("Ctrl+F",),
        "shortcuts.action.constructor_find",
        "shortcuts.group.other",
        "reference-constructor",
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "constructor_preview",
        ("Ctrl+P",),
        "shortcuts.action.constructor_preview",
        "shortcuts.group.other",
        "reference-constructor",
        profiles=frozenset({"full"}),
    ),
    ShortcutSpec(
        "constructor_delete",
        ("Delete",),
        "shortcuts.action.constructor_delete",
        "shortcuts.group.other",
        "reference-constructor",
        profiles=frozenset({"full"}),
    ),
    *(
        ShortcutSpec(
            f"favorite_{index}",
            (str(index),),
            f"shortcuts.action.favorite_{index}",
            "shortcuts.group.viewer",
            "main-viewer",
        )
        for index in range(1, 10)
    ),
    ShortcutSpec(
        "multiview_ctrl_click",
        ("Ctrl+click",),
        "shortcuts.action.multiview_ctrl_click",
        "shortcuts.group.gestures",
        "thumbnail-gallery",
        kind="gesture",
        key_label_key="shortcuts.key.ctrl_click",
    ),
)

_SHORTCUT_BY_ID = {shortcut.id: shortcut for shortcut in SHORTCUTS}
_SHORTCUT_OVERRIDES: dict[str, tuple[str, ...]] = {}
# Qt children own their bindings; the registry must never keep a closed window
# alive. One QShortcut per action can carry all aliases via setKeys().
_INSTALLED_BINDINGS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

_GROUP_ORDER = (
    "shortcuts.group.main",
    "shortcuts.group.viewer",
    "shortcuts.group.viewer_only",
    "shortcuts.group.other",
    "shortcuts.group.gestures",
)
_DISPLAY_KEYS = {
    "Escape": "Esc",
    "Up": "↑",
    "Down": "↓",
    "Left": "←",
    "Right": "→",
    "BracketLeft": "[",
    "BracketRight": "]",
}
_HELP_START = "<!-- SHORTCUT_REGISTRY:START -->"
_HELP_END = "<!-- SHORTCUT_REGISTRY:END -->"
_HELP_SECTION_RE = re.compile(r"(?ms)^## 18\..*?(?=^## 19\.|\Z)")


def get_shortcut(shortcut_id: str) -> ShortcutSpec:
    """Return a registered shortcut by its stable ID."""
    try:
        spec = _SHORTCUT_BY_ID[shortcut_id]
        return replace(spec, sequences=_SHORTCUT_OVERRIDES[shortcut_id]) if shortcut_id in _SHORTCUT_OVERRIDES else spec
    except KeyError as exc:
        raise KeyError(f"Unknown SonoForge shortcut: {shortcut_id}") from exc


def shortcuts_for_profile(profile: str | None = None) -> tuple[ShortcutSpec, ...]:
    """Return bindings for *profile*; ``None`` returns the documentation superset."""
    return tuple(
        get_shortcut(spec.id) for spec in SHORTCUTS if profile is None or not spec.profiles or profile in spec.profiles
    )


def main_window_shortcuts(profile: str | None = None) -> tuple[ShortcutSpec, ...]:
    """Window-level QShortcut registrations, in declaration order."""
    return tuple(spec for spec in shortcuts_for_profile(profile) if spec.main_window_shortcut)


def shortcut_sequences(shortcut_id: str) -> tuple[str, ...]:
    """Portable Qt sequences associated with *shortcut_id*."""
    return get_shortcut(shortcut_id).sequences


def shortcut_label(shortcut_id: str, *, language: str | None = None) -> str:
    """Human-readable key label, including aliases such as Enter / Return."""
    spec = get_shortcut(shortcut_id)
    active_language = language or get_language()
    if spec.key_label_key and shortcut_id not in _SHORTCUT_OVERRIDES:
        return tr_for_language(spec.key_label_key, active_language)
    labels = []
    for sequence in spec.sequences:
        label = (
            tr_for_language("shortcuts.key.space", active_language)
            if sequence == "Space"
            else _DISPLAY_KEYS.get(sequence, sequence)
        )
        if sys.platform == "darwin":
            label = label.replace("Ctrl+", "⌘").replace("Meta+", "⌘").replace("Alt+", "⌥")
        labels.append(label)
    return " / ".join(labels)


def shortcut_note(shortcut_id: str, *, language: str | None = None) -> str:
    """Localized inline note suitable for a button, status line, or tooltip."""
    keys = shortcut_label(shortcut_id, language=language)
    return tr_for_language("shortcuts.note", language or get_language(), keys=keys) if keys else ""


def append_shortcut_hint(text: str, shortcut_id: str, *, language: str | None = None) -> str:
    """Append a localized shortcut note to existing explanatory text."""
    language = language or get_language()
    note = shortcut_note(shortcut_id, language=language)
    return tr_for_language("shortcuts.inline_hint", language, text=text, note=note) if note else text


def _conflict_context(context: str) -> str:
    return "main-window" if context in {"main-window", "main-viewer", "viewer"} else context


def shortcut_conflicts(
    profile: str | None = None,
    *,
    overrides: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[tuple[str, str, str, str], ...]:
    """Find duplicate keyboard bindings inside the same active-window context.

    Repeated sequences in one entry (for example F10/Escape to close Presenter)
    are aliases, not a conflict. Different windows are independent contexts.
    """
    occupied: dict[tuple[str, str], str] = {}
    conflicts: list[tuple[str, str, str, str]] = []
    for default in SHORTCUTS:
        if default.kind != "keyboard" or (profile is not None and default.profiles and profile not in default.profiles):
            continue
        spec = (
            get_shortcut(default.id)
            if overrides is None
            else replace(default, sequences=overrides.get(default.id, default.sequences))
        )
        # These handlers coexist in the main window: their former separate
        # context strings must not allow a global binding to shadow a viewer key.
        context = _conflict_context(spec.context)
        for sequence in spec.sequences:
            normalized = _normalize_sequence(sequence)
            key = (context, normalized)
            other = occupied.get(key)
            if other is not None and other != spec.id:
                conflicts.append((spec.context, normalized, other, spec.id))
            else:
                occupied[key] = spec.id
    return tuple(conflicts)


def decode_shortcut_overrides(encoded: str) -> dict[str, tuple[str, ...]]:
    """Read bounded, portable single-stroke overrides; unknown/invalid entries abstain."""
    from PySide6.QtGui import QKeySequence

    if not encoded or len(encoded) > 65536:
        return {}
    try:
        data = json.loads(encoded)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for shortcut_id, values in data.items():
        spec = _SHORTCUT_BY_ID.get(shortcut_id)
        if spec is None or spec.kind != "keyboard" or not isinstance(values, list) or len(values) > 3:
            continue
        if any(not isinstance(value, str) or not value or len(value) > 80 for value in values):
            continue
        keys = [QKeySequence(value, QKeySequence.SequenceFormat.PortableText) for value in values]
        portable = tuple(key.toString(QKeySequence.SequenceFormat.PortableText) for key in keys)
        if any(key.isEmpty() or key.count() != 1 for key in keys):
            continue
        if any(
            not value or _split_sequence(value) is None or value in {"Ctrl", "Alt", "Shift", "Meta"}
            for value in portable
        ):
            continue
        result[shortcut_id] = tuple(dict.fromkeys(portable))
    return result


def configure_shortcuts(encoded: str) -> None:
    """Apply saved bindings and update already-open Qt windows without duplicate handlers."""
    overrides = decode_shortcut_overrides(encoded)
    from echo_personal_tool.application.profile_settings import active_profile_name

    if shortcut_conflicts(active_profile_name(), overrides=overrides):
        overrides = {}  # A hand-edited/corrupt preference cannot disable normal routing.
    if overrides == _SHORTCUT_OVERRIDES:
        return
    _SHORTCUT_OVERRIDES.clear()
    _SHORTCUT_OVERRIDES.update(overrides)
    for binding, shortcut_id in list(_INSTALLED_BINDINGS.items()):
        try:
            keys = _qt_sequences(shortcut_id)
            if hasattr(binding, "setKeys"):
                binding.setKeys(keys)
            else:
                binding.setShortcuts(keys)
        except RuntimeError:
            _INSTALLED_BINDINGS.pop(binding, None)  # C++ object already deleted.


def _qt_sequences(shortcut_id: str):  # type: ignore[no-untyped-def]  # mypy does not check this file (outside tool.mypy.files)
    from PySide6.QtGui import QKeySequence

    return [
        QKeySequence(sequence.replace("Ctrl+", "Meta+") if sys.platform == "darwin" else sequence)
        for sequence in shortcut_sequences(shortcut_id)
    ]


def bind_action_shortcut(action, shortcut_id: str) -> None:  # type: ignore[no-untyped-def]  # mypy does not check this file (outside tool.mypy.files)
    """Bind a QAction too, including disabled/empty bindings and live changes."""
    action.setShortcuts(_qt_sequences(shortcut_id))
    _INSTALLED_BINDINGS[action] = shortcut_id


def _normalize_sequence(sequence: str) -> str:
    """Normalize aliases, literal plus keys and platform modifiers before collision checks."""
    parts = _split_sequence(sequence)
    if parts is None:
        return sequence.casefold()
    names, key_name = parts
    aliases = {"escape": "esc", "return": "enter", "control": "ctrl"}
    modifiers = {aliases.get(name.casefold(), name.casefold()) for name in names}
    if sys.platform == "darwin" and "ctrl" in modifiers:
        modifiers = (modifiers - {"ctrl"}) | {"meta"}
    modifier_order = ("ctrl", "shift", "alt", "meta", "num")
    key = aliases.get(key_name.casefold(), key_name.casefold())
    return "+".join((*[modifier for modifier in modifier_order if modifier in modifiers], key))


def event_matches_shortcut(
    event: object,
    shortcut_id: str,
    *,
    exact_modifiers: bool = True,
    forbidden_modifiers: tuple[str, ...] = (),
) -> bool:
    """Compare one ``QKeyEvent`` against the registry's portable sequences.

    This keeps event-handler keys in sync with the strings shown in Help while
    preserving Qt's existing context routing. ``exact_modifiers=False`` is for
    handlers whose historical behavior intentionally accepted extra modifiers.
    """
    from PySide6.QtCore import Qt

    spec = get_shortcut(shortcut_id)
    if spec.kind != "keyboard":
        return False
    if shortcut_id in _SHORTCUT_OVERRIDES:
        exact_modifiers = True
        forbidden_modifiers = ()

    modifier_values = {
        "Ctrl": Qt.KeyboardModifier.ControlModifier,
        "Control": Qt.KeyboardModifier.ControlModifier,
        "Shift": Qt.KeyboardModifier.ShiftModifier,
        "Alt": Qt.KeyboardModifier.AltModifier,
        "Meta": Qt.KeyboardModifier.MetaModifier,
        "Num": Qt.KeyboardModifier.KeypadModifier,
    }
    significant_modifiers = (
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.ShiftModifier
        | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.MetaModifier
    )
    if (
        shortcut_id not in _SHORTCUT_OVERRIDES
        and _SHORTCUT_OVERRIDES
        and (
            not exact_modifiers or event.modifiers() & Qt.KeyboardModifier.KeypadModifier  # type: ignore[attr-defined]  # mypy does not check this file (outside tool.mypy.files)
        )
    ):
        # Legacy handlers accept extra modifiers (Ctrl+Space, Shift+Plus,
        # regular digits on the numpad). A deliberately assigned, more
        # specific combination must win instead of being swallowed first.
        from echo_personal_tool.application.profile_settings import active_profile_name

        for candidate_id in _SHORTCUT_OVERRIDES:
            candidate = get_shortcut(candidate_id)
            if candidate.profiles and active_profile_name() not in candidate.profiles:
                continue
            if _conflict_context(candidate.context) == _conflict_context(spec.context) and event_matches_shortcut(
                event, candidate_id
            ):
                return False
    actual_modifiers = event.modifiers() & significant_modifiers  # type: ignore[attr-defined]  # mypy does not check this file (outside tool.mypy.files)
    forbidden = Qt.KeyboardModifier.NoModifier
    for name in forbidden_modifiers:
        forbidden |= modifier_values[name]
    if actual_modifiers & forbidden:
        return False

    for sequence in spec.sequences:
        parts = _split_sequence(sequence)
        if parts is None:
            continue
        modifier_names, key_name = parts
        if sys.platform == "darwin":
            modifier_names = tuple("Meta" if name == "Ctrl" else name for name in modifier_names)
        key = _qt_key(key_name, Qt)
        if key is None or event.key() != key:  # type: ignore[attr-defined]  # mypy does not check this file (outside tool.mypy.files)
            continue
        expected_modifiers = Qt.KeyboardModifier.NoModifier
        for name in modifier_names:
            modifier = modifier_values.get(name)
            if modifier is None:
                break
            expected_modifiers |= modifier
        else:
            actual = actual_modifiers
            if expected_modifiers & Qt.KeyboardModifier.KeypadModifier:
                actual |= event.modifiers() & Qt.KeyboardModifier.KeypadModifier  # type: ignore[attr-defined]  # mypy does not check this file (outside tool.mypy.files)
            if exact_modifiers and actual == expected_modifiers:
                return True
            if not exact_modifiers and actual & expected_modifiers == expected_modifiers:
                return True
    return False


def _split_sequence(sequence: str) -> tuple[tuple[str, ...], str] | None:
    """Split simple Qt sequences while allowing literal plus/equal keys."""
    if ", " in sequence:
        return None
    modifiers: list[str] = []
    remaining = sequence
    while "+" in remaining and remaining != "+":
        modifier, rest = remaining.split("+", 1)
        canonical = {
            "ctrl": "Ctrl",
            "control": "Ctrl",
            "alt": "Alt",
            "shift": "Shift",
            "meta": "Meta",
            "num": "Num",
        }.get(modifier.casefold())
        if canonical is None:
            break
        modifiers.append(canonical)
        remaining = rest
    if not remaining:
        return None
    return tuple(modifiers), remaining


def _first_key(sequence: Any) -> Any:
    """First key of a QKeySequence.

    Typed as Any so the module type-checks both with PySide6 stubs (the
    sequence-protocol ``__getitem__`` is missing from the ``.pyi``) and
    without PySide6 installed (CI lint environment).
    """
    return sequence[0]


def _qt_key(key_name: str, Qt: Any) -> Any:
    special = {
        "Esc": Qt.Key.Key_Escape,
        "Escape": Qt.Key.Key_Escape,
        "Return": Qt.Key.Key_Return,
        "Enter": Qt.Key.Key_Enter,
        "Space": Qt.Key.Key_Space,
        "Tab": Qt.Key.Key_Tab,
        "Backspace": Qt.Key.Key_Backspace,
        "Delete": Qt.Key.Key_Delete,
        "Up": Qt.Key.Key_Up,
        "Down": Qt.Key.Key_Down,
        "Left": Qt.Key.Key_Left,
        "Right": Qt.Key.Key_Right,
        "[": Qt.Key.Key_BracketLeft,
        "]": Qt.Key.Key_BracketRight,
        "+": Qt.Key.Key_Plus,
        "=": Qt.Key.Key_Equal,
        "-": Qt.Key.Key_Minus,
        "`": Qt.Key.Key_QuoteLeft,
        "/": Qt.Key.Key_Slash,
    }
    if key_name in special:
        return special[key_name]
    enum_name = f"Key_{key_name.upper()}" if len(key_name) == 1 else f"Key_{key_name}"
    key = getattr(Qt.Key, enum_name, None)
    if key is not None:
        return key
    from PySide6.QtGui import QKeySequence

    sequence = QKeySequence(key_name, QKeySequence.SequenceFormat.PortableText)
    if not sequence.isEmpty() and sequence.count() == 1 and _first_key(sequence).key() != Qt.Key.Key_unknown:
        return _first_key(sequence).key()
    return None


def favorite_shortcut_index(event: object) -> int | None:
    """Resolve a favorite slot through the user bindings, not hard-coded digits."""
    return next((index for index in range(9) if event_matches_shortcut(event, f"favorite_{index + 1}")), None)


def install_qshortcuts(
    widget: object,
    shortcut_id: str,
    handler: Any,
    *,
    context: Any | None = None,
) -> tuple[object, ...]:
    """Create QShortcut children for a registered action and return them."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QShortcut

    spec = get_shortcut(shortcut_id)
    if spec.kind != "keyboard":
        raise ValueError(f"{shortcut_id} is a gesture, not a keyboard shortcut")
    # cast: widget is duck-typed `object`; QShortcut only needs a QObject at
    # runtime, and the cast keeps the call clean both with and without the
    # PySide6 stubs (CI lints without PySide6 installed).
    shortcut = cast(Any, QShortcut)(widget)
    shortcut.setKeys(_qt_sequences(shortcut_id))
    shortcut.setContext(Qt.ShortcutContext.WindowShortcut if context is None else context)
    shortcut.setProperty("sonoShortcutId", shortcut_id)
    shortcut.activated.connect(handler)
    _INSTALLED_BINDINGS[shortcut] = shortcut_id
    return (shortcut,)


def render_shortcut_help_markdown(language: str, *, profile: str | None = None) -> str:
    """Render the registered bindings as the keyboard section of the Help guide."""
    language = language if language in {"en", "ru"} else "en"
    entries = shortcuts_for_profile(profile)
    lines = [
        f"## {tr_for_language('shortcuts.help.heading', language)}",
        "",
        tr_for_language("shortcuts.help.intro", language),
        "",
    ]
    for group_key in _GROUP_ORDER:
        grouped = [spec for spec in entries if spec.group_key == group_key]
        if not grouped:
            continue
        lines.extend(
            (
                f"### {tr_for_language(group_key, language)}",
                "",
                tr_for_language(f"{group_key}.intro", language),
                "",
                f"| {tr_for_language('shortcuts.help.key_column', language)} | "
                f"{tr_for_language('shortcuts.help.action_column', language)} |",
                "|---|---|",
            )
        )
        for spec in grouped:
            label = shortcut_label(spec.id, language=language).replace("|", "\\|")
            description = tr_for_language(spec.description_key, language).replace("|", "\\|")
            lines.append(f"| {_markdown_code(label)} | {description} |")
        lines.append("")
    lines.append(tr_for_language("shortcuts.help.no_inference", language))
    return "\n".join(lines).rstrip() + "\n"


def replace_shortcut_help_section(
    markdown: str,
    language: str,
    *,
    profile: str | None = None,
    add_markers: bool = False,
) -> str:
    """Replace the marked section (or legacy section 18) in a HELP document."""
    content = render_shortcut_help_markdown(language, profile=profile)
    if add_markers:
        content = f"{_HELP_START}\n{content}{_HELP_END}\n\n"
    start = markdown.find(_HELP_START)
    end = markdown.find(_HELP_END)
    if start >= 0 and end >= start:
        end += len(_HELP_END)
        if add_markers:
            while markdown.startswith("\n", end):
                end += 1
        return markdown[:start] + content + markdown[end:]
    match = _HELP_SECTION_RE.search(markdown)
    if match is None:
        return markdown
    return markdown[: match.start()] + content + markdown[match.end() :]


def _markdown_code(text: str) -> str:
    """Escape inline code, including the gallery's literal backtick key."""
    if "`" not in text:
        return f"`{text}`"
    return f"`` {text} ``"


# Static consistency guard used by tests and docs generation.
assert len(_SHORTCUT_BY_ID) == len(SHORTCUTS), "shortcut IDs must be unique"
