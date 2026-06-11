"""Regression tests for DICOM decode-on-open and frame cache playback."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom

pytest.importorskip("pytestqt")


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self._callbacks):
            callback(*args)


class _FakeDecodeWorker:
    def __init__(self, path: Path, request_id: int, parent=None) -> None:
        self.path = Path(path)
        self.request_id = request_id
        self.parent = parent
        self.signals = SimpleNamespace(
            finished=_FakeSignal(),
            failed=_FakeSignal(),
        )


class _RecordingThreadPool:
    def __init__(self) -> None:
        self.started: list[object] = []

    def start(self, worker) -> None:
        self.started.append(worker)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _sample_dicom_instance(path: Path) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=4,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=40.0,
        series_description="Test",
        path=path,
        media_format="dicom",
    )


def test_load_instance_starts_dicom_decode_worker(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.DicomDecodeWorker",
        _FakeDecodeWorker,
    )
    thread_pool = _RecordingThreadPool()
    controller = AppController(thread_pool=thread_pool)
    path = tmp_path / "study.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=4, rows=16, cols=16)
    instance = _sample_dicom_instance(path)

    controller.load_instance(instance)

    assert len(thread_pool.started) == 1
    worker = thread_pool.started[0]
    assert isinstance(worker, _FakeDecodeWorker)
    assert worker.path.resolve() == path.resolve()
    assert controller.state_manager.snapshot.decode_in_progress is True


def test_stale_dicom_decode_request_is_ignored(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.DicomDecodeWorker",
        _FakeDecodeWorker,
    )
    thread_pool = _RecordingThreadPool()
    controller = AppController(thread_pool=thread_pool)
    path = tmp_path / "study.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=4, rows=16, cols=16)
    instance = _sample_dicom_instance(path)

    frame_events: list[np.ndarray] = []
    controller.frame_loaded.connect(frame_events.append)

    controller.load_instance(instance)
    worker = thread_pool.started[0]
    stale_frames = np.stack(
        [np.full((16, 16), 99, dtype=np.uint8) for _ in range(4)],
        axis=0,
    )
    worker.signals.finished.emit(999, path, stale_frames)

    assert controller.state_manager.snapshot.decode_in_progress is True
    assert not controller._frame_cache.is_ready(path)
    assert frame_events == []

    frames = np.stack(
        [np.full((16, 16), frame_index, dtype=np.uint8) for frame_index in range(4)],
        axis=0,
    )
    worker.signals.finished.emit(worker.request_id, path, frames)

    assert controller.state_manager.snapshot.decode_in_progress is False
    assert controller._frame_cache.is_ready(path)
    assert len(frame_events) == 1
    np.testing.assert_array_equal(frame_events[0], frames[0])


def test_cached_dicom_frame_change_emits_without_frame_loader(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.DicomDecodeWorker",
        _FakeDecodeWorker,
    )
    frame_loader_calls = {"count": 0}
    original_worker = __import__(
        "echo_personal_tool.application.workers.frame_loader_worker",
        fromlist=["FrameLoaderWorker"],
    ).FrameLoaderWorker

    class _SpyFrameLoader(original_worker):
        def __init__(self, *args, **kwargs):
            frame_loader_calls["count"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        _SpyFrameLoader,
    )
    thread_pool = _RecordingThreadPool()
    controller = AppController(thread_pool=thread_pool)
    path = tmp_path / "study.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=4, rows=16, cols=16)
    instance = _sample_dicom_instance(path)

    frame_events: list[np.ndarray] = []
    controller.frame_loaded.connect(frame_events.append)

    controller.load_instance(instance)
    worker = thread_pool.started[0]
    frames = np.stack(
        [np.full((16, 16), frame_index, dtype=np.uint8) for frame_index in range(4)],
        axis=0,
    )
    worker.signals.finished.emit(worker.request_id, path, frames)

    assert controller.state_manager.snapshot.decode_in_progress is False
    assert len(thread_pool.started) == 1
    frame_events.clear()

    controller.state_manager.set_frame(2)

    assert len(thread_pool.started) == 1
    assert len(frame_events) == 1
    np.testing.assert_array_equal(frame_events[0], frames[2])
    assert frame_loader_calls["count"] == 0


def test_invalid_decode_frames_clears_decode_state(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.DicomDecodeWorker",
        _FakeDecodeWorker,
    )
    thread_pool = _RecordingThreadPool()
    controller = AppController(thread_pool=thread_pool)
    path = tmp_path / "study.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=4, rows=16, cols=16)
    instance = _sample_dicom_instance(path)

    failed_messages: list[str] = []
    controller.frame_load_failed.connect(failed_messages.append)

    controller.load_instance(instance)
    worker = thread_pool.started[0]
    worker.signals.finished.emit(worker.request_id, path, "not-an-ndarray")

    assert controller.state_manager.snapshot.decode_in_progress is False
    assert failed_messages == ["Decoded frames are invalid"]
    assert not controller._frame_cache.is_ready(path)

