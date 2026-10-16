"""Semantic design tokens for the presentation layer (UI-0, PR-1).

Three layers of appearance (UI redesign spec, §5.1):

1. **Palette** — raw theme colours; they live in :mod:`.palettes` only.
2. **Semantic tokens** — the *role* of a colour; this module.
3. **Consumers** — QSS, item delegates and ``QPainter`` code read tokens only.

Raw hex literals are allowed in the palette module alone. The ratchet
(``scripts/check_ui_colors.py``) keeps that rule honest: the number of
literals outside the palette may only fall, never grow.

The token vocabulary is declared here once. Values per theme are supplied by
:mod:`.palettes`; the ``overlay`` group is filled in by UI-0 PR-7 (viewer and
doppler overlay move to ``overlay.*`` without changing a single colour), so it
is listed here as a declared-but-not-yet-valued group.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# ── Token groups ───────────────────────────────────────────────────
GROUP_SURFACE = "surface"
GROUP_LINE = "line"
GROUP_TEXT = "text"
GROUP_ACCENT = "accent"
GROUP_STATE = "state"
GROUP_FOCUS = "focus"
GROUP_PROGRESS = "progress"
GROUP_SLIDER = "slider"
GROUP_PAPER = "paper"
GROUP_OVERLAY = "overlay"

#: Groups whose values are declared but not filled in yet. Every other token
#: must have a value in every palette (enforced by the unit tests).
PENDING_GROUPS: tuple[str, ...] = (GROUP_OVERLAY,)


@dataclass(frozen=True)
class TokenSpec:
    """One semantic token: its name, group and role."""

    name: str
    group: str
    description: str


#: The token vocabulary. Order is the reading order of the spec table (§5.2).
TOKENS: tuple[TokenSpec, ...] = (
    # Surfaces — from the window background to the most raised element.
    TokenSpec("surface.0", GROUP_SURFACE, "Window background, area around the image"),
    TokenSpec("surface.1", GROUP_SURFACE, "Panels, bars, header"),
    TokenSpec("surface.2", GROUP_SURFACE, "Input fields, cards"),
    TokenSpec("surface.3", GROUP_SURFACE, "Buttons, selected segment"),
    TokenSpec("surface.hover", GROUP_SURFACE, "Button hover state"),
    TokenSpec("surface.pressed", GROUP_SURFACE, "Button pressed state"),
    TokenSpec("surface.hover.alt", GROUP_SURFACE, "Legacy hover colour of the 28-key palette contract"),
    # Lines.
    TokenSpec("line.1", GROUP_LINE, "Separators between areas"),
    TokenSpec("line.2", GROUP_LINE, "Borders of controls"),
    # Text.
    TokenSpec("text.1", GROUP_TEXT, "Primary text"),
    TokenSpec("text.2", GROUP_TEXT, "Secondary text"),
    TokenSpec("text.3", GROUP_TEXT, "Hints, units, placeholders"),
    TokenSpec("text.disabled", GROUP_TEXT, "Disabled elements (WCAG sets no minimum)"),
    # Accent.
    TokenSpec("accent", GROUP_ACCENT, "Active tool, primary action"),
    TokenSpec("accent.text", GROUP_ACCENT, "Accent text on a dark surface"),
    TokenSpec("accent.on", GROUP_ACCENT, "Text on an accent fill"),
    TokenSpec("accent.tab", GROUP_ACCENT, "Accent of the selected tab"),
    TokenSpec("accent.selected", GROUP_ACCENT, "Background of a selected item"),
    # States.
    TokenSpec("state.ok", GROUP_STATE, "Success state"),
    TokenSpec("state.warn", GROUP_STATE, "Warning state"),
    TokenSpec("state.err", GROUP_STATE, "Error state"),
    TokenSpec("state.info", GROUP_STATE, "Informational state"),
    TokenSpec("state.danger.bg", GROUP_STATE, "Destructive button fill (gradient start)"),
    TokenSpec("state.danger.bg2", GROUP_STATE, "Destructive button fill (gradient end)"),
    TokenSpec("state.danger.bg.hover", GROUP_STATE, "Destructive button fill on hover (gradient start)"),
    TokenSpec("state.danger.bg2.hover", GROUP_STATE, "Destructive button fill on hover (gradient end)"),
    TokenSpec("state.danger.bg.pressed", GROUP_STATE, "Destructive button fill when pressed"),
    TokenSpec("state.danger.border", GROUP_STATE, "Border of a destructive button"),
    TokenSpec("state.danger.border.hover", GROUP_STATE, "Border of a destructive button on hover"),
    TokenSpec("state.danger.text", GROUP_STATE, "Text on a destructive fill"),
    TokenSpec("state.danger.solid", GROUP_STATE, "Solid destructive fill (window close hover)"),
    TokenSpec("state.danger.on", GROUP_STATE, "Text on the solid destructive fill"),
    # Focus, progress, slider.
    TokenSpec("focus.ring", GROUP_FOCUS, "Keyboard focus ring"),
    TokenSpec("progress.text", GROUP_PROGRESS, "Text of a progress bar"),
    TokenSpec("slider.track", GROUP_SLIDER, "Slider groove"),
    TokenSpec("slider.fill", GROUP_SLIDER, "Filled part of a slider"),
    # Paper — the A4 sheet of the report is always light, in every theme.
    TokenSpec("paper.surface", GROUP_PAPER, "A4 sheet of the report"),
    TokenSpec("paper.text", GROUP_PAPER, "Primary text on the A4 sheet"),
    TokenSpec("paper.text.dim", GROUP_PAPER, "Secondary text on the A4 sheet"),
    TokenSpec("paper.line", GROUP_PAPER, "Rules of the A4 sheet"),
    # Overlay — the drawing on the image. Filled in by UI-0 PR-7.
    TokenSpec("overlay.contour.manual", GROUP_OVERLAY, "Manually drawn contour"),
    TokenSpec("overlay.contour.auto", GROUP_OVERLAY, "Automatic (AI) contour"),
    TokenSpec("overlay.contour.model", GROUP_OVERLAY, "Model contour (Simpson)"),
    TokenSpec("overlay.caliper", GROUP_OVERLAY, "Caliper line and markers"),
    TokenSpec("overlay.caliper.doppler", GROUP_OVERLAY, "Doppler caliper line and markers"),
    TokenSpec("overlay.label", GROUP_OVERLAY, "Label of a measurement on the image"),
    TokenSpec("overlay.point", GROUP_OVERLAY, "Current point of a contour"),
    TokenSpec("overlay.marker", GROUP_OVERLAY, "End-diastole / end-systole markers"),
)

#: Token names in declaration order.
TOKEN_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOKENS)

#: Tokens that every palette must define (i.e. all but the pending groups).
REQUIRED_TOKEN_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOKENS if spec.group not in PENDING_GROUPS)

#: The 28-key palette contract of ``dark_theme.get_theme_palette()`` and the
#: token each legacy key is computed from. The mapping is the one of the spec
#: (§5.2); it is the only bridge between the old palette names and the tokens.
LEGACY_KEY_TO_TOKEN: dict[str, str] = {
    "bg_dark": "surface.0",
    "bg_panel": "surface.1",
    "bg_control": "surface.2",
    "bg_button": "surface.3",
    "bg_button_hover": "surface.hover",
    "bg_button_pressed": "surface.pressed",
    "accent": "accent",
    "accent_bright": "accent.text",
    "accent_tab": "accent.tab",
    "accent_selected": "accent.selected",
    "text": "text.1",
    "text_dim": "text.2",
    "border": "line.1",
    "slider_track": "slider.track",
    "slider_fill": "slider.fill",
    "reset_bg1": "state.danger.bg",
    "reset_bg2": "state.danger.bg2",
    "reset_hov1": "state.danger.bg.hover",
    "reset_hov2": "state.danger.bg2.hover",
    "reset_pressed": "state.danger.bg.pressed",
    "reset_border": "state.danger.border",
    "reset_border_hov": "state.danger.border.hover",
    "reset_text": "state.danger.text",
    "progress_text": "progress.text",
    "hover_btn1": "surface.hover.alt",
    "success": "state.ok",
    "warning": "state.warn",
    "error": "state.err",
}

#: The legacy key each token is published under. ``text.3``, ``text.disabled``,
#: ``line.2``, ``focus.ring`` and ``state.info`` have no legacy counterpart —
#: the old palette had a single key for each of them.
TOKEN_TO_LEGACY_KEY: dict[str, str] = {token: key for key, token in LEGACY_KEY_TO_TOKEN.items()}

#: The legacy palette keys, in the order of the old module.
LEGACY_KEYS: tuple[str, ...] = tuple(LEGACY_KEY_TO_TOKEN)

# ── Sizes (spec §5.2) ──────────────────────────────────────────────
#: Spacing grid, in px.
SPACING_SCALE: tuple[int, ...] = (4, 8, 12, 16, 24)
#: Corner radii, in px.
RADIUS_SCALE: tuple[int, ...] = (4, 6, 8, 10)
#: Control heights, in px.
CONTROL_HEIGHTS: tuple[int, ...] = (28, 32)
#: Icon sizes, in px.
ICON_SIZES: tuple[int, ...] = (16, 18)
#: Font sizes, in px. Values use tabular figures.
FONT_SIZES: tuple[float, ...] = (11.5, 12.5, 13.5, 15, 24)


def tokens_to_legacy(tokens: Mapping[str, str]) -> dict[str, str]:
    """Compute the legacy 28-key palette from semantic tokens.

    The inverse of :func:`legacy_to_tokens`; the result is what
    ``dark_theme.get_theme_palette()`` hands out until every call site is
    moved to tokens (UI-0 PR-3…PR-7, removal in UI-8).
    """
    missing = [key for key, token in LEGACY_KEY_TO_TOKEN.items() if token not in tokens]
    if missing:
        raise KeyError(f"palette is missing tokens for legacy keys: {', '.join(sorted(missing))}")
    return {key: tokens[token] for key, token in LEGACY_KEY_TO_TOKEN.items()}


def legacy_to_tokens(legacy: Mapping[str, str]) -> dict[str, str]:
    """Compute semantic tokens from a legacy 28-key palette.

    Used to move an existing palette into the token system without changing a
    single colour: every legacy key is mapped to its token, the tokens that
    had no legacy counterpart are derived from the ones that had.
    """
    missing = [key for key in LEGACY_KEYS if key not in legacy]
    if missing:
        raise KeyError(f"legacy palette is missing keys: {', '.join(sorted(missing))}")
    tokens: dict[str, str] = {token: legacy[key] for key, token in LEGACY_KEY_TO_TOKEN.items()}
    # The old palette had one key where the token system has several.
    tokens["text.3"] = legacy["text_dim"]
    tokens["text.disabled"] = legacy["text_dim"]
    tokens["line.2"] = legacy["border"]
    tokens["focus.ring"] = legacy["accent"]
    tokens["state.info"] = legacy["accent"]
    return tokens


def token_group(name: str) -> str:
    """Return the group of a token name."""
    for spec in TOKENS:
        if spec.name == name:
            return spec.group
    raise KeyError(f"unknown token: {name}")
