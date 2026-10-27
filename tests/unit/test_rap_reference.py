"""The RAP hover card (2026-10-27 UI list, item 7)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

pytestmark = pytest.mark.gui


def _hover(widget) -> None:
    pos = QPointF(3, 3)
    QApplication.sendEvent(widget, QEnterEvent(pos, pos, pos))


def test_rap_model_has_a_norm_and_the_ase_source() -> None:
    from echo_personal_tool.presentation.rap_reference import RAP_PARAM_KEY, rap_card_model

    assert RAP_PARAM_KEY == "ra.rap"
    model = rap_card_model()
    assert model.known and model.has_norm
    assert model.param_id == "rap"
    assert "2025" in model.source


def test_step_bar_chips_open_the_card_after_the_hover_delay(qtbot) -> None:
    from echo_personal_tool.presentation.protocol_step_bar import ProtocolStepBar
    from echo_personal_tool.presentation.reference_card import HOVER_DELAY_MS

    bar = ProtocolStepBar()
    qtbot.addWidget(bar)
    bar.show()
    QApplication.processEvents()
    chips = bar._rap_values.findChildren(QPushButton)
    assert [chip.text() for chip in chips] == ["3", "8", "15", "…"]
    chip = chips[0]
    chip.show()
    _hover(chip)
    QTest.qWait(HOVER_DELAY_MS + 120)
    card = bar._rap_hover.card
    assert card is not None and card.isVisible()
    assert card._model is not None and card._model.param_id == "rap"
    bar.clear()
    assert not card.isVisible()


def test_step_bar_forwards_open_in_handbook(qtbot) -> None:
    from echo_personal_tool.presentation.protocol_step_bar import ProtocolStepBar

    bar = ProtocolStepBar()
    qtbot.addWidget(bar)
    seen: list[str] = []
    bar.rap_reference_requested.connect(seen.append)
    bar._rap_hover.reference_requested.emit("ra.rap")
    assert seen == ["ra.rap"]


def test_protocol_card_rap_tile_is_a_hover_anchor(qtbot) -> None:
    from echo_personal_tool.domain.protocol_definitions import TR_PASP
    from echo_personal_tool.domain.protocols import StudyProjection, progress
    from echo_personal_tool.infrastructure.user_preferences import UserPreferences
    from echo_personal_tool.presentation.tool_panel_v2.panel import ToolPanelV2

    panel = ToolPanelV2(UserPreferences())
    qtbot.addWidget(panel)
    card = panel._protocol_card
    card.set_protocols([TR_PASP])
    state = progress(TR_PASP, StudyProjection(values={}))
    card.set_progress(state)
    rap_steps = [index for index, step in enumerate(TR_PASP.steps) if "ra.rap" in step.satisfied_keys]
    assert rap_steps, "TR/PASP must keep its RAP input step"
    assert card._rap_hover._anchors, "the RAP tile must be a hover anchor"
    seen: list[str] = []
    panel.open_reference_requested.connect(seen.append)
    card._rap_hover.reference_requested.emit("ra.rap")
    assert seen == ["ra.rap"]
