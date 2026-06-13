"""Unit tests for StateManager."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.domain.models import (
    Contour,
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
    InstanceMetadata,
    LinearMeasurement,
    MeasurementSnapshot,
    ViewerState,
)


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
    assert state.doppler_measurement is None
    assert state.contours == ()
    assert state.linear_measurements == ()
    assert state.measurement_snapshot is None


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
    assert state.doppler_measurement is None
    assert state.contours == ()
    assert state.linear_measurements == ()
    assert state.measurement_snapshot is None


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


def test_set_instance_clears_measurement_state(
    qtbot,
    instance_metadata: InstanceMetadata,
) -> None:
    manager = StateManager()
    manager.set_instance(instance_metadata, total_frames=100, frame_time_ms=33.3)
    contour = Contour(phase="ED", view="A4C", points=[(1.0, 2.0), (3.0, 4.0)])
    manager.set_contours((contour,))

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
    assert state.doppler_measurement is None
    assert state.contours == ()
    assert state.linear_measurements == ()
    assert state.measurement_snapshot is None


def test_set_doppler_measurement_updates_snapshot(qtbot) -> None:
    manager = StateManager()
    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="E", time_ms=120.0, velocity_cm_s=85.0),),
        intervals=(
            DopplerIntervalMarker(label="DT", start_time_ms=80.0, end_time_ms=260.0),
        ),
        traces=(DopplerTrace(label="VTI", points=((0.0, 0.0), (10.0, 2.0))),),
    )

    with qtbot.waitSignal(manager.state_changed):
        manager.set_doppler_measurement(dto)

    assert manager.snapshot.doppler_measurement == dto


def test_set_total_frames_clamps_current_frame_index(
    qtbot,
    instance_metadata: InstanceMetadata,
) -> None:
    manager = StateManager()
    manager.set_instance(instance_metadata, total_frames=10, frame_time_ms=33.3)
    manager.set_frame(9)
    assert manager.snapshot.current_frame_index == 9

    with qtbot.waitSignal(manager.state_changed):
        manager.set_total_frames(5)

    assert manager.snapshot.total_frames == 5
    assert manager.snapshot.current_frame_index == 4


def test_set_decode_in_progress(qtbot, instance_metadata: InstanceMetadata) -> None:
    manager = StateManager()
    manager.set_instance(instance_metadata, total_frames=10, frame_time_ms=33.3)
    assert manager.snapshot.decode_in_progress is False

    manager.set_decode_in_progress(True)
    assert manager.snapshot.decode_in_progress is True

    manager.set_decode_in_progress(False)
    assert manager.snapshot.decode_in_progress is False


def test_set_measurement_fields_update_snapshot(qtbot) -> None:
    manager = StateManager()
    contour = Contour(phase="ED", view="A4C", points=[(1.0, 2.0), (3.0, 4.0)])
    linear = LinearMeasurement(label="LVEDD", pixel_length=42.0, millimeter_length=21.0)
    snapshot = MeasurementSnapshot(linear_measurements=(linear,))

    with qtbot.waitSignal(manager.state_changed):
        manager.set_contours((contour,))
    assert manager.snapshot.contours == (contour,)

    with qtbot.waitSignal(manager.state_changed):
        manager.set_linear_measurements((linear,))
    assert manager.snapshot.linear_measurements == (linear,)

    with qtbot.waitSignal(manager.state_changed):
        manager.set_measurement_snapshot(snapshot)
    assert manager.snapshot.measurement_snapshot == snapshot


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
