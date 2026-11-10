"""StateManager A→B loop region (issue 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication  # noqa: F401  # Qt app for the signal-carrying manager

from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.domain.models import InstanceMetadata


@pytest.fixture()
def instance_metadata() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5.7.1",
        series_uid="1.2.3.4.5.7",
        modality="US",
        number_of_frames=100,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Stress echo 4C",
        path=Path("/tmp/stress.mp4"),
    )


@pytest.fixture()
def manager(qtbot, instance_metadata: InstanceMetadata) -> StateManager:
    state_manager = StateManager()
    state_manager.set_instance(instance_metadata, total_frames=100, frame_time_ms=33.3)
    return state_manager


def test_loop_bounds_default_to_none(manager: StateManager) -> None:
    assert manager.loop_bounds() is None
    assert manager.loop_state() == (None, None, False)
    assert not manager.loop_armed()


def test_loop_bounds_clamp_and_order(manager: StateManager) -> None:
    assert manager.set_loop_bounds(40, 10) == (10, 40)  # swapped into A ≤ B
    assert manager.loop_bounds() == (10, 40)
    assert manager.set_loop_bounds(-5, 500) == (0, 99)  # clamped to the clip


def test_loop_bound_setter_uses_current_frame(manager: StateManager) -> None:
    manager.set_frame(30)
    assert manager.set_loop_bound("a", 30) == (30, 30)  # B not set yet → collapses → disarmed
    manager.set_frame(50)
    assert manager.set_loop_bound("b", 50) == (30, 50)


def test_toggle_loop_requires_a_region(manager: StateManager) -> None:
    assert manager.toggle_loop() is False  # no bounds yet
    manager.set_loop_bounds(10, 20)
    assert manager.toggle_loop() is True
    assert manager.loop_state() == (10, 20, True)
    assert manager.toggle_loop() is False
    assert manager.loop_state() == (10, 20, False)


def test_collapsed_region_disarms(manager: StateManager) -> None:
    manager.set_loop_bounds(15, 25)
    manager.set_loop_armed(True)
    assert manager.loop_armed()
    manager.set_loop_bounds(20, 20)  # collapsing the region disarms
    assert not manager.loop_armed()


def test_step_frame_wraps_inside_the_armed_loop(manager: StateManager) -> None:
    manager.set_loop_bounds(10, 20)
    manager.set_loop_armed(True)
    manager.set_frame(19)
    manager.step_frame(1)
    assert manager.snapshot.current_frame_index == 20
    manager.step_frame(1)
    assert manager.snapshot.current_frame_index == 10  # wrapped B → A
    manager.step_frame(-1)
    assert manager.snapshot.current_frame_index == 20  # wrapped A → B backwards


def test_step_frame_outside_the_loop_snaps_into_it(manager: StateManager) -> None:
    manager.set_loop_bounds(10, 20)
    manager.set_loop_armed(True)
    manager.set_frame(80)  # parked beyond B
    manager.step_frame(1)
    assert manager.snapshot.current_frame_index == 10


def test_step_frame_plain_modulo_without_loop(manager: StateManager) -> None:
    manager.set_frame(99)
    manager.step_frame(1)
    assert manager.snapshot.current_frame_index == 0
    manager.set_frame(0)
    manager.step_frame(-1)
    assert manager.snapshot.current_frame_index == 99


def test_loop_next_frame_helper(manager: StateManager) -> None:
    manager.set_loop_bounds(10, 12)
    manager.set_loop_armed(True)
    assert manager.loop_next_frame(10) == 11
    assert manager.loop_next_frame(12) == 10
    assert manager.loop_next_frame(12, 2) == 11
    assert manager.loop_next_frame(10, -1) == 12


def test_loop_reset_on_instance_swap(manager: StateManager, instance_metadata: InstanceMetadata) -> None:
    manager.set_loop_bounds(10, 20)
    manager.set_loop_armed(True)
    manager.set_instance(instance_metadata, total_frames=100, frame_time_ms=33.3)
    assert manager.loop_state() == (None, None, False)


def test_loop_region_reclamped_on_total_change(manager: StateManager) -> None:
    manager.set_loop_bounds(80, 95)
    manager.set_loop_armed(True)
    manager.set_total_frames(50)
    assert manager.loop_bounds() == (49, 49)
    # clamped into the new clip; collapsed pair disarms
    assert not manager.loop_armed()
