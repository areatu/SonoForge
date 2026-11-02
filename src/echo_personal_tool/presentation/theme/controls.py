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
  chip (:data:`CHIP_HEIGHT`), one for a card (:data:`CARD_RADIUS`); vertical
  padding is font-relative (``em``), so the same numbers grow with the UI font
  instead of pinning a fixed pixel box (Э4/D-26);
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

#: The one rhythm of the shell, read as «air between blocks», not as numbers
#: scattered over the panels: 2 / 4 / 6 / 8 / 12 / 16 / 24.  A caption sits 8 px
#: over its content, two blocks are 16 px apart, a page section is 24 px from
#: the next.  Every panel of the redesign uses these instead of its own
#: literals — the 2026-10-27 review found «Анатомия» 4 px over its chips and
#: the chips 2 px over the tools, which read as one broken block.
SPACE_2XS = 2
SPACE_XS = GAP_XS
SPACE_SM = GAP_SM
SPACE_MD = GAP_MD
SPACE_LG = GAP_LG
SPACE_XL = 16
SPACE_2XL = 24

#: Height of one row of the measurement list (a tool, a hidden tool).
LIST_ROW_HEIGHT = 30
#: Height of the section caption that names the open anatomy group.
SECTION_HEADER_HEIGHT = 26

#: Horizontal/vertical padding of a normal control.  ``PAD_Y`` is a *pixel*
#: value at the reference 13 px UI font: QSS emits it in ``em`` (see
#: :data:`REFERENCE_FONT_PX`) so large user fonts are not clipped by a fixed
#: ``min-height`` box.
PAD_X = 10
PAD_Y = 5
REFERENCE_FONT_PX = 13
#: Padding of a dense chip.
CHIP_PAD_X = 8

#: Minimum width of one tool row in the measure panel: below it a caption
#: cannot be read, so the panel uses fewer columns instead of wrapping text.
MIN_TOOL_CELL_WIDTH = 136

#: Icon edge of a chip / a tool button.
ICON_EDGE = 16


def type_scale(font_size: int) -> dict[str, int]:
    """Pixel sizes of the text roles, derived from the user's UI font.

    Five roles, not fifteen (app-screen study: 4–9 sizes per screen, median 6;
    the cleanest scales are 12/14/16/24).  ``meta`` never goes below 11 px — the
    house floor — so a badge or an axis caption stays legible at the smallest
    UI font the settings allow.
    """
    body = int(font_size)
    return {
        "meta": max(11, body - 2),  # badges, counts, hints
        "small": max(11, body - 1),  # captions, secondary labels
        "body": body,  # controls, rows, cells
        "title": body + 2,  # panel / section titles
        "display": body + 5,  # the one heading of a dialog
    }


def _join(selectors: Iterable[str]) -> str:
    return ", ".join(selectors)


def _with_state(selectors: tuple[str, ...], state: str) -> str:
    return _join(f"{selector}{state}" for selector in selectors)


def _block(selectors: tuple[str, ...], state: str, body: str) -> str:
    return f"{_with_state(selectors, state)} {{\n{body}\n}}\n"


def _pad(padding_x: int | None, padding_y: int | str | None, height: int | None) -> str:
    """Emit padding + a content minimum, keeping the box font-scalable.

    Qt adds the QSS padding *on top of* ``min-height``.  A pixel-only vertical
    padding therefore made the whole control exactly ``height + 2*PAD_Y`` tall
    at every font — the Э4/D-26 audit caught the frozen action bar.  Expressing
    the vertical padding in ``em`` keeps the 100 % geometry and lets a 24 px
    UI font grow the control.
    """
    lines = []
    if padding_x is not None or padding_y is not None:
        if isinstance(padding_y, str):
            vertical = padding_y
        elif padding_y is None:
            vertical = "0"
        else:
            vertical = f"{padding_y / REFERENCE_FONT_PX:.3f}em"
        lines.append(f"    padding: {vertical} {padding_x or 0}px;")
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
    padding_y: int | str | None = PAD_Y,
    radius: int = BUTTON_RADIUS,
    font_size: int | None = None,
    checked: bool = True,
    text_align: str | None = None,
) -> str:
    """QSS of a button family with every interactive state.

    ``variant`` is ``secondary`` (the default quiet control), ``primary``
    (the one action that submits), ``chip`` (a dense panel tile) or ``ghost``
    (a toolbar action that must not add another box to the screen).  All four
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
    elif variant == "tile":
        # A chip that lives *inside* a panel: a tone step instead of a frame.
        # Four groups of five framed chips (quick, favourites, anatomy, tools)
        # made the panel read as a wall of boxes; the tile keeps the fill of the
        # resting state and gives the border up, so the checked chip is the one
        # outline in its group.
        rest = ("surface.2", "transparent", "text.1")
        hover = tokens["surface.3"]
        pressed = tokens["surface.pressed"]
        hover_border = "transparent"
        press_border = "transparent"
    elif variant == "ghost":
        # A toolbar of nine boxed buttons is the loudest thing on the screen
        # (2026-10-27: «9 одинаковых рамок»).  A ghost control keeps the text
        # and the glyph, gains a fill only under the pointer or when it is the
        # armed tool — the row recedes, the image and the measurements lead.
        rest = ("surface.1", "transparent", "text.2")
        hover = tokens["surface.hover"]
        pressed = tokens["surface.pressed"]
        hover_border = "transparent"
        press_border = "transparent"
    else:
        rest = ("surface.2", "line.2", "text.1")
        hover = tokens["surface.hover"]
        pressed = tokens["surface.pressed"]
        hover_border = tokens["accent.line"]
        press_border = tokens["accent.line"]

    def value(name: str) -> str:
        """A token name, or a literal QSS keyword such as ``transparent``."""
        return name if name.startswith("#") or name in ("transparent", "none") else tokens[name]

    extra = _pad(padding_x, padding_y, height)
    if extra:
        extra = "\n" + extra
    if radius != BUTTON_RADIUS:
        extra += f"\n    border-radius: {radius}px;"
    if font_size is not None:
        extra += f"\n    font-size: {font_size}px;"
    if text_align:
        extra += f"\n    text-align: {text_align};"

    body = _rest_body(tokens, background=value(rest[0]), border=value(rest[1]), color=value(rest[2]), extra=extra)
    result = _block(names, "", body)
    hover_color = tokens["text.1"] if variant == "ghost" else value(rest[2])
    result += _block(
        names,
        ":hover",
        f"    background: {hover};\n    border-color: {hover_border};\n    color: {hover_color};",
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
    disabled_background = "transparent" if variant == "ghost" else tokens["surface.1"]
    disabled_border = "transparent" if variant == "ghost" else tokens["line.1"]
    result += _block(
        names,
        ":disabled",
        f"    background: {disabled_background};"
        f"\n    border-color: {disabled_border};"
        f"\n    color: {tokens['text.disabled']};",
    )
    return result


def list_row_qss(
    selectors: str | Iterable[str],
    tokens: Mapping[str, str],
    *,
    separated: bool = True,
) -> str:
    """QSS of a row of the measurement list: a rule, a hover fill, an armed tint.

    The panel used to draw every tool as a bordered tile in a three-column grid
    (2026-10-27: «непонятная вторая строка», «слишком тесно»).  A *list* is the
    form the app-screen rules give a set of peer tools: one column, a 1 px rule
    between neighbours, the value on the right edge.  No card per row, no gap
    lottery, and a long Russian name has the whole width before it is elided.
    """
    names = (selectors,) if isinstance(selectors, str) else tuple(selectors)
    if not names:
        return ""
    border = f"    border-bottom: {BORDER_WIDTH}px solid {tokens['line.1']};\n" if separated else ""
    result = _block(
        names,
        "",
        f"    background: transparent;\n{border}    border-radius: 0;\n    color: {tokens['text.1']};",
    )
    result += _block(
        names,
        ":hover",
        f"    background: {tokens['surface.hover']};\n    color: {tokens['text.1']};",
    )
    result += _block(
        names,
        '[active="true"]',
        f"    background: {tokens['accent.tint']};",
    )
    result += _block(
        names,
        '[available="false"]',
        f"    color: {tokens['text.disabled']};",
    )
    result += _block(
        names,
        ":focus",
        f"    border-color: {tokens['focus.ring']};\n    outline: none;",
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
