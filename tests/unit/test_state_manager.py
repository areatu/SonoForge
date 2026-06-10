"""Unit tests for StateManager."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.domain.models import InstanceMetadata, ViewerState


@pytest.fixture
def instance_metadata() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=100,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Apical 4C",
        path=Path("/tmp/test.mp4"),
    )


def test_initial_snapshot(qtbot, instance_metadata: InstanceMetadata) -> None:
    manager = StateManager()
    state = manager.snapshot

    assert state.instance is None
    assert state.current_frame_index == 0
    assert state.total_frames == 0
    assert state.frame_time_ms is None
    assert state.is_playing is False
    assert state.ed_frame_index is None
    assert state.es_frame_index is None


def test_set_instance_resets_state_and_emits(
    qtbot,
    instance_metadata: InstanceMetadata,
) -> None:
    manager = StateManager()
    snapshots: list[ViewerState] = []
    manager.state_changed.connect(snapshots.append)

    with qtbot.waitSignal(manager.state_changed):
        manager.set_instance(instance_metadata, total_frames=100, frame_time_ms=33.3)

    state = snapshots[-1]
    assert state.instance == instance_metadata
    assert state.total_frames == 100
    assert state.frame_time_ms == 33.3
    assert state.current_frame_index == 0
    assert state.is_playing is False
    assert state.ed_frame_index is None
    assert state.es_frame_index is None


def test_set_frame_updates_index(qtbot, instance_metadata: InstanceMetadata) -> None:
    manager = StateManager()
    manager.set_instance(instance_metadata, total_frames=100, frame_time_ms=33.3)

    with qtbot.waitSignal(manager.state_changed):
        manager.set_frame(42)

    assert manager.snapshot.current_frame_index == 42


def test_set_frame_out_of_range_raises(
    qtbot,
    instance_metadata: InstanceMetadata,
) -> None:
    manager = StateManager()
    manager.set_instance(instance_metadata, total_frames=10, frame_time_ms=33.3)

    with pytest.raises(IndexError):
        manager.set_frame(10)

    with pytest.raises(IndexError):
        manager.set_frame(-1)


def test_set_frame_without_instance_raises() -> None:
    manager = StateManager()

    with pytest.raises(RuntimeError, match="without a loaded instance"):
        manager.set_frame(0)


def test_set_instance_rejects_invalid_total_frames(
    instance_metadata: InstanceMetadata,
) -> None:
    manager = StateManager()

    with pytest.raises(ValueError, match="total_frames must be >= 1"):
        manager.set_instance(instance_metadata, total_frames=0, frame_time_ms=33.3)

    with pytest.raises(ValueError, match="total_frames must be >= 1"):
        manager.set_instance(instance_metadata, total_frames=-1, frame_time_ms=33.3)

    assert manager.snapshot.instance is None
    assert manager.snapshot.total_frames == 0


def test_set_instance_accepts_single_frame(
    qtbot,
    instance_metadata: InstanceMetadata,
) -> None:
    manager = StateManager()

    with qtbot.waitSignal(manager.state_changed):
        manager.set_instance(instance_metadata, total_frames=1, frame_time_ms=33.3)

    assert manager.snapshot.total_frames == 1
    manager.set_frame(0)
    assert manager.snapshot.current_frame_index == 0

    with pytest.raises(IndexError):
        manager.set_frame(1)


def test_mark_ed_and_es_use_current_frame(
    qtbot,
    instance_metadata: InstanceMetadata,
) -> None:
    manager = StateManager()
    manager.set_instance(instance_metadata, total_frames=100, frame_time_ms=33.3)
    manager.set_frame(15)

    with qtbot.waitSignal(manager.state_changed):
        manager.mark_ed()
    assert manager.snapshot.ed_frame_index == 15
    assert manager.snapshot.es_frame_index is None

    manager.set_frame(55)
    with qtbot.waitSignal(manager.state_changed):
        manager.mark_es()
    assert manager.snapshot.es_frame_index == 55


def test_clear_phase_markers(qtbot, instance_metadata: InstanceMetadata) -> None:
    manager = StateManager()
    manager.set_instance(instance_metadata, total_frames=100, frame_time_ms=33.3)
    manager.set_frame(10)
    manager.mark_ed()
    manager.set_frame(20)
    manager.mark_es()

    with qtbot.waitSignal(manager.state_changed):
        manager.clear_phase_markers()

    state = manager.snapshot
    assert state.ed_frame_index is None
    assert state.es_frame_index is None
    assert state.current_frame_index == 20


def test_set_instance_clears_previous_markers(
    qtbot,
    instance_metadata: InstanceMetadata,
) -> None:
    manager = StateManager()
    manager.set_instance(instance_metadata, total_frames=100, frame_time_ms=33.3)
    manager.set_frame(7)
    manager.mark_ed()
    manager.mark_es()

    other = InstanceMetadata(
        sop_instance_uid="9.9.9",
        series_uid="8.8.8",
        modality="US",
        number_of_frames=50,
        pixel_spacing=None,
        frame_time_ms=40.0,
        series_description="PLAX",
        path=Path("/tmp/other.mp4"),
    )

    manager.set_instance(other, total_frames=50, frame_time_ms=40.0)
    state = manager.snapshot
    assert state.instance == other
    assert state.ed_frame_index is None
    assert state.es_frame_index is None


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
