"""Unit tests for AppController auto-segmentation orchestration."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import Contour, InstanceMetadata
from echo_personal_tool.domain.services.segmentation_service import (
    mask_to_contour,
    smooth_contour,
)

pytest.importorskip("pytestqt")


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self._callbacks):
            callback(*args)


class _FakeWorker:
    def __init__(self, frame, *args, **kwargs) -> None:
        self.frame = np.ascontiguousarray(frame)
        self.args = args
        self.kwargs = kwargs
        self.signals = SimpleNamespace(
            finished=_FakeSignal(),
            failed=_FakeSignal(),
            timed_out=_FakeSignal(),
        )


class _RecordingThreadPool:
    def __init__(self) -> None:
        self.started: list[object] = []

    def start(self, worker) -> None:
        self.started.append(worker)


class _FakeSegmenter:
    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.calls = 0

    def is_available(self) -> bool:
        self.calls += 1
        return self.available

    def segment(self, frame: np.ndarray) -> np.ndarray:
        return frame


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _sample_instance() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=4,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=40.0,
        series_description="Test",
        path=Path("/tmp/test.dcm"),
    )


def _prepared_controller(
    monkeypatch: pytest.MonkeyPatch,
    *,
    available: bool = True,
) -> tuple[AppController, _RecordingThreadPool, _FakeSegmenter, InstanceMetadata, np.ndarray]:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.OnnxWorker",
        _FakeWorker,
    )
    thread_pool = _RecordingThreadPool()
    segmenter = _FakeSegmenter(available=available)
    controller = AppController(thread_pool=thread_pool, segmenter=segmenter)
    instance = _sample_instance()
    controller.state_manager.set_instance(instance, total_frames=4, frame_time_ms=40.0)
    controller.state_manager.mark_ed()
    controller._current_instance = instance

    pixels = np.arange(64, dtype=np.uint8).reshape(8, 8)
    controller._pending_load_id = 1
    controller._on_frame_loaded(1, instance.path, 0, pixels)
    return controller, thread_pool, segmenter, instance, pixels


def test_request_auto_segment_dispatches_worker_and_updates_contour(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, thread_pool, segmenter, _, pixels = _prepared_controller(monkeypatch)
    manual_ed = Contour(phase="ED", view="A4C", points=[(0.0, 0.0), (1.0, 1.0)])
    manual_es = Contour(phase="ES", view="A4C", points=[(2.0, 2.0), (3.0, 3.0)])
    controller.on_contours_changed([manual_ed, manual_es])

    controller.request_auto_segment()

    assert segmenter.calls == 1
    assert len(thread_pool.started) == 1
    worker = thread_pool.started[0]
    assert isinstance(worker, _FakeWorker)
    np.testing.assert_array_equal(worker.frame, pixels)

    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[2:6, 2:6] = 1
    worker.signals.finished.emit(mask)

    contours = controller.state_manager.snapshot.contours
    expected_points = smooth_contour(mask_to_contour(mask, pixels.shape[:2]), num_nodes=32)

    assert len(contours) == 2
    assert any(
        contour == Contour(phase="ES", view="A4C", points=manual_es.points)
        for contour in contours
    )
    assert any(
        contour.phase == "ED"
        and contour.view == "A4C"
        and contour.source == "ai"
        and contour.points == expected_points
        for contour in contours
    )
    assert controller._segment_in_progress is False


def test_request_auto_segment_rejects_when_segmenter_unavailable(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, thread_pool, segmenter, _, _ = _prepared_controller(
        monkeypatch,
        available=False,
    )
    messages: list[str] = []
    controller.status_message.connect(messages.append)

    controller.request_auto_segment()

    assert segmenter.calls == 1
    assert thread_pool.started == []
    assert messages[-1] == "сегментация недоступна — используйте ручной контур"


def test_request_auto_segment_rejects_when_frame_is_not_marked(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.OnnxWorker",
        _FakeWorker,
    )
    controller = AppController(
        thread_pool=_RecordingThreadPool(),
        segmenter=_FakeSegmenter(),
    )
    instance = _sample_instance()
    controller.state_manager.set_instance(instance, total_frames=4, frame_time_ms=40.0)
    controller._current_instance = instance
    controller._pending_load_id = 1
    controller._on_frame_loaded(1, instance.path, 0, np.zeros((8, 8), dtype=np.uint8))

    messages: list[str] = []
    controller.status_message.connect(messages.append)

    controller.request_auto_segment()

    assert messages[-1] == "Auto-segmentation requires an ED or ES frame"


def test_request_auto_segment_rejects_when_playing(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, thread_pool, _, _, _ = _prepared_controller(monkeypatch)
    controller.state_manager.set_playing(True)
    messages: list[str] = []
    controller.status_message.connect(messages.append)

    controller.request_auto_segment()

    assert thread_pool.started == []
    assert messages[-1] == "Pause playback before auto-segmentation"


def test_request_auto_segment_emits_timeout_message(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, thread_pool, _, _, _ = _prepared_controller(monkeypatch)
    messages: list[str] = []
    controller.status_message.connect(messages.append)

    controller.request_auto_segment()
    worker = thread_pool.started[0]
    worker.signals.timed_out.emit()

    assert messages[-1] == "сегментация недоступна — используйте ручной контур"
    assert controller._segment_in_progress is False


def test_request_auto_segment_blocks_concurrent_requests(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, thread_pool, _, _, _ = _prepared_controller(monkeypatch)
    messages: list[str] = []
    controller.status_message.connect(messages.append)

    controller.request_auto_segment()
    controller.request_auto_segment()

    assert len(thread_pool.started) == 1
    assert messages[-1] == "Segmentation already in progress"
