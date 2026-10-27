"""One control contract for the whole shell (buttons, chips, cards).

The redesign used to keep the numbers of a button in the stylesheet of every
panel that drew one: one radius here, another padding there, 4 px in the tool
row and 8 px in the settings dialog.  The result is what the acceptance
screenshots show — buttons of the same height with different corners, gaps
that change from panel to panel, and a primary action whose hover state is
indistinguishable from its resting state.

This module is the *single* source of those numbers and of the QSS recipe.
It is deliberately Qt-free: it takes the already-resolved token dict (the
colours of the active theme) and returns text, so it can be checked without a
GUI and cannot drift from :mod:`presentation.theme.palettes`.

Rules of the contract:

* one resting height for a control (:data:`CONTROL_HEIGHT`), one for a dense
  chip (:data:`CHIP_HEIGHT`), one for a card (:data:`CARD_RADIUS`);
* one radius (:data:`BUTTON_RADIUS`), one border width, one gap scale;
* every interactive control has four states — rest, hover, pressed, disabled —
  and a checked state that is the *quiet* accent tint, never a loud fill;
* every colour comes from a token.  No hex literal is written here: a hover
  or pressed fill is another token, never a brightened accent (which would
  break the 4.5:1 contrast of the caption).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

# ── Geometry (logical pixels, 100 % scale) ─────────────────────────────

#: Height of a normal single-line control (button, field, combobox).
CONTROL_HEIGHT = 32
#: Height of an icon-only or very dense control.
COMPACT_HEIGHT = 26
#: Height of a panel chip (label + badge on one line).
CHIP_HEIGHT = 34
#: Minimum height of a two-line tool row.
ROW_HEIGHT = 44

#: Radius shared by buttons, chips, fields and cards.
BUTTON_RADIUS = 6
CHIP_RADIUS = 6
CARD_RADIUS = 8
BADGE_RADIUS = 4

#: One border everywhere.
BORDER_WIDTH = 1

#: Spacing grid: 4 / 6 / 8 / 12.
GAP_XS = 4
GAP_SM = 6
GAP_MD = 8
GAP_LG = 12

#: Horizontal/vertical padding of a normal control.
PAD_X = 10
PAD_Y = 5
#: Padding of a dense chip.
CHIP_PAD_X = 8

#: Minimum width of one tool row in the measure panel: below it a caption
#: cannot be read, so the panel uses fewer columns instead of wrapping text.
MIN_TOOL_CELL_WIDTH = 136

#: Icon edge of a chip / a tool button.
ICON_EDGE = 16


def _join(selectors: Iterable[str]) -> str:
    return ", ".join(selectors)


def _with_state(selectors: tuple[str, ...], state: str) -> str:
    return _join(f"{selector}{state}" for selector in selectors)


def _block(selectors: tuple[str, ...], state: str, body: str) -> str:
    return f"{_with_state(selectors, state)} {{\n{body}\n}}\n"


def _pad(padding_x: int | None, padding_y: int | None, height: int | None) -> str:
    lines = []
    if padding_x is not None or padding_y is not None:
        lines.append(f"    padding: {padding_y if padding_y is not None else 0}px {padding_x or 0}px;")
    if height is not None:
        lines.append(f"    min-height: {height}px;")
    return "\n".join(lines)


def _rest_body(tokens: Mapping[str, str], *, background: str, border: str, color: str, extra: str) -> str:
    return (
        f"    background: {background};"
        f"\n    border: {BORDER_WIDTH}px solid {border};"
        f"\n    border-radius: {BUTTON_RADIUS}px;"
        f"\n    color: {color};{extra}"
    )


def button_qss(
    selectors: str | Iterable[str],
    tokens: Mapping[str, str],
    *,
    variant: str = "secondary",
    height: int | None = CONTROL_HEIGHT,
    padding_x: int | None = PAD_X,
    padding_y: int | None = PAD_Y,
    radius: int = BUTTON_RADIUS,
    font_size: int | None = None,
    checked: bool = True,
    text_align: str | None = None,
) -> str:
    """QSS of a button family with every interactive state.

    ``variant`` is ``secondary`` (the default quiet control), ``primary``
    (the one action that submits) or ``chip`` (a dense panel tile).  All three
    share geometry and the focus ring; only the resting fill differs, so a
    dialog and a panel cannot disagree about what a button looks like.
    """
    names = (selectors,) if isinstance(selectors, str) else tuple(selectors)
    if not names:
        return ""
    if variant == "primary":
        # The quiet accent tint is the *only* safe fill: brightening it with
        # more accent drops «accent.text» below 4.5:1 in VS Code/blue.  Hover
        # and press therefore change the border and the animated wash, not the
        # text background — the caption never loses its contrast.
        rest = ("accent.tint", "accent.line", "accent.text")
        hover = tokens["accent.tint"]
        pressed = tokens["accent.tint"]
        hover_border = tokens["accent"]
        press_border = tokens["accent"]
    elif variant == "chip":
        rest = ("surface.2", "line.1", "text.1")
        hover = tokens["surface.hover"]
        pressed = tokens["surface.pressed"]
        hover_border = tokens["accent.line"]
        press_border = tokens["accent.line"]
    else:
        rest = ("surface.2", "line.2", "text.1")
        hover = tokens["surface.hover"]
        pressed = tokens["surface.pressed"]
        hover_border = tokens["accent.line"]
        press_border = tokens["accent.line"]

    extra = _pad(padding_x, padding_y, height)
    if extra:
        extra = "\n" + extra
    if radius != BUTTON_RADIUS:
        extra += f"\n    border-radius: {radius}px;"
    if font_size is not None:
        extra += f"\n    font-size: {font_size}px;"
    if text_align:
        extra += f"\n    text-align: {text_align};"

    body = _rest_body(tokens, background=tokens[rest[0]], border=tokens[rest[1]], color=tokens[rest[2]], extra=extra)
    result = _block(names, "", body)
    result += _block(
        names,
        ":hover",
        f"    background: {hover};\n    border-color: {hover_border};\n    color: {tokens[rest[2]]};",
    )
    result += _block(
        names,
        ":pressed",
        f"    background: {pressed};\n    border-color: {press_border};",
    )
    if checked:
        result += _block(
            names,
            ":checked",
            f"    background: {tokens['accent.tint']};"
            f"\n    border-color: {tokens['accent.line']};"
            f"\n    color: {tokens['accent.text']};",
        )
    result += _block(
        names,
        ":focus",
        f"    border-color: {tokens['focus.ring']};\n    outline: none;",
    )
    result += _block(
        names,
        ":disabled",
        f"    background: {tokens['surface.1']};"
        f"\n    border-color: {tokens['line.1']};"
        f"\n    color: {tokens['text.disabled']};",
    )
    return result


def card_qss(selectors: str | Iterable[str], tokens: Mapping[str, str], *, radius: int = CARD_RADIUS) -> str:
    """QSS of a panel card: one surface, one hairline, one radius."""
    names = (selectors,) if isinstance(selectors, str) else tuple(selectors)
    if not names:
        return ""
    return _block(
        names,
        "",
        f"    background: {tokens['surface.1']};"
        f"\n    border: {BORDER_WIDTH}px solid {tokens['line.1']};"
        f"\n    border-radius: {radius}px;",
    )
