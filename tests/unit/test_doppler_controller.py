"""Unit tests for Doppler measurement controller wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.domain.models import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
    InstanceMetadata,
)


def _sample_instance() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=4,
        pixel_spacing=None,
        frame_time_ms=40.0,
        series_description="Test",
        path=Path("/tmp/test.dcm"),
    )


def _sample_measurement() -> DopplerMeasurementDTO:
    return DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=120.0, velocity_cm_s=85.0),),
        intervals=(
            DopplerIntervalMarker(label="DT", start_time_ms=80.0, end_time_ms=260.0),
        ),
        traces=(DopplerTrace(label="VTI", points=((0.0, 0.0), (10.0, 2.0))),),
    )


def test_state_manager_stores_doppler_measurement() -> None:
    manager = StateManager()
    dto = _sample_measurement()

    manager.set_doppler_measurement(dto)

    assert manager.snapshot.doppler_measurement == dto


def test_app_controller_handles_doppler_marker_changes(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(_sample_instance(), total_frames=4, frame_time_ms=40.0)

    messages: list[str] = []
    controller.status_message.connect(messages.append)

    dto = _sample_measurement()
    controller.on_doppler_markers_changed(dto)

    assert controller.state_manager.snapshot.doppler_measurement == dto
    assert messages[-1] == "Doppler: 1 peak, 1 interval, 1 trace"


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
