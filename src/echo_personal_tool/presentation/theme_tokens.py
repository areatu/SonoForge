"""Compatibility facade of the design tokens (UI-0, PR-1).

The tokens themselves moved into the package
:mod:`echo_personal_tool.presentation.theme` — the layout the redesign spec
asks for (§9): ``tokens.py`` (the roles), ``palettes.py`` (the raw colours),
``qss.py`` (the stylesheet) and ``system_theme.py`` (the colour scheme of the
operating system).

This module keeps the names the flat token module offered, so importers do
not break; it is a facade like :mod:`echo_personal_tool.presentation.dark_theme`
and goes away with the legacy palette in UI-8. The values are the same: the
legacy 28-key palette is still derived from the tokens, and the stylesheet is
still the one of the previous release.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from echo_personal_tool.presentation.theme.contrast import (
    CHECKS,
    ENFORCED_CONTRAST_THEMES,
    TEXT_MINIMUM,
    UI_MINIMUM,
    contrast_failures,
    contrast_ratio,
    hex_to_rgb,
    relative_luminance,
)
from echo_personal_tool.presentation.theme.palettes import (
    PALETTES,
    THEME_DARK,
    THEME_IDS,
    get_legacy_palette,
    get_palette_tokens,
    is_dark_theme,
    validate_palette,
)
from echo_personal_tool.presentation.theme.tokens import (
    LEGACY_KEY_TO_TOKEN,
    REQUIRED_TOKEN_NAMES,
    TOKEN_NAMES,
)

#: Themes with a dark background.
DARK_THEMES: frozenset[str] = frozenset({"dark", "vscode_dark", "graphite"})

#: The token mapping of every theme (read-only).
THEME_TOKENS: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {theme_id: MappingProxyType(dict(tokens)) for theme_id, tokens in PALETTES.items()}
)

#: The 28 legacy palette keys and the token each of them reads.
LEGACY_KEY_TOKENS: Mapping[str, str] = MappingProxyType(dict(LEGACY_KEY_TO_TOKEN))

#: The pairs the contrast check looks at: (foreground, backgrounds, minimum).
CONTRAST_REQUIREMENTS: tuple[tuple[str, tuple[str, ...], float], ...] = tuple(
    (check.foreground, (check.background,), check.minimum) for check in CHECKS
)


def normalize_theme_id(theme: str) -> str:
    """Map a stored theme id to a concrete palette id (unknown → navy).

    ``"system"`` is resolved by the caller (it needs the OS); here it falls
    back to navy like any unknown id.
    """
    return theme if theme in THEME_IDS else THEME_DARK


def tokens_for(theme: str) -> Mapping[str, str]:
    """Read-only token mapping of a concrete theme (unknown → navy)."""
    return THEME_TOKENS[normalize_theme_id(theme)]


def token(theme: str, name: str) -> str:
    """One token value; raises ``KeyError`` for an unknown token name."""
    if name not in TOKEN_NAMES:
        raise KeyError(name)
    return tokens_for(theme)[name]


def legacy_palette(theme: str) -> dict[str, str]:
    """The 28 legacy palette keys of a theme, computed from the tokens."""
    return get_legacy_palette(normalize_theme_id(theme))


def validate_tokens() -> list[str]:
    """Return the problems of the token tables (empty when they are sound)."""
    problems: list[str] = []
    for theme_id in THEME_IDS:
        problems.extend(f"{theme_id}: {problem}" for problem in validate_palette(theme_id))
    return problems


__all__ = [
    "CONTRAST_REQUIREMENTS",
    "DARK_THEMES",
    "ENFORCED_CONTRAST_THEMES",
    "LEGACY_KEY_TOKENS",
    "REQUIRED_TOKEN_NAMES",
    "TEXT_MINIMUM",
    "THEME_IDS",
    "THEME_TOKENS",
    "TOKEN_NAMES",
    "UI_MINIMUM",
    "contrast_failures",
    "contrast_ratio",
    "get_legacy_palette",
    "get_palette_tokens",
    "hex_to_rgb",
    "is_dark_theme",
    "legacy_palette",
    "normalize_theme_id",
    "relative_luminance",
    "token",
    "tokens_for",
    "validate_tokens",
]
