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
def window():
    from echo_personal_tool.presentation.main_window import MainWindow

    return MainWindow()


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
