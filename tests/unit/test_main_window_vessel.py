"""Tests for main window vessel wiring."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def window(qtbot):
    from echo_personal_tool.presentation.main_window import MainWindow

    widget = MainWindow()
    qtbot.addWidget(widget)
    return widget


def test_vessel_actions_dispatch_to_viewer(window, monkeypatch):
    from echo_personal_tool.presentation.measurement_action import MeasurementAction

    calls = []

    def fake_start_psv():
        calls.append("psv")
        return True

    def fake_clear():
        calls.append("clear")

    def fake_accept():
        calls.append("accept")

    monkeypatch.setattr(window._viewer, "start_vessel_psv", fake_start_psv)
    monkeypatch.setattr(window._viewer, "clear_vessel_measurement", fake_clear)
    monkeypatch.setattr(window._viewer, "accept_vessel_measurement", fake_accept)

    window._on_measure_action(MeasurementAction.VESSEL_PSV_EDV, "", "")
    window._on_measure_action(MeasurementAction.VESSEL_CLEAR, "", "")
    window._on_measure_action(MeasurementAction.VESSEL_ACCEPT, "", "")

    assert calls == ["psv", "clear", "accept"]


def test_sync_doppler_tool_availability_passes_vessel_ok(window, monkeypatch):
    def fake_is_vessel_available() -> bool:
        return True

    monkeypatch.setattr(window._viewer, "is_vessel_available", fake_is_vessel_available)
    captured = {}

    class _FakeToolPanel:
        def set_doppler_tool_availability(self, *, time_ok, vessel_ok=False):
            captured["time_ok"] = time_ok
            captured["vessel_ok"] = vessel_ok

    monkeypatch.setattr(window, "_tool_panel", _FakeToolPanel())

    window._sync_doppler_tool_availability()

    assert captured["vessel_ok"] is True


@pytest.mark.parametrize("acquisition", ["2d", "doppler"])
def test_vessels_mode_wires_stenosis_and_resets_on_panel_replacement(window, acquisition):
    from dataclasses import replace

    import numpy as np

    from echo_personal_tool.domain.models import InstanceMetadata

    viewer = window._viewer
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.9",
        series_uid="1.2.3",
        modality="US",
        number_of_frames=1,
        pixel_spacing=(0.1, 0.1),
        frame_time_ms=None,
        series_description="Synthetic vascular image",
        clip_mode=acquisition,
    )
    window._controller.state_manager.set_instance(instance, total_frames=1, frame_time_ms=None)
    viewer.show_frame(np.zeros((128, 128), dtype=np.uint8))
    window._tool_panel.set_view_context(acquisition, "PW")
    window._tool_panel.set_doppler_tool_availability(time_ok=False, vessel_ok=False)
    panel = window._tool_panel.measure
    panel._context_buttons["vessels"].click()
    assert viewer._vessel_measurement_mode is True
    assert window._radial_context() == "vessels"
    window._sync_tool_panel_context()
    assert panel.context() == "vessels"
    for tool_id, kind in (("vessel.stenosis_d", "stenosis_diameter"), ("vessel.stenosis_area", "stenosis_area")):
        panel._tile_buttons[tool_id].click()
        assert viewer._comparison_state.kind == kind
    # Re-enabling the legacy panel must not leave an invisible override behind.
    window._tool_panel.rebuild_menu_with_preferences(replace(window._user_preferences, tool_panel_v2=False))
    assert viewer._vessel_measurement_mode is False
