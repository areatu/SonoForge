"""Tests for measures menu next-step highlight."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from echo_personal_tool.presentation.measurement_action import MeasurementAction
from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_highlight_es_diameter_after_all_diastole_chain() -> None:
    menu = MeasuresMenuWidget()
    menu.highlight_action(MeasurementAction.LV2D_ES)
    es_button = next(
        btn
        for btn in menu.findChildren(QPushButton)
        if btn.text() == "КСР (2D)"
    )
    assert menu._blink_target is es_button
    menu.clear_highlight()
    assert menu._blink_target is None


def test_highlight_fac_after_ed_contour() -> None:
    menu = MeasuresMenuWidget()
    menu.highlight_action(MeasurementAction.RV_FAC)
    fac_button = next(
        btn for btn in menu.findChildren(QPushButton) if btn.text() == "FAC ПЖ"
    )
    assert menu._blink_target is fac_button


def test_highlight_manual_esv_after_edv() -> None:
    menu = MeasuresMenuWidget()
    menu.highlight_action(MeasurementAction.MANUAL_SIMPSON, view="A4C", phase="ES")
    esv_button = next(
        btn
        for btn in menu.findChildren(QPushButton)
        if btn.text() == "Simpson ES"
    )
    assert menu._blink_target is esv_button


def test_rv_section_has_fac_button() -> None:
    menu = MeasuresMenuWidget()
    fac_buttons = [
        btn for btn in menu.findChildren(QPushButton) if btn.text() == "FAC ПЖ"
    ]
    assert len(fac_buttons) == 1
