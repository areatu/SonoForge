"""Playback state and controller tests."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.domain.models import InstanceMetadata


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


def test_state_manager_steps_and_wraps_frames(qtbot) -> None:
    manager = StateManager()
    manager.set_instance(_sample_instance(), total_frames=4, frame_time_ms=40.0)

    manager.step_frame(1)
    assert manager.snapshot.current_frame_index == 1

    manager.step_frame(3)
    assert manager.snapshot.current_frame_index == 0

    manager.step_frame(-1)
    assert manager.snapshot.current_frame_index == 3


def test_app_controller_steps_via_state_manager(qtbot) -> None:
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
            path=Path("/tmp/test.dcm"),
        ),
        total_frames=5,
        frame_time_ms=33.3,
    )

    controller.step_frame(2)
    assert controller.state_manager.snapshot.current_frame_index == 2

    controller.toggle_playback()
    assert controller.state_manager.snapshot.is_playing is True


def test_app_controller_mark_ed_and_es(qtbot) -> None:
    controller = AppController()
    controller.state_manager.set_instance(
        _sample_instance(),
        total_frames=4,
        frame_time_ms=40.0,
    )
    controller.state_manager.set_frame(1)

    status_messages: list[str] = []
    controller.status_message.connect(status_messages.append)

    controller.mark_ed()
    assert controller.state_manager.snapshot.ed_frame_index == 1
    assert controller.state_manager.snapshot.es_frame_index is None
    assert status_messages[-1] == "ED marked at frame 2"

    controller.state_manager.set_frame(3)
    controller.mark_es()
    assert controller.state_manager.snapshot.es_frame_index == 3
    assert status_messages[-1] == "ES marked at frame 4"
