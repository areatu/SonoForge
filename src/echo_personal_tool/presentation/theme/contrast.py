"""Contrast rules for the design tokens (UI-0, PR-1).

The token system states a colour *role*; this module states how much contrast
the roles must have against each other (spec §5.2, G-4) and computes the
WCAG 2.1 ratio of two colours.

* the graphite theme is checked strictly — a failing pair fails the build,
* the former themes (navy, light, VS Code) are only reported: their colours
  were not agreed with anyone and must not change silently (the script turns
  them into errors with ``--strict``).

The module lives in the token package and imports no Qt, so the CI script
uses it without a GUI stack.
"""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.presentation.theme.palettes import PALETTES, THEME_GRAPHITE

#: Text needs 4.5:1 (WCAG 2.1 AA), a non-text element 3:1 (1.4.11).
TEXT_MINIMUM = 4.5
UI_MINIMUM = 3.0

#: The surfaces a text token has to be readable on.
SURFACES: tuple[str, ...] = ("surface.0", "surface.1", "surface.2", "surface.3")

#: Themes whose contrast blocks the build.
ENFORCED_CONTRAST_THEMES: frozenset[str] = frozenset({THEME_GRAPHITE})


@dataclass(frozen=True)
class ContrastCheck:
    """One pair of tokens with the contrast it has to reach."""

    foreground: str
    background: str
    minimum: float

    @property
    def kind(self) -> str:
        return "text" if self.minimum >= TEXT_MINIMUM else "ui"


def _checks() -> tuple[ContrastCheck, ...]:
    """Build the list of checked token pairs."""
    checks: list[ContrastCheck] = []
    for text_token in ("text.1", "text.2", "text.3", "accent.text"):
        for surface in SURFACES:
            checks.append(ContrastCheck(text_token, surface, TEXT_MINIMUM))
    checks.append(ContrastCheck("accent.on", "accent", TEXT_MINIMUM))
    for surface in SURFACES:
        checks.append(ContrastCheck("accent", surface, UI_MINIMUM))
    checks.append(ContrastCheck("focus.ring", "surface.0", UI_MINIMUM))
    for state in ("state.ok", "state.warn", "state.err"):
        checks.append(ContrastCheck(state, "surface.1", TEXT_MINIMUM))
    checks.append(ContrastCheck("state.danger.text", "state.danger.bg", TEXT_MINIMUM))
    return tuple(checks)


#: Every pair the check looks at.
CHECKS: tuple[ContrastCheck, ...] = _checks()


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Return the red, green and blue channels of a hex colour."""
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) not in (6, 8):
        raise ValueError(f"not a hex colour: {value!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def relative_luminance(color: str) -> float:
    """Return the relative luminance of a hex colour (WCAG 2.1)."""
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) not in (6, 8):
        raise ValueError(f"not a hex colour: {color!r}")
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the contrast ratio of two hex colours (1.0 … 21.0)."""
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def check_theme(theme_id: str) -> list[dict]:
    """Check one theme; returns one record per checked pair."""
    tokens = PALETTES[theme_id]
    records: list[dict] = []
    for check in CHECKS:
        foreground = tokens[check.foreground]
        background = tokens[check.background]
        ratio = contrast_ratio(foreground, background)
        records.append(
            {
                "theme": theme_id,
                "foreground": check.foreground,
                "background": check.background,
                "foreground_color": foreground,
                "background_color": background,
                "ratio": round(ratio, 2),
                "minimum": check.minimum,
                "kind": check.kind,
                "passed": ratio >= check.minimum,
            }
        )
    return records


def contrast_failures(theme_id: str) -> list[tuple[str, str, float, float]]:
    """Return the pairs of a theme that do not reach their minimum."""
    return [
        (record["foreground"], record["background"], record["ratio"], record["minimum"])
        for record in check_theme(theme_id)
        if not record["passed"]
    ]
