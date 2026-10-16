"""Theme palettes: the raw colours behind the semantic tokens (UI-0, PR-1).

This is the only module of the presentation layer where raw hex literals are
allowed — everything else reads semantic tokens from :mod:`.tokens`. The
ratchet ``scripts/check_ui_colors.py`` enforces that rule in CI.

The four legacy themes (navy, light, VS Code dark, VS Code light) keep their
colours exactly as before: the token values below are the old palette values,
one by one, so the interface does not change while the palette is being
migrated to tokens. ``graphite`` is the neutral palette of the redesign
(spec §5.2); it becomes selectable in UI-0 PR-2.

The module is free of Qt imports on purpose: the CI scripts (colour ratchet,
contrast check) read the palettes without a GUI stack.
"""

from __future__ import annotations

from collections.abc import Mapping

from echo_personal_tool.presentation.theme.tokens import (
    REQUIRED_TOKEN_NAMES,
    tokens_to_legacy,
)

# ── Theme ids ─────────────────────────────────────────────────────
THEME_DARK = "dark"
THEME_LIGHT = "light"
THEME_VS_CODE_DARK = "vscode_dark"
THEME_VS_CODE_LIGHT = "vscode_light"
THEME_GRAPHITE = "graphite"

#: Every theme id known to the palette module.
THEME_IDS: tuple[str, ...] = (
    THEME_DARK,
    THEME_LIGHT,
    THEME_VS_CODE_DARK,
    THEME_VS_CODE_LIGHT,
    THEME_GRAPHITE,
)

# ── Colours that do not depend on the theme ───────────────────────
#: The A4 sheet of the report is always light, in every theme (spec §5.2).
PAPER_SURFACE = "#ffffff"
PAPER_TEXT = "#1b1f24"
PAPER_TEXT_DIM = "#5b6169"
PAPER_LINE = "#d6d9dd"

#: Solid fill of the window-close button on hover — the Windows accent red.
DANGER_SOLID = "#e81123"
#: Text on the solid destructive fill.
DANGER_ON = "#ffffff"

#: Default slider colours for widgets painted outside a themed context.
LEGACY_SLIDER_TRACK = "#1e2834"
LEGACY_SLIDER_FILL = "#3b82f6"


def _legacy_theme(
    *,
    surface_0: str,
    surface_1: str,
    surface_2: str,
    surface_3: str,
    surface_hover: str,
    surface_pressed: str,
    surface_hover_alt: str,
    line: str,
    text_1: str,
    text_2: str,
    accent: str,
    accent_text: str,
    accent_on: str,
    accent_tab: str,
    accent_selected: str,
    state_ok: str,
    state_warn: str,
    state_err: str,
    danger_bg: str,
    danger_bg2: str,
    danger_bg_hover: str,
    danger_bg2_hover: str,
    danger_bg_pressed: str,
    danger_border: str,
    danger_border_hover: str,
    danger_text: str,
    progress_text: str,
    slider_track: str,
    slider_fill: str,
) -> dict[str, str]:
    """Complete a legacy theme.

    The old palette had a single key where the token system has several:
    ``text_dim`` covered secondary text, hints and disabled elements,
    ``border`` covered separators and control borders, ``accent`` covered the
    focus ring. The token values below repeat the old colour on purpose — the
    interface must not change while the palette is being migrated.
    """
    tokens = {
        "surface.0": surface_0,
        "surface.1": surface_1,
        "surface.2": surface_2,
        "surface.3": surface_3,
        "surface.hover": surface_hover,
        "surface.pressed": surface_pressed,
        "surface.hover.alt": surface_hover_alt,
        "line.1": line,
        "text.1": text_1,
        "text.2": text_2,
        "accent": accent,
        "accent.text": accent_text,
        "accent.on": accent_on,
        "accent.tab": accent_tab,
        "accent.selected": accent_selected,
        "state.ok": state_ok,
        "state.warn": state_warn,
        "state.err": state_err,
        "state.danger.bg": danger_bg,
        "state.danger.bg2": danger_bg2,
        "state.danger.bg.hover": danger_bg_hover,
        "state.danger.bg2.hover": danger_bg2_hover,
        "state.danger.bg.pressed": danger_bg_pressed,
        "state.danger.border": danger_border,
        "state.danger.border.hover": danger_border_hover,
        "state.danger.text": danger_text,
        "progress.text": progress_text,
        "slider.track": slider_track,
        "slider.fill": slider_fill,
    }
    tokens["text.3"] = text_2
    tokens["text.disabled"] = text_2
    tokens["line.2"] = line
    tokens["focus.ring"] = accent
    tokens["state.info"] = accent
    tokens["state.danger.solid"] = DANGER_SOLID
    tokens["state.danger.on"] = DANGER_ON
    tokens["paper.surface"] = PAPER_SURFACE
    tokens["paper.text"] = PAPER_TEXT
    tokens["paper.text.dim"] = PAPER_TEXT_DIM
    tokens["paper.line"] = PAPER_LINE
    return tokens


# ── Navy (the former dark theme) ──────────────────────────────────
_NAVY = _legacy_theme(
    surface_0="#102135",
    surface_1="#12273d",
    surface_2="#1a3050",
    surface_3="#244161",
    surface_hover="#2e5580",
    surface_pressed="#0c1a29",
    surface_hover_alt="#2e5580",
    line="#2a4a6b",
    text_1="#f1f5f9",
    text_2="#9bacbb",
    accent="#40e2de",
    accent_text="#5ff0ea",
    accent_on="#062a29",
    accent_tab="#40e2de",
    accent_selected="#1a5c5a",
    state_ok="#34d399",
    state_warn="#fb923c",
    state_err="#f87171",
    danger_bg="#991b1b",
    danger_bg2="#7f1d1d",
    danger_bg_hover="#dc2626",
    danger_bg2_hover="#991b1b",
    danger_bg_pressed="#7f1d1d",
    danger_border="#ef4444",
    danger_border_hover="#f87171",
    danger_text="#f1f5f9",
    progress_text="#f1f5f9",
    slider_track="#1a3050",
    slider_fill="#40e2de",
)

# ── Light ──────────────────────────────────────────────────────────
_LIGHT = _legacy_theme(
    surface_0="#f8fafc",
    surface_1="#ffffff",
    surface_2="#f1f5f9",
    surface_3="#e2e8f0",
    surface_hover="#cbd5e1",
    surface_pressed="#94a3b8",
    surface_hover_alt="#cbd5e1",
    line="#e2e8f0",
    text_1="#0f172a",
    text_2="#64748b",
    accent="#0891b2",
    accent_text="#06b6d4",
    accent_on="#001f24",
    accent_tab="#0891b2",
    accent_selected="#0e7490",
    state_ok="#22c55e",
    state_warn="#f59e0b",
    state_err="#ef4444",
    danger_bg="#dc2626",
    danger_bg2="#b91c1c",
    danger_bg_hover="#ef4444",
    danger_bg2_hover="#dc2626",
    danger_bg_pressed="#b91c1c",
    danger_border="#ef4444",
    danger_border_hover="#f87171",
    danger_text="#ffffff",
    progress_text="#ffffff",
    slider_track="#e2e8f0",
    slider_fill="#0891b2",
)

# ── VS Code Dark 2026 (Default Dark+ inspired) ─────────────────────
_VS_CODE_DARK = _legacy_theme(
    surface_0="#1e1e1e",
    surface_1="#252526",
    surface_2="#333333",
    surface_3="#3c3c3c",
    surface_hover="#454545",
    surface_pressed="#2d2d2d",
    surface_hover_alt="#505050",
    line="#3c3c3c",
    text_1="#cccccc",
    text_2="#858585",
    accent="#007acc",
    accent_text="#1a8fe3",
    accent_on="#ffffff",
    accent_tab="#007acc",
    accent_selected="#007acc",
    state_ok="#4ec9b0",
    state_warn="#cca700",
    state_err="#f14c4c",
    danger_bg="#c42b1c",
    danger_bg2="#a01d10",
    danger_bg_hover="#e04030",
    danger_bg2_hover="#c42b1c",
    danger_bg_pressed="#8b1a10",
    danger_border="#e04030",
    danger_border_hover="#f05545",
    danger_text="#cccccc",
    progress_text="#cccccc",
    slider_track="#3c3c3c",
    slider_fill="#007acc",
)

# ── VS Code Light 2026 (Default Light+ inspired) ───────────────────
_VS_CODE_LIGHT = _legacy_theme(
    surface_0="#ffffff",
    surface_1="#f3f3f3",
    surface_2="#ececec",
    surface_3="#ddd",
    surface_hover="#c8c8c8",
    surface_pressed="#b0b0b0",
    surface_hover_alt="#c0c0c0",
    line="#d4d4d4",
    text_1="#333333",
    text_2="#6e6e6e",
    accent="#0066b8",
    accent_text="#005a9e",
    accent_on="#ffffff",
    accent_tab="#0066b8",
    accent_selected="#0066b8",
    state_ok="#16825d",
    state_warn="#bf8803",
    state_err="#c42b1c",
    danger_bg="#c42b1c",
    danger_bg2="#a01d10",
    danger_bg_hover="#e04030",
    danger_bg2_hover="#c42b1c",
    danger_bg_pressed="#8b1a10",
    danger_border="#c42b1c",
    danger_border_hover="#e04030",
    danger_text="#ffffff",
    progress_text="#ffffff",
    slider_track="#d4d4d4",
    slider_fill="#0066b8",
)

# ── Graphite (the neutral palette of the redesign, spec §5.2) ──────
#: The surfaces, the text colours, the accent and the state colours are fixed
#: by the spec (§5.2).  The hover/pressed steps of the surfaces and the
#: destructive scale are not: they were chosen in UI-0 PR-2 together with the
#: screenshots of the new theme (``tests/baselines/ui/graphite.png``) and are
#: held in place by the contrast gate (``ENFORCED_CONTRAST_THEMES``) and by the
#: screenshot base.  The destructive border stays clearly visible on every
#: surface (≥ 4.9:1), the destructive text on every fill (≥ 5.9:1).
_GRAPHITE = {
    "surface.0": "#0b0d0f",
    "surface.1": "#131619",
    "surface.2": "#1a1e22",
    "surface.3": "#23282d",
    "surface.hover": "#2b3138",
    "surface.pressed": "#191d21",
    "surface.hover.alt": "#2b3138",
    "line.1": "#262b31",
    "line.2": "#343b42",
    "text.1": "#e6e9ec",
    "text.2": "#a3abb3",
    "text.3": "#858f99",
    "text.disabled": "#6e7781",
    "accent": "#2bd1cb",
    "accent.text": "#5fe3dd",
    "accent.on": "#032421",
    "accent.tab": "#2bd1cb",
    "accent.selected": "#1c4a48",
    "state.ok": "#3ccb7f",
    "state.warn": "#f2a93b",
    "state.err": "#f06a6a",
    "state.info": "#5aa9ff",
    "state.danger.bg": "#8c2f2f",
    "state.danger.bg2": "#6f2424",
    "state.danger.bg.hover": "#b03a3a",
    "state.danger.bg2.hover": "#8c2f2f",
    "state.danger.bg.pressed": "#5c1e1e",
    "state.danger.border": "#f06a6a",
    "state.danger.border.hover": "#f58a8a",
    "state.danger.text": "#ffffff",
    "state.danger.solid": DANGER_SOLID,
    "state.danger.on": DANGER_ON,
    "focus.ring": "#2bd1cb",
    "progress.text": "#e6e9ec",
    "slider.track": "#1a1e22",
    "slider.fill": "#2bd1cb",
    "paper.surface": PAPER_SURFACE,
    "paper.text": PAPER_TEXT,
    "paper.text.dim": PAPER_TEXT_DIM,
    "paper.line": PAPER_LINE,
}

#: Theme id -> semantic tokens.
PALETTES: dict[str, dict[str, str]] = {
    THEME_DARK: _NAVY,
    THEME_LIGHT: _LIGHT,
    THEME_VS_CODE_DARK: _VS_CODE_DARK,
    THEME_VS_CODE_LIGHT: _VS_CODE_LIGHT,
    THEME_GRAPHITE: _GRAPHITE,
}

#: Theme id -> the legacy 28-key palette, computed from the tokens.
LEGACY_PALETTES: dict[str, dict[str, str]] = {
    theme_id: tokens_to_legacy(tokens) for theme_id, tokens in PALETTES.items()
}

#: Themes with a light background.
LIGHT_THEME_IDS: frozenset[str] = frozenset({THEME_LIGHT, THEME_VS_CODE_LIGHT})


def get_palette_tokens(theme_id: str) -> dict[str, str]:
    """Return the semantic tokens of a theme (empty dict for an unknown id)."""
    return dict(PALETTES.get(theme_id, {}))


def get_legacy_palette(theme_id: str) -> dict[str, str]:
    """Return the legacy 28-key palette of a theme (empty dict for an unknown id)."""
    return dict(LEGACY_PALETTES.get(theme_id, {}))


def is_dark_theme(theme_id: str) -> bool:
    """Tell whether a theme has a dark background."""
    return theme_id not in LIGHT_THEME_IDS


def missing_tokens(theme_id: str) -> tuple[str, ...]:
    """Return the tokens a theme does not define (empty for a complete theme)."""
    tokens = PALETTES.get(theme_id, {})
    return tuple(name for name in REQUIRED_TOKEN_NAMES if name not in tokens)


def validate_palette(theme_id: str) -> tuple[str, ...]:
    """Return the problems of a palette: unknown tokens and missing tokens."""
    tokens = PALETTES.get(theme_id, {})
    problems = [f"unknown token: {name}" for name in tokens if name not in REQUIRED_TOKEN_NAMES]
    problems += [f"missing token: {name}" for name in missing_tokens(theme_id)]
    return tuple(problems)


def token_value(tokens: Mapping[str, str], name: str, fallback: str = "") -> str:
    """Read a token with a fallback (used by the QSS builder)."""
    return tokens.get(name, fallback)
