"""Context swaps reuse tool rows instead of rebuilding the widget tree."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.tool_status import ToolState, ToolStatus
from echo_personal_tool.infrastructure.i18n import set_language
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.tool_panel_v2.panel import ToolPanelV2
from echo_personal_tool.presentation.tool_panel_v2.sections import ToolRow

pytestmark = pytest.mark.gui


@pytest.fixture
def panel(qtbot) -> ToolPanelV2:
    widget = ToolPanelV2(UserPreferences())
    qtbot.addWidget(widget)
    widget.resize(320, 640)
    widget.show()
    QApplication.processEvents()
    return widget


def _flush_deletes() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_shared_rows_survive_context_swaps(panel) -> None:
    original = panel._rows["tool.caliper"]
    for context in ("vessels", "2d", "m", "doppler", "2d", "vessels", "2d"):
        panel._on_context_clicked(context)
        QApplication.processEvents()
        _flush_deletes()
    assert panel._rows["tool.caliper"] is original
    # The pool is bounded by the catalogue, not by the number of switches.
    assert len(panel._row_pool) < 150
    rows = panel.findChildren(ToolRow)
    assert len({row.tool.id for row in rows}) == len(rows)


def test_statuses_and_highlight_are_restored_after_reuse(panel) -> None:
    status = ToolStatus(
        tool_id="lv.linear_ed", state=ToolState.DONE, text="52 mm", value=52.0, unit="mm", key="lv.lvidd"
    )
    panel.set_tool_statuses([status])
    panel.highlight_tool("lv.linear_ed")
    row = panel._rows["lv.linear_ed"]
    assert row.is_active()

    panel._on_context_clicked("m")
    _flush_deletes()
    panel._on_context_clicked("2d")
    _flush_deletes()

    restored = panel._rows["lv.linear_ed"]
    assert restored is row
    assert restored.is_active()
    assert restored.measurement_value == 52.0
    assert restored.has_value()


def test_stale_status_does_not_leak_into_a_new_context(panel) -> None:
    panel.set_tool_statuses(
        [ToolStatus(tool_id="lv.linear_ed", key="lv.lvidd", state=ToolState.DONE, text="52 mm", value=52.0)]
    )
    panel.set_tool_statuses([])
    panel._on_context_clicked("m")
    panel._on_context_clicked("2d")
    _flush_deletes()
    assert not panel._rows["lv.linear_ed"].has_value()


def test_reused_rows_stay_visible_after_a_rebuild(panel) -> None:
    """Pooled rows arrive hidden (prepare_for_reuse) and must be reshown.

    Qt keeps the explicit hide() flag through layout.addWidget, so without
    row.show() in ToolSection the second rebuild drew an empty tool list
    under the Anatomy chips (2026-10-30).
    """
    panel._rebuild()
    QApplication.processEvents()
    _flush_deletes()
    open_sections = [section for section in panel._section_widgets if section.isVisible()]
    assert open_sections, "the panel must keep one open anatomy section"
    for section in open_sections:
        assert section.rows(), "an open section carries its tool rows"
        assert all(row.isVisible() for row in section.rows())


def test_language_change_rebuilds_row_labels(panel) -> None:
    original = panel._rows["tool.caliper"]
    set_language("en")
    try:
        panel.reload_text()
        _flush_deletes()
        assert panel._rows["tool.caliper"] is not original
        assert panel._rows["tool.caliper"]._language == "en"
    finally:
        set_language("ru")
        panel.reload_text()


def test_row_wheel_cancels_hover_card_and_yields_to_scroll(panel) -> None:
    row = panel._rows["tool.caliper"]
    row._hover_timer.start()
    hidden: list[str] = []
    row.reference_hide_requested.connect(hidden.append)
    event = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(row, event)
    assert not event.isAccepted()
    assert not row._hover_timer.isActive()
    assert hidden == [row.tool.id]
