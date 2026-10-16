"""Semantic design tokens for every UI theme (UI-0, spec 2026-10-16 §5).

Three layers:

1. **Palettes** — raw colours per theme.  This module is the only place in
   ``presentation/`` where hex colour literals are allowed (see
   ``scripts/check_ui_colors.py``).
2. **Semantic tokens** — the role of a colour (``surface.1``, ``text.2``,
   ``state.err`` …).  Every theme defines the same token set.
3. **Consumers** (QSS, delegates, QPainter) read tokens only.

Until every caller has moved to tokens, :func:`legacy_palette` derives the 28
historical keys of ``dark_theme.get_theme_palette()`` from the tokens (removed
in UI-8).  The table :data:`LEGACY_KEY_TOKENS` is the documented mapping; the
derived dictionaries reproduce the pre-token palettes byte for byte, so the
generated stylesheet does not change (gate UI-0).

The module is pure Python (no Qt) so CI scripts can import it without a
display.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

# ── Token vocabulary ────────────────────────────────────────────────
#
# Order matters only for documentation and the contrast report.
TOKEN_NAMES: tuple[str, ...] = (
    # Surfaces, from the window background up to the hovered control.
    "surface.0",  # window background, field around the image
    "surface.1",  # panels, bars, title
    "surface.2",  # inputs, cards
    "surface.3",  # buttons, selected segment
    "surface.hover",  # hovered control
    "surface.hover.alt",  # secondary hover (legacy ``hover_btn1``)
    "surface.pressed",  # pressed control
    # Lines.
    "line.1",  # separators
    "line.2",  # control borders
    # Text.
    "text.1",  # primary text
    "text.2",  # secondary text
    "text.3",  # hints, units
    "text.disabled",  # disabled controls (no WCAG requirement)
    "text.on_fill",  # text on a filled progress chunk
    # Accent.
    "accent",  # active tool, primary button, focus
    "accent.text",  # accent-coloured text on a dark surface
    "accent.on",  # text on an accent fill
    "accent.selected",  # selection background
    # Controls.
    "control.track",  # slider groove
    # Destructive action (the red "Reset" button).
    "danger.fill",
    "danger.fill.end",
    "danger.hover",
    "danger.hover.end",
    "danger.pressed",
    "danger.line",
    "danger.line.hover",
    "danger.text",
    # States.
    "state.ok",
    "state.warn",
    "state.err",
    "state.info",
    # Keyboard focus ring.
    "focus.ring",
    # Window chrome.
    "window.close.hover",  # caption "close" button on hover (Windows red)
)

THEME_IDS: tuple[str, ...] = ("dark", "light", "vscode_dark", "vscode_light")
"""Theme ids as stored in ``UserPreferences.theme`` (plus ``"system"``)."""

DARK_THEMES: frozenset[str] = frozenset({"dark", "vscode_dark"})

_WINDOWS_CLOSE_RED = "#e81123"

# ── Palettes → tokens ──────────────────────────────────────────────
#
# Values are the pre-token palettes of ``dark_theme.py`` (navy, light,
# VS Code dark/light) expressed through the token table of spec §5.2.
# New tokens with no historical counterpart (``line.2``, ``text.3``,
# ``text.disabled``, ``accent.on``, ``state.info``, ``focus.ring``) are filled
# so that nothing visible changes: they repeat the closest existing role.

_NAVY: dict[str, str] = {
    "surface.0": "#102135",
    "surface.1": "#12273d",
    "surface.2": "#1a3050",
    "surface.3": "#244161",
    "surface.hover": "#2e5580",
    "surface.hover.alt": "#2e5580",
    "surface.pressed": "#0c1a29",
    "line.1": "#2a4a6b",
    "line.2": "#2a4a6b",
    "text.1": "#f1f5f9",
    "text.2": "#9bacbb",
    "text.3": "#9bacbb",
    "text.disabled": "#9bacbb",
    "text.on_fill": "#f1f5f9",
    "accent": "#40e2de",
    "accent.text": "#5ff0ea",
    "accent.on": "#0c1a29",
    "accent.selected": "#1a5c5a",
    "control.track": "#1a3050",
    "danger.fill": "#991b1b",
    "danger.fill.end": "#7f1d1d",
    "danger.hover": "#dc2626",
    "danger.hover.end": "#991b1b",
    "danger.pressed": "#7f1d1d",
    "danger.line": "#ef4444",
    "danger.line.hover": "#f87171",
    "danger.text": "#f1f5f9",
    "state.ok": "#34d399",
    "state.warn": "#fb923c",
    "state.err": "#f87171",
    "state.info": "#5ff0ea",
    "focus.ring": "#40e2de",
    "window.close.hover": _WINDOWS_CLOSE_RED,
}

_LIGHT: dict[str, str] = {
    "surface.0": "#f8fafc",
    "surface.1": "#ffffff",
    "surface.2": "#f1f5f9",
    "surface.3": "#e2e8f0",
    "surface.hover": "#cbd5e1",
    "surface.hover.alt": "#cbd5e1",
    "surface.pressed": "#94a3b8",
    "line.1": "#e2e8f0",
    "line.2": "#e2e8f0",
    "text.1": "#0f172a",
    "text.2": "#64748b",
    "text.3": "#64748b",
    "text.disabled": "#64748b",
    "text.on_fill": "#ffffff",
    "accent": "#0891b2",
    "accent.text": "#06b6d4",
    "accent.on": "#ffffff",
    "accent.selected": "#0e7490",
    "control.track": "#e2e8f0",
    "danger.fill": "#dc2626",
    "danger.fill.end": "#b91c1c",
    "danger.hover": "#ef4444",
    "danger.hover.end": "#dc2626",
    "danger.pressed": "#b91c1c",
    "danger.line": "#ef4444",
    "danger.line.hover": "#f87171",
    "danger.text": "#ffffff",
    "state.ok": "#22c55e",
    "state.warn": "#f59e0b",
    "state.err": "#ef4444",
    "state.info": "#0891b2",
    "focus.ring": "#0891b2",
    "window.close.hover": _WINDOWS_CLOSE_RED,
}

_VS_CODE_DARK: dict[str, str] = {
    "surface.0": "#1e1e1e",
    "surface.1": "#252526",
    "surface.2": "#333333",
    "surface.3": "#3c3c3c",
    "surface.hover": "#454545",
    "surface.hover.alt": "#505050",
    "surface.pressed": "#2d2d2d",
    "line.1": "#3c3c3c",
    "line.2": "#3c3c3c",
    "text.1": "#cccccc",
    "text.2": "#858585",
    "text.3": "#858585",
    "text.disabled": "#858585",
    "text.on_fill": "#cccccc",
    "accent": "#007acc",
    "accent.text": "#1a8fe3",
    "accent.on": "#ffffff",
    "accent.selected": "#007acc",
    "control.track": "#3c3c3c",
    "danger.fill": "#c42b1c",
    "danger.fill.end": "#a01d10",
    "danger.hover": "#e04030",
    "danger.hover.end": "#c42b1c",
    "danger.pressed": "#8b1a10",
    "danger.line": "#e04030",
    "danger.line.hover": "#f05545",
    "danger.text": "#cccccc",
    "state.ok": "#4ec9b0",
    "state.warn": "#cca700",
    "state.err": "#f14c4c",
    "state.info": "#1a8fe3",
    "focus.ring": "#007acc",
    "window.close.hover": _WINDOWS_CLOSE_RED,
}

_VS_CODE_LIGHT: dict[str, str] = {
    "surface.0": "#ffffff",
    "surface.1": "#f3f3f3",
    "surface.2": "#ececec",
    "surface.3": "#ddd",
    "surface.hover": "#c8c8c8",
    "surface.hover.alt": "#c0c0c0",
    "surface.pressed": "#b0b0b0",
    "line.1": "#d4d4d4",
    "line.2": "#d4d4d4",
    "text.1": "#333333",
    "text.2": "#6e6e6e",
    "text.3": "#6e6e6e",
    "text.disabled": "#6e6e6e",
    "text.on_fill": "#ffffff",
    "accent": "#0066b8",
    "accent.text": "#005a9e",
    "accent.on": "#ffffff",
    "accent.selected": "#0066b8",
    "control.track": "#d4d4d4",
    "danger.fill": "#c42b1c",
    "danger.fill.end": "#a01d10",
    "danger.hover": "#e04030",
    "danger.hover.end": "#c42b1c",
    "danger.pressed": "#8b1a10",
    "danger.line": "#c42b1c",
    "danger.line.hover": "#e04030",
    "danger.text": "#ffffff",
    "state.ok": "#16825d",
    "state.warn": "#bf8803",
    "state.err": "#c42b1c",
    "state.info": "#0066b8",
    "focus.ring": "#0066b8",
    "window.close.hover": _WINDOWS_CLOSE_RED,
}

THEME_TOKENS: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "dark": MappingProxyType(_NAVY),
        "light": MappingProxyType(_LIGHT),
        "vscode_dark": MappingProxyType(_VS_CODE_DARK),
        "vscode_light": MappingProxyType(_VS_CODE_LIGHT),
    }
)

# ── Compatibility: 28 legacy palette keys ──────────────────────────
#
# ``get_theme_palette()`` keeps returning these keys (computed from tokens)
# until every consumer reads tokens; removed in UI-8.
LEGACY_KEY_TOKENS: Mapping[str, str] = MappingProxyType(
    {
        "bg_dark": "surface.0",
        "bg_panel": "surface.1",
        "bg_control": "surface.2",
        "bg_button": "surface.3",
        "bg_button_hover": "surface.hover",
        "bg_button_pressed": "surface.pressed",
        "accent": "accent",
        "accent_bright": "accent.text",
        "accent_tab": "accent",
        "accent_selected": "accent.selected",
        "text": "text.1",
        "text_dim": "text.2",
        "border": "line.1",
        "slider_track": "control.track",
        "slider_fill": "accent",
        "reset_bg1": "danger.fill",
        "reset_bg2": "danger.fill.end",
        "reset_hov1": "danger.hover",
        "reset_hov2": "danger.hover.end",
        "reset_pressed": "danger.pressed",
        "reset_border": "danger.line",
        "reset_border_hov": "danger.line.hover",
        "reset_text": "danger.text",
        "progress_text": "text.on_fill",
        "hover_btn1": "surface.hover.alt",
        "success": "state.ok",
        "warning": "state.warn",
        "error": "state.err",
    }
)

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def normalize_theme_id(theme: str) -> str:
    """Map a stored theme id to a concrete palette id (unknown → navy).

    ``"system"`` is resolved by the caller (it needs the OS); here it falls
    back to navy like any unknown id.
    """
    return theme if theme in THEME_TOKENS else "dark"


def tokens_for(theme: str) -> Mapping[str, str]:
    """Read-only token mapping of a concrete theme (unknown → navy)."""
    return THEME_TOKENS[normalize_theme_id(theme)]


def token(theme: str, name: str) -> str:
    """One token value; raises ``KeyError`` for an unknown token name."""
    if name not in TOKEN_NAMES:
        raise KeyError(f"unknown design token: {name!r}")
    return tokens_for(theme)[name]


def legacy_palette(theme: str) -> dict[str, str]:
    """The historical 28-key palette computed from tokens (compatibility)."""
    values = tokens_for(theme)
    return {key: values[name] for key, name in LEGACY_KEY_TOKENS.items()}


def is_dark_theme(theme: str) -> bool:
    """Whether a concrete theme id draws light text on dark surfaces."""
    return normalize_theme_id(theme) in DARK_THEMES


def validate_tokens() -> list[str]:
    """Problems in the token tables (empty list = consistent)."""
    problems: list[str] = []
    expected = set(TOKEN_NAMES)
    if len(expected) != len(TOKEN_NAMES):
        problems.append("TOKEN_NAMES contains duplicates")
    for theme, values in THEME_TOKENS.items():
        missing = expected - set(values)
        extra = set(values) - expected
        if missing:
            problems.append(f"{theme}: missing tokens {sorted(missing)}")
        if extra:
            problems.append(f"{theme}: unknown tokens {sorted(extra)}")
        for name, value in values.items():
            if not _HEX_RE.match(value):
                problems.append(f"{theme}: {name} is not a hex colour: {value!r}")
    for key, name in LEGACY_KEY_TOKENS.items():
        if name not in expected:
            problems.append(f"legacy key {key} maps to unknown token {name}")
    return problems


# ── Contrast (WCAG 2.1) ─────────────────────────────────────────────


def _channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """``#rgb`` / ``#rrggbb`` / ``#rrggbbaa`` → (r, g, b); alpha is ignored."""
    if not _HEX_RE.match(value):
        raise ValueError(f"not a hex colour: {value!r}")
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def relative_luminance(value: str) -> float:
    r, g, b = hex_to_rgb(value)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.1 contrast ratio between two opaque colours (1.0 … 21.0)."""
    a = relative_luminance(foreground)
    b = relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


# Pairs checked by ``scripts/check_theme_contrast.py``: (foreground,
# backgrounds, minimum ratio).  Thresholds follow spec §5.2: primary text
# ≥ 7:1 (AAA), secondary and hint text ≥ 4.5:1 (AA), accent text ≥ 4.5:1,
# text on the accent fill ≥ 4.5:1.  ``text.disabled`` is exempt (WCAG sets
# no requirement for inactive controls).
_TEXT_SURFACES = ("surface.0", "surface.1", "surface.2", "surface.3")
CONTRAST_REQUIREMENTS: tuple[tuple[str, tuple[str, ...], float], ...] = (
    ("text.1", _TEXT_SURFACES, 7.0),
    ("text.2", _TEXT_SURFACES, 4.5),
    ("text.3", _TEXT_SURFACES, 4.5),
    ("accent.text", ("surface.0", "surface.1", "surface.2"), 4.5),
    ("accent.on", ("accent",), 4.5),
)

ENFORCED_CONTRAST_THEMES: frozenset[str] = frozenset()
"""Themes whose contrast failures break CI.

Empty in UI-0 PR-1: the historical themes are only reported (spec §5.3).
UI-0 PR-2 adds the new "Graphite" theme here.
"""


def contrast_failures(theme: str) -> list[tuple[str, str, float, float]]:
    """(foreground, background, ratio, required) for every failing pair."""
    values = tokens_for(theme)
    failures: list[tuple[str, str, float, float]] = []
    for foreground, backgrounds, required in CONTRAST_REQUIREMENTS:
        for background in backgrounds:
            ratio = contrast_ratio(values[foreground], values[background])
            if ratio + 1e-9 < required:
                failures.append((foreground, background, ratio, required))
    return failures
