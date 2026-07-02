"""Unit tests for AppController auto-segmentation orchestration."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata

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


def _circle_mask(
    *,
    height: int,
    width: int,
    center_y: float,
    center_x: float,
    radius: float,
) -> np.ndarray:
    ys, xs = np.ogrid[:height, :width]
    distance = (ys - center_y) ** 2 + (xs - center_x) ** 2
    return (distance <= radius**2).astype(np.uint8)


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
    controller._current_instance = instance

    pixels = np.arange(64, dtype=np.uint8).reshape(8, 8)
    controller._pending_load_id = 1
    controller._on_frame_loaded(1, instance.path, 0, pixels)
    return controller, thread_pool, segmenter, instance, pixels


def test_request_auto_segment_requires_active_simpson_workflow(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, thread_pool, segmenter, _, _ = _prepared_controller(monkeypatch)
    messages: list[str] = []
    controller.status_message.connect(messages.append)

    controller.request_auto_segment()

    assert segmenter.calls == 0
    assert thread_pool.started == []
    assert messages[-1] == "Auto-segmentation: select A4C/A2C ED or ES in worksheet first"


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

    assert segmenter.calls == 0
    assert thread_pool.started == []
    assert messages[-1] == "Auto-segmentation: select A4C/A2C ED or ES in worksheet first"


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

    assert messages[-1] == "Auto-segmentation: select A4C/A2C ED or ES in worksheet first"


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

    assert thread_pool.started == []
    assert messages[-1] == "Auto-segmentation: select A4C/A2C ED or ES in worksheet first"
    assert controller._segment_in_progress is False


def test_request_auto_segment_starts_worker_when_phase_set(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, thread_pool, segmenter, _, _ = _prepared_controller(monkeypatch)
    controller.set_simpson_workflow_context(phase="ED", view="A4C", chamber="LV")

    controller.request_auto_segment()

    assert segmenter.calls == 1
    assert len(thread_pool.started) == 1
    assert controller._segment_in_progress is True


def test_request_auto_segment_blocks_concurrent_requests(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, thread_pool, _, _, _ = _prepared_controller(monkeypatch)
    messages: list[str] = []
    controller.status_message.connect(messages.append)

    controller.request_auto_segment()
    controller.request_auto_segment()

    assert thread_pool.started == []
    assert messages[-1] == "Auto-segmentation: select A4C/A2C ED or ES in worksheet first"


def test_on_auto_segment_finished_sets_review_pending(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        AppController,
        "_should_auto_refine_after_segment",
        lambda self: False,
    )
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.explain_lv_auto_reject_reason",
        lambda contour, pixel_spacing: None,
    )
    controller, _, _, instance, _ = _prepared_controller(monkeypatch)
    controller.set_simpson_workflow_context(phase="ED", view="A4C")
    messages: list[str] = []
    controller.status_message.connect(messages.append)
    mask = _circle_mask(
        height=64,
        width=48,
        center_y=32,
        center_x=24,
        radius=18,
    )

    controller._on_auto_segment_finished(
        "ED",
        "A4C",
        "LV",
        instance.path,
        0,
        (64, 48),
        mask,
    )

    contours = controller.state_manager.snapshot.contours
    assert len(contours) == 1
    assert contours[0].source == "ai"
    assert contours[0].review_pending is True
    assert messages[-1] == (
        "A4C ED: review contour (ASE, no papillary muscles) \u00b7 R \u2014 refine \u00b7 Enter \u2014 accept"
    )


def test_accept_ai_contour_review_clears_pending(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        AppController,
        "_should_auto_refine_after_segment",
        lambda self: False,
    )
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.explain_lv_auto_reject_reason",
        lambda contour, pixel_spacing: None,
    )
    controller, _, _, instance, _ = _prepared_controller(monkeypatch)
    controller.set_simpson_workflow_context(phase="ED", view="A4C")
    messages: list[str] = []
    controller.status_message.connect(messages.append)
    mask = _circle_mask(
        height=64,
        width=48,
        center_y=32,
        center_x=24,
        radius=18,
    )

    controller._on_auto_segment_finished(
        "ED",
        "A4C",
        "LV",
        instance.path,
        0,
        (64, 48),
        mask,
    )

    accepted = controller.accept_ai_contour_review("A4C", "ED")

    contours = controller.state_manager.snapshot.contours
    assert accepted is True
    assert len(contours) == 1
    assert contours[0].review_pending is False
    assert messages[-1] == "A4C ED: contour accepted"


def test_on_auto_segment_finished_auto_refines_when_enabled(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echo_personal_tool.domain.models import Contour

    controller, _, _, instance, pixels = _prepared_controller(monkeypatch)
    controller.set_simpson_workflow_context(phase="ED", view="A4C")
    refine_calls: list[tuple[np.ndarray, Contour]] = []

    def _fake_refine(frame: np.ndarray, contour: Contour, **kwargs: object) -> tuple[Contour, str]:
        refine_calls.append((frame, contour))
        shifted = [(x + 1.0, y) for x, y in contour.points]
        return dataclasses.replace(contour, points=shifted), "gradient"

    monkeypatch.setattr(
        "echo_personal_tool.domain.services.mbs_lite_service.refine_open_arc_contour",
        _fake_refine,
    )
    monkeypatch.setattr(
        AppController,
        "_should_auto_refine_after_segment",
        lambda self: True,
    )
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.explain_lv_auto_reject_reason",
        lambda contour, pixel_spacing: None,
    )

    mask = _circle_mask(
        height=64,
        width=48,
        center_y=32,
        center_x=24,
        radius=18,
    )
    controller._on_auto_segment_finished(
        "ED",
        "A4C",
        "LV",
        instance.path,
        0,
        (64, 48),
        mask,
    )

    contours = controller.state_manager.snapshot.contours
    assert len(contours) == 1
    assert contours[0].review_pending is True
    assert refine_calls
    assert refine_calls[0][0] is pixels


def test_request_auto_segment_requires_a4c_view(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, thread_pool, _, _, _ = _prepared_controller(monkeypatch)
    controller.set_simpson_workflow_context(phase="ED", view="A2C")
    messages: list[str] = []
    controller.status_message.connect(messages.append)

    controller.request_auto_segment()

    assert thread_pool.started == []
    assert "unavailable" in messages[-1].lower() or "недоступн" in messages[-1]


@pytest.fixture(autouse=True)
def _en_locale():
    from echo_personal_tool.infrastructure.i18n import set_language
    set_language("en")
    yield
    set_language("ru")
