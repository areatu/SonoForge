"""Canonical registry for SonoForge keyboard shortcuts and key hints.

The registry is intentionally dependency-light: shortcut metadata can be used
by the application, domain presentation, native Qt widgets, tooltips, and the
user guide without importing Qt at module import time.  Keep only bindings
that have a real handler in the current application; a key mentioned in an
older document is not evidence that it is active.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
        "delete_selection",
        ("Delete", "Backspace"),
        "shortcuts.action.delete_selection",
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
        return _SHORTCUT_BY_ID[shortcut_id]
    except KeyError as exc:
        raise KeyError(f"Unknown SonoForge shortcut: {shortcut_id}") from exc


def shortcuts_for_profile(profile: str | None = None) -> tuple[ShortcutSpec, ...]:
    """Return bindings for *profile*; ``None`` returns the documentation superset."""
    if profile is None:
        return SHORTCUTS
    return tuple(spec for spec in SHORTCUTS if not spec.profiles or profile in spec.profiles)


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
    if spec.key_label_key:
        return tr_for_language(spec.key_label_key, active_language)
    labels = (
        tr_for_language("shortcuts.key.space", active_language)
        if sequence == "Space"
        else _DISPLAY_KEYS.get(sequence, sequence)
        for sequence in spec.sequences
    )
    return " / ".join(labels)


def shortcut_note(shortcut_id: str, *, language: str | None = None) -> str:
    """Localized inline note suitable for a button, status line, or tooltip."""
    return tr_for_language(
        "shortcuts.note",
        language or get_language(),
        keys=shortcut_label(shortcut_id, language=language),
    )


def append_shortcut_hint(text: str, shortcut_id: str, *, language: str | None = None) -> str:
    """Append a localized shortcut note to existing explanatory text."""
    language = language or get_language()
    return tr_for_language(
        "shortcuts.inline_hint",
        language,
        text=text,
        note=shortcut_note(shortcut_id, language=language),
    )


def shortcut_conflicts(profile: str | None = None) -> tuple[tuple[str, str, str, str], ...]:
    """Find duplicate keyboard bindings inside the same active-window context.

    Repeated sequences in one entry (for example F10/Escape to close Presenter)
    are aliases, not a conflict. Different windows are independent contexts.
    """
    occupied: dict[tuple[str, str], str] = {}
    conflicts: list[tuple[str, str, str, str]] = []
    for spec in shortcuts_for_profile(profile):
        if spec.kind != "keyboard":
            continue
        for sequence in spec.sequences:
            normalized = _normalize_sequence(sequence)
            key = (spec.context, normalized)
            other = occupied.get(key)
            if other is not None and other != spec.id:
                conflicts.append((spec.context, normalized, other, spec.id))
            else:
                occupied[key] = spec.id
    return tuple(conflicts)


def _normalize_sequence(sequence: str) -> str:
    """Normalize key aliases and modifier order before collision checks."""
    if sequence in {"+", "=", "-", "[", "]", "`"}:
        return sequence.casefold()
    pieces = sequence.split("+")
    if not pieces or any(not piece for piece in pieces):
        return sequence.casefold()
    aliases = {"escape": "esc", "return": "enter", "control": "ctrl"}
    modifiers = {aliases.get(piece.casefold(), piece.casefold()) for piece in pieces[:-1]}
    modifier_order = ("ctrl", "shift", "alt", "meta")
    normalized_modifiers = [modifier for modifier in modifier_order if modifier in modifiers]
    normalized_modifiers.extend(sorted(modifiers - set(normalized_modifiers)))
    key = aliases.get(pieces[-1].casefold(), pieces[-1].casefold())
    return "+".join((*normalized_modifiers, key))


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

    modifier_values = {
        "Ctrl": Qt.KeyboardModifier.ControlModifier,
        "Control": Qt.KeyboardModifier.ControlModifier,
        "Shift": Qt.KeyboardModifier.ShiftModifier,
        "Alt": Qt.KeyboardModifier.AltModifier,
        "Meta": Qt.KeyboardModifier.MetaModifier,
    }
    significant_modifiers = (
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.ShiftModifier
        | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.MetaModifier
    )
    actual_modifiers = event.modifiers() & significant_modifiers  # type: ignore[attr-defined]
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
        key = _qt_key(key_name, Qt)
        if key is None or event.key() != key:  # type: ignore[attr-defined]
            continue
        expected_modifiers = Qt.KeyboardModifier.NoModifier
        for name in modifier_names:
            modifier = modifier_values.get(name)
            if modifier is None:
                break
            expected_modifiers |= modifier
        else:
            if exact_modifiers and actual_modifiers == expected_modifiers:
                return True
            if not exact_modifiers and actual_modifiers & expected_modifiers == expected_modifiers:
                return True
    return False


def _split_sequence(sequence: str) -> tuple[tuple[str, ...], str] | None:
    """Split simple Qt sequences while allowing literal plus/equal keys."""
    if sequence in {"+", "=", "-", "[", "]", "`"}:
        return (), sequence
    parts = sequence.split("+")
    if not parts or any(not part for part in parts):
        return None
    return tuple(parts[:-1]), parts[-1]


def _qt_key(key_name: str, Qt):  # noqa: ANN001 - Qt is imported lazily
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
    }
    if key_name in special:
        return special[key_name]
    enum_name = f"Key_{key_name.upper()}" if len(key_name) == 1 else f"Key_{key_name}"
    return getattr(Qt.Key, enum_name, None)


def install_qshortcuts(
    widget: object,
    shortcut_id: str,
    handler,
    *,
    context=None,
) -> tuple[object, ...]:
    """Create QShortcut children for a registered action and return them."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence, QShortcut

    spec = get_shortcut(shortcut_id)
    if spec.kind != "keyboard":
        raise ValueError(f"{shortcut_id} is a gesture, not a keyboard shortcut")
    shortcuts = []
    for sequence in spec.sequences:
        shortcut = QShortcut(QKeySequence(sequence), widget)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut if context is None else context)
        shortcut.activated.connect(handler)
        shortcuts.append(shortcut)
    return tuple(shortcuts)


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
