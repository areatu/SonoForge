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
    assert MeasurementAction.VESSEL_PSV_EDV in actions
    assert MeasurementAction.VESSEL_AUTO_TRACE_UP in actions
    assert MeasurementAction.VESSEL_AUTO_TRACE_DOWN in actions
    assert MeasurementAction.VESSEL_ACCEPT in actions
    assert MeasurementAction.VESSEL_CLEAR in actions
    assert "vessel_edv" not in {str(a) for a in actions}


def test_vessel_preset_defaults_to_normal(menu):
    assert menu.vessel_preset() == "normal"


def test_vessel_preset_changes(menu):
    combo = menu._vessel_preset_combo
    combo.setCurrentIndex(combo.findData("high"))
    assert menu.vessel_preset() == "high"
    combo.setCurrentIndex(combo.findData("low"))
    assert menu.vessel_preset() == "low"


def test_vessel_auto_trace_disabled_without_calibration(menu):
    menu.set_doppler_tool_availability(time_ok=False, vessel_ok=False)
    for button, spec in menu._tool_buttons:
        if spec.action == MeasurementAction.VESSEL_AUTO_TRACE_UP:
            assert button.isEnabled() is False
            return
    raise AssertionError("VESSEL_AUTO_TRACE_UP button not found")


def test_vessel_buttons_disabled_without_calibration(menu):
    menu.set_doppler_tool_availability(time_ok=False, vessel_ok=False)
    for button, spec in menu._tool_buttons:
        if spec.action in {
            MeasurementAction.VESSEL_PSV_EDV,
            MeasurementAction.VESSEL_ACCEPT,
            MeasurementAction.VESSEL_CLEAR,
        }:
            assert button.isEnabled() is False


def test_vessel_buttons_enabled_with_calibration(menu):
    menu.set_doppler_tool_availability(time_ok=False, vessel_ok=True)
    for button, spec in menu._tool_buttons:
        if spec.action == MeasurementAction.VESSEL_PSV_EDV:
            assert button.isEnabled() is True


def test_set_vessel_status(menu):
    menu.set_vessel_status("Готово")
    assert menu._vessel_status_label.text() == "Готово"
