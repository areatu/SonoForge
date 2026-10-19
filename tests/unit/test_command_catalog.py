"""The command catalogue behind the caption field (UI-1 PR-2, spec §4.1).

Pure logic: no Qt, no window. The tests pin what the field promises before the
palette of TP-6 replaces its rendering — a bilingual match (RU and EN labels),
a deterministic order, a profile-aware list, and an explicit resolution rule for
``Enter``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from echo_personal_tool.keyboard_shortcuts import get_shortcut
from echo_personal_tool.presentation.command_catalog import (
    COMMANDS,
    command_label,
    commands_for_profile,
    match_commands,
    resolve_command,
)

_LOCALES = Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool" / "infrastructure" / "locales"


def _locale(language: str) -> dict[str, str]:
    return json.loads((_LOCALES / f"{language}.json").read_text(encoding="utf-8"))


def test_catalogue_ids_actions_and_locales_are_consistent() -> None:
    assert len({command.id for command in COMMANDS}) == len(COMMANDS)
    assert len({command.action for command in COMMANDS}) == len(COMMANDS)
    for language in ("ru", "en"):
        translations = _locale(language)
        for command in COMMANDS:
            assert command.label_key in translations, f"{language}: {command.label_key}"
            if command.shortcut_id:
                # A key hint of the field must be a registered binding, not prose.
                assert get_shortcut(command.shortcut_id).sequences


def test_empty_query_offers_the_whole_catalogue_in_display_order() -> None:
    assert match_commands("", profile="full") == commands_for_profile("full")
    assert match_commands("   ", profile="full") == commands_for_profile("full")


def test_query_matches_the_label_in_both_languages() -> None:
    russian = match_commands("настрой", profile="full", language="ru")
    english = match_commands("settings", profile="full", language="ru")

    assert [command.id for command in russian] == ["settings"]
    assert [command.id for command in english] == ["settings"]
    # «Справ…» reaches both «Справочник» and «Справка» — the field is a filter,
    # not an exact command line (the palette of TP-6 keeps that freedom).
    assert {"references", "help"} <= {c.id for c in match_commands("справ", profile="full")}
    assert "guide" in {c.id for c in match_commands("руковод", profile="full")}
    assert match_commands("СПРАВКА", profile="full")[0].id in {"help", "references"}
    assert [c.id for c in match_commands("help", profile="full")] == ["help"]


def test_query_matches_the_identifier_as_a_fallback() -> None:
    matches = [command.id for command in match_commands("calibration_dop", profile="full")]
    assert matches == ["calibration_doppler"]


def test_prefix_matches_come_first() -> None:
    """«Настроить» must land on the command whose label starts with it (TP-6 keeps the rule)."""
    matches = match_commands("откр", profile="full", language="ru")
    assert matches
    assert matches[0].id == "open_folder"


def test_profile_filters_the_presenter_entry() -> None:
    full = {command.id for command in commands_for_profile("full")}
    presenter = {command.id for command in commands_for_profile("presenter")}

    assert "presenter" not in full
    assert "presenter" in presenter
    assert full | {"presenter"} == presenter
    assert "presenter" not in {command.id for command in match_commands("", profile="full")}


def test_enter_resolves_the_first_match_only_for_a_real_query() -> None:
    assert resolve_command("", profile="full") is None
    assert resolve_command("   ", profile="full") is None
    assert resolve_command("эрзац-команда", profile="full") is None
    assert resolve_command("caliper", profile="full").id == "caliper"
    assert resolve_command("открыть папку", profile="full", language="ru").action == "open_folder"


def test_command_label_carries_the_key_hint() -> None:
    command = next(item for item in COMMANDS if item.id == "open_folder")

    assert command_label(command, language="ru", with_shortcut=False) == "Открыть папку…"
    key = "⌘O" if sys.platform == "darwin" else "Ctrl+O"
    assert command_label(command, language="ru") == f"Открыть папку… · {key}"
    without_hint = next(item for item in COMMANDS if item.id == "settings")
    assert command_label(without_hint, language="ru") == "Настройки…"
