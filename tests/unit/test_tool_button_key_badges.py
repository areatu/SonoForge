"""The key badge of the tool row: painted, reserved, and never resizing a cell.

Item 1 of the 2026-11-06 owner list.  Holding Alt used to rewrite the caption of
every row button into «подпись · клавиша» and switch the button to
``ToolButtonTextBesideIcon``, while the cell kept the width the row had measured
for the caption alone.  The content then grew past the cell, Qt re-centred it and
the row jumped — the report reads «Alt сдвигает иконки».

The rule these tests pin: the badge is *painted* over the cell, the cell reserves
its room up front, and ``geometry()`` of every button is identical before, during
and after the hint.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import QSize

from echo_personal_tool.presentation.tool_buttons.buttons import key_hint
from echo_personal_tool.presentation.tool_buttons.rail import ToolButtonRail
from echo_personal_tool.presentation.tool_buttons.row import KEY_BADGE_RESERVE, ToolButtonRow


def _captioned_spec(row: ToolButtonRow):
    """A button that keeps its caption and has a registered key."""
    for spec in row.specs():
        if key_hint(spec) and row.button(spec.id) is not None:
            return spec
    raise AssertionError("no row button carries a key hint")


def test_alt_keeps_every_geometry_and_style_of_the_row(qtbot) -> None:
    row = ToolButtonRow()
    qtbot.addWidget(row)
    row.resize(2400, 42)
    row.show()
    row.update_geometry()
    assert row.is_compact() is False

    def snapshot() -> list[tuple[tuple[int, int, int, int], object, str]]:
        return [
            (
                row.button(spec.id).geometry().getRect(),
                row.button(spec.id).toolButtonStyle(),
                row.button(spec.id).text(),
            )
            for spec in row.specs()
            if row.button(spec.id) is not None
        ]

    before = snapshot()
    spec = _captioned_spec(row)
    row.set_key_hints_visible(True)

    assert row.button(spec.id).key_badge_visible() is True
    assert snapshot() == before, "Alt changed a cell, its style or its caption"

    row.set_key_hints_visible(False)
    assert row.button(spec.id).key_badge_visible() is False
    assert snapshot() == before


def test_the_caption_reserves_the_badge_width(qtbot) -> None:
    """The cell a captioned button asks for includes the badge's room.

    The reserve is what keeps the painted letter from landing on the caption,
    and what makes the reserve independent of whether Alt is held right now.
    """
    from echo_personal_tool.presentation.tool_buttons.buttons import ToolButtonSpec

    row = ToolButtonRow()
    qtbot.addWidget(row)
    row.resize(2400, 42)
    row.show()
    unbound = ToolButtonSpec("kbd.none", "catalog", "tool.bogus_missing", icon="activity_area")
    assert not key_hint(unbound)

    control = row.button(_captioned_spec(row).id)
    assert control is not None
    width = row._caption_width(control, 38)
    text_width = control.fontMetrics().horizontalAdvance(control.text())
    icon_width = row.ICON_EDGE + 4 if not control.icon().isNull() else 0
    assert width >= text_width + icon_width + 2 * 8 + 4 + KEY_BADGE_RESERVE


def test_the_badge_needs_a_registered_key(qtbot) -> None:
    """A button without a binding shows nothing: the badge never invents a key."""
    from echo_personal_tool.presentation.tool_buttons.base import ToolButton
    from echo_personal_tool.presentation.tool_buttons.buttons import ToolButtonSpec

    spec = ToolButtonSpec("kbd.none", "catalog", "tool.bogus_missing", icon="activity_area")
    button = ToolButton(spec)
    qtbot.addWidget(button)
    button.resize(80, 38)
    button.set_key_badge_visible(True)
    assert button.key_badge_visible() is False


def test_the_rail_paints_the_same_badge_without_touching_the_caption(qtbot) -> None:
    rail = ToolButtonRail()
    qtbot.addWidget(rail)
    rail.resize(QSize(70, 700))
    rail.show()
    rail.update_geometry()
    spec = next(item for item in rail.specs() if key_hint(item))
    control = rail.button(spec.id)
    assert control is not None
    caption = control.text()
    before = control.geometry().getRect()

    rail.set_key_hints_visible(True)
    assert control.text() == caption, "the key letter belongs to the badge, not to the caption"
    assert control.geometry().getRect() == before
