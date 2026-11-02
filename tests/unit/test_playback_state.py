"""Playback state and controller tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.application.app_controller import (
    PROJECTION_DEBOUNCE_MS,
    AppController,
)
from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.protocols import StudyProjection

pytestmark = pytest.mark.gui


def _sample_instance(dicom_path: Path) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=4,
        pixel_spacing=None,
        frame_time_ms=40.0,
        series_description="Test",
        path=dicom_path,
    )


def test_state_manager_steps_and_wraps_frames(qtbot, synthetic_dicom_path) -> None:
    manager = StateManager()
    manager.set_instance(_sample_instance(synthetic_dicom_path), total_frames=4, frame_time_ms=40.0)

    manager.step_frame(1)
    assert manager.snapshot.current_frame_index == 1

    manager.step_frame(3)
    assert manager.snapshot.current_frame_index == 0

    manager.step_frame(-1)
    assert manager.snapshot.current_frame_index == 3


def test_app_controller_steps_via_state_manager(qtbot, synthetic_dicom_path) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        InstanceMetadata(
            sop_instance_uid="1.2.3",
            series_uid="1.2.4",
            modality="US",
            number_of_frames=5,
            pixel_spacing=None,
            frame_time_ms=33.3,
            series_description="Test",
            path=synthetic_dicom_path,
        ),
        total_frames=5,
        frame_time_ms=33.3,
    )

    controller.step_frame(2)
    assert controller.state_manager.snapshot.current_frame_index == 2

    controller.toggle_playback()
    assert controller.state_manager.snapshot.is_playing is True


def test_study_projection_debounce_emits_once(qtbot) -> None:
    controller = AppController()
    assert 50 <= PROJECTION_DEBOUNCE_MS <= 100

    received: list[StudyProjection] = []
    controller.study_projection_changed.connect(received.append)

    controller._schedule_study_projection_changed()
    controller._schedule_study_projection_changed()
    assert controller.projection_debounce_active is True

    controller.emit_projection_now()
    assert controller.projection_debounce_active is False
    assert len(received) == 1
    assert isinstance(received[0], StudyProjection)
