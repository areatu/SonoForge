"""Tests for vessel section in MeasuresMenuWidget."""

from __future__ import annotations

import pytest

from echo_personal_tool.presentation.measurement_action import MeasurementAction

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def menu():
    from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget

    return MeasuresMenuWidget()


def test_vessel_section_has_buttons(menu):
    actions = {spec.action for _, spec in menu._tool_buttons}
    assert MeasurementAction.VESSEL_PSV in actions
    assert MeasurementAction.VESSEL_EDV in actions
    assert MeasurementAction.VESSEL_ACCEPT in actions
    assert MeasurementAction.VESSEL_CLEAR in actions


def test_vessel_buttons_disabled_without_calibration(menu):
    menu.set_doppler_tool_availability(time_ok=False, vessel_ok=False)
    for button, spec in menu._tool_buttons:
        if spec.action in {
            MeasurementAction.VESSEL_PSV,
            MeasurementAction.VESSEL_EDV,
            MeasurementAction.VESSEL_ACCEPT,
            MeasurementAction.VESSEL_CLEAR,
        }:
            assert button.isEnabled() is False


def test_vessel_buttons_enabled_with_calibration(menu):
    menu.set_doppler_tool_availability(time_ok=False, vessel_ok=True)
    for button, spec in menu._tool_buttons:
        if spec.action == MeasurementAction.VESSEL_PSV:
            assert button.isEnabled() is True


def test_set_vessel_status(menu):
    menu.set_vessel_status("Готово")
    assert menu._vessel_status_label.text() == "Готово"
