"""Clinical colours of the norm gradations (UI-5 PR-1).

A gradation («норма», «лёгкое», «умеренное», «тяжёлое») is **data of the
handbook**, not a role of the theme: the colour means the same thing in every
theme, the way a red value out of range does. UI-0 deliberately left these
literals where they were and named UI-5 as their owner; the card S2 is the
first consumer, so the palette now lives in one module both the card and the
reference window read.

Only the brightness differs between a dark and a light surface — the hue and
its meaning never change, so a physician moving between themes reads the same
scale. The pairs are ``(fill, text)``: the fill carries an alpha channel
because the segments of the scale sit on a themed surface.
"""

from __future__ import annotations

GRADE_COLORS: dict[str, tuple[str, str]] = {
    "норм": ("#1E22C55E", "#22c55e"),
    "лёгк": ("#1EEAB308", "#eab308"),
    "умерен": ("#1EF97316", "#f97316"),
    "тяжёл": ("#1EEF4444", "#ef4444"),
    "normal": ("#1E22C55E", "#22c55e"),
    "mild": ("#1EEAB308", "#eab308"),
    "moderate": ("#1EF97316", "#f97316"),
    "severe": ("#1EEF4444", "#ef4444"),
}

GRADE_COLORS_LIGHT: dict[str, tuple[str, str]] = {
    "норм": ("#2D22C55E", "#16a34a"),
    "лёгк": ("#2DEAB308", "#d97706"),
    "умерен": ("#2DF97316", "#ea580c"),
    "тяжёл": ("#2DEF4444", "#dc2626"),
    "normal": ("#2D22C55E", "#16a34a"),
    "mild": ("#2DEAB308", "#d97706"),
    "moderate": ("#2DF97316", "#ea580c"),
    "severe": ("#2DEF4444", "#dc2626"),
}


def is_light_theme() -> bool:
    """Whether the active theme paints on a light surface."""
    from echo_personal_tool.presentation.dark_theme import _current_theme_mode

    return _current_theme_mode in ("light", "vscode_light")


def grade_colors(name: str) -> tuple[str, str] | None:
    """``(fill, text)`` of a gradation name, or ``None`` for an unknown one.

    The name comes from the handbook and is matched by its stem, so the
    Russian «Тяжёлое» and the English «Severe» land on the same colour while
    the handbook keeps its own wording.
    """
    lowered = (name or "").lower()
    palette = GRADE_COLORS_LIGHT if is_light_theme() else GRADE_COLORS
    for keyword, colors in palette.items():
        if keyword in lowered:
            return colors
    return None
