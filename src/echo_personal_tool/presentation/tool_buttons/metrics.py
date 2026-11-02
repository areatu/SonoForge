"""Nominal sizes of the tool row and the tool rail (spec §4.1, UI-2 PR-3).

Kept free of Qt so the numbers that decide how a pictogram fits its cell can be
checked without a GUI stack (:mod:`tests.unit.test_ui_icon_metrics`).

The glyph edge is explicit rather than taken from the style: ``QToolButton``
derives its default icon size from the platform style (16 px on Fusion, another
value on the Windows style), and together with the 12 px padding of the global
stylesheet it left a 10 px glyph box inside the fixed 38 px cell of the row —
the pictogram looked small and pushed to one side, and the same row was spaced
differently on Windows and Linux.
"""

from __future__ import annotations

from typing import Final

#: §4.1 — nominal sizes of the two views. The row remains a 42 px floor; the
#: rail stays 70 px wide and right-elides long captions (full text stays in the
#: tooltip/accessibility name) instead of stealing viewer width at high DPI.
ROW_HEIGHT_MIN: Final = 42
RAIL_WIDTH_MIN: Final = 70

#: §4.1 — the touch target of one button in both views.
BUTTON_EDGE_MIN: Final = 44

#: Logical edge of a glyph in the row / the rail.
ICON_EDGE_ROW: Final = 20
ICON_EDGE_RAIL: Final = 22

#: Margin kept around a glyph inside a cell of the row, in logical pixels.
ICON_CELL_MARGIN: Final = 8


def initial_for_caption(text: str) -> str:
    """First visible character of a caption, for a button without a glyph.

    An icon-only cell used to fall back to the whole caption, which the fixed
    width then elided to «…» — four identical «…» tiles in the row (N-07).  The
    first letter stays legible; the tooltip carries the full name.
    """
    for character in text or "":
        if character.isalnum():
            return character.upper()
    return "?"
