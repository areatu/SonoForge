"""Bilingual, profile-aware commands available to the TP-6 palette.

The module stays Qt-free: catalogue matching and Enter resolution are pure
functions, and the Qt palette only renders :func:`match_commands` results.
"""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.application.localization import get_language, tr_for_language
from echo_personal_tool.keyboard_shortcuts import shortcut_label

#: Languages a query is matched against, so RU and EN labels both work (TP-6 keeps this).
_MATCH_LANGUAGES = ("ru", "en")


@dataclass(frozen=True, slots=True)
class Command:
    """One entry of the command field: a label, a key hint and an action id.

    ``label_text`` is for entries whose caption is not a key of the locales —
    the parameters of the handbook («Справочник: КДР ЛЖ»), whose names live in
    the handbook itself and are already in the language of the interface.
    """

    id: str
    label_key: str
    action: str
    shortcut_id: str = ""
    profiles: frozenset[str] = frozenset()
    label_text: str = ""


#: Declarations in display order; every ``action`` has a handler in ``MainWindow``.
COMMANDS: tuple[Command, ...] = (
    Command("open_folder", "system_bar.open_folder", "open_folder", "open_folder"),
    Command("load_server", "system_bar.load_from_server", "load_server", "load_server"),
    Command("new_tab", "title_bar.new_tab", "new_tab", "new_tab"),
    Command("settings", "app_menu.settings", "settings"),
    Command("layout", "app_menu.layout", "layout"),
    Command("calculators", "tool_panel.calculators", "open_calculators"),
    Command("references", "app_menu.references", "references"),
    Command("help", "app_menu.help", "help"),
    Command("guide", "app_menu.guide", "guide"),
    Command("about", "app_menu.about", "about"),
    Command("caliper", "system_bar.caliper", "caliper", "caliper"),
    Command("spline_area", "menu.spline_area", "tool_spline_area"),
    Command("spline_volume", "menu.spline_volume", "tool_spline_volume"),
    Command("manual_contour", "toolbtn.manual_contour", "tool_manual_contour", "manual_contour"),
    Command("model_contour", "toolbtn.model_contour", "tool_model_contour", "model_contour"),
    Command("vti_trace", "toolbtn.vti_trace", "tool_vti_trace", "vti_trace"),
    Command("doppler_interval", "toolbtn.doppler_interval", "tool_doppler_interval", "doppler_interval"),
    Command("auto_segment", "toolbtn.auto_segment", "tool_auto_segment", "auto_segment"),
    Command("heart_rate", "system_bar.heart_rate", "heart_rate"),
    Command("calibration_bmode", "system_bar.calibration_bmode", "calibration_bmode", "calibration_toggle"),
    Command("calibration_doppler", "system_bar.calibration_doppler", "calibration_doppler"),
    Command("reset", "system_bar.reset", "reset"),
    Command("multiview", "layout.multiview_mode", "multiview"),
    Command("focus", "focus.badge", "focus", "toggle_focus_mode"),
    Command(
        "presenter",
        "presenter.button",
        "presenter",
        "presenter_toggle",
        profiles=frozenset({"presenter"}),
    ),
    Command("quit", "app_menu.quit", "quit"),
)


def commands_for_profile(profile: str) -> tuple[Command, ...]:
    """The commands of a build: profile-limited entries are filtered out."""
    return tuple(command for command in COMMANDS if not command.profiles or profile in command.profiles)


def command_label(command: Command, *, language: str | None = None, with_shortcut: bool = True) -> str:
    """Localized label of a command, optionally with its key hint («Открыть папку… · Ctrl+O»)."""
    active_language = language or get_language()
    label = command.label_text or tr_for_language(command.label_key, active_language)
    if not with_shortcut or not command.shortcut_id:
        return label
    return f"{label} · {shortcut_label(command.shortcut_id, language=active_language)}"


def _search_text(command: Command) -> tuple[str, ...]:
    """Everything a query is matched against: the id and the label in both languages."""
    return (
        command.id,
        command.label_text.casefold(),
        *(tr_for_language(command.label_key, language).casefold() for language in _MATCH_LANGUAGES),
    )


def match_commands(query: str, *, profile: str, language: str | None = None) -> tuple[Command, ...]:
    """Commands whose id or label (RU/EN) contains ``query``.

    An empty query returns the whole catalogue in display order; prefix matches
    come first so the palette opens on the most likely command.
    """
    active_language = language or get_language()
    needle = query.strip().casefold()
    commands = commands_for_profile(profile)
    if not needle:
        return commands
    matched = [command for command in commands if any(needle in text for text in _search_text(command))]
    prefix = [
        command
        for command in matched
        if tr_for_language(command.label_key, active_language).casefold().startswith(needle)
        or command.id.startswith(needle)
    ]
    return tuple(prefix + [command for command in matched if command not in prefix])


#: Action prefix of a handbook parameter («Справочник: КДР» opens S1 on its row).
REFERENCE_PARAM_PREFIX = "reference_param:"

#: Action prefix of a protocol («Протоколы» group starts the runner).
PROTOCOL_ACTION_PREFIX = "protocol:"


def protocol_commands(query: str, *, language: str | None = None) -> tuple[Command, ...]:
    """The six protocols matching ``query``, for the «Протоколы» group of Ctrl+K.

    An entry starts the protocol runner through ``protocol:<id>`` — the same
    action the panel's protocol card dispatches.  Matching sees the id and the
    RU and EN names, so a query works in either language of the interface.
    """
    from echo_personal_tool.domain.protocol_definitions import PROTOCOLS

    active = language or get_language()
    needle = query.strip().casefold()
    commands: list[Command] = []
    for spec in PROTOCOLS:
        haystack = (spec.id.casefold(), spec.label("ru").casefold(), spec.label("en").casefold())
        if needle and not any(needle in text for text in haystack):
            continue
        commands.append(
            Command(
                id=f"protocol.{spec.id}",
                label_key="",
                action=f"{PROTOCOL_ACTION_PREFIX}{spec.id}",
                label_text=spec.label(active),
            )
        )
    return tuple(commands)


def reference_commands(query: str, *, language: str | None = None, limit: int = 6) -> tuple[Command, ...]:
    """Handbook parameters matching ``query``, for the «Справочник» group of Ctrl+K.

    Declared here rather than in the palette so the entry keeps the contract of
    the catalogue: an id, a caption and an action the window can dispatch.  An
    empty handbook (a broken YAML) yields no entries — the palette still opens.
    """
    from echo_personal_tool.domain.services.reference_topics import parameter_matches

    prefix = tr_for_language("ref_window.command_prefix", language or get_language())
    return tuple(
        Command(
            id=f"reference.{param.id}",
            label_key="",
            action=f"{REFERENCE_PARAM_PREFIX}{param.id}",
            label_text=f"{prefix}: {param.name}",
        )
        for param in parameter_matches(query, language=language, limit=limit)
    )


def resolve_command(query: str, *, profile: str, language: str | None = None) -> Command | None:
    """The command ``Enter`` runs: the first match of :func:`match_commands`."""
    matches = match_commands(query, profile=profile, language=language)
    if not matches:
        return None
    if not query.strip():
        return None  # an empty field is a prompt, not a command
    return matches[0]


__all__ = [
    "COMMANDS",
    "PROTOCOL_ACTION_PREFIX",
    "REFERENCE_PARAM_PREFIX",
    "Command",
    "command_label",
    "commands_for_profile",
    "match_commands",
    "protocol_commands",
    "reference_commands",
    "resolve_command",
]
