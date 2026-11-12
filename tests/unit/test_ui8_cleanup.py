"""UI-8 cleanup preserves token colours and legacy settings migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echo_personal_tool.presentation.theme.palettes import ACCENT_PALETTES, THEME_IDS, get_palette_tokens
from echo_personal_tool.presentation.theme.tokens import tokens_to_legacy


@pytest.mark.parametrize("theme", THEME_IDS)
@pytest.mark.parametrize("accent", ["theme", *ACCENT_PALETTES])
def test_migrated_legacy_colours_equal_tokens(theme: str, accent: str) -> None:
    tokens = get_palette_tokens(theme, accent_palette=accent)
    legacy = tokens_to_legacy(tokens)
    for old, new in {
        "border": "line.1",
        "text": "text.1",
        "text_dim": "text.2",
        "accent_bright": "accent.text",
        "accent_tab": "accent.tab",
        "slider_track": "slider.track",
        "slider_fill": "slider.fill",
    }.items():
        assert legacy[old] == tokens[new]


def test_obsolete_activity_bar_locale_keys_are_removed() -> None:
    root = Path(__file__).resolve().parents[2] / "src/echo_personal_tool/infrastructure/locales"
    for language in ("en", "ru"):
        locale = json.loads((root / f"{language}.json").read_text(encoding="utf-8"))
        assert not any(key.startswith("activity.") or key.startswith("layout.activity_bar") for key in locale)


def test_legacy_activity_bar_setting_still_migrates() -> None:
    from echo_personal_tool.presentation.layout.presets import migrate_v1

    assert migrate_v1({"activity_bar": True}).tool_buttons == "rail"
