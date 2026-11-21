"""Tests for the AppController view-recognition hook (#639 step 4)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.composition import in_memory_app_services
from echo_personal_tool.application.workers.view_recognition_worker import (
    ViewRecognitionWorker,
)
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.view_recognition import (
    RecognizedView,
    ViewDecision,
    ViewDecisionSource,
)
from echo_personal_tool.domain.services.view_recognition_workflow import (
    ViewRecognitionWorkflow,
)


class StubRecognizer:
    def __init__(self, view: str, confidence: float) -> None:
        self._view = view
        self._confidence = confidence

    def recognize(self, frames: Sequence[np.ndarray]) -> RecognizedView:
        del frames
        return RecognizedView(self._view, self._confidence)


class InMemoryDecisionStore:
    def __init__(self) -> None:
        self._decisions: dict[tuple[str, str], ViewDecision] = {}

    def load(self, study_uid: str, series_uid: str) -> ViewDecision | None:
        return self._decisions.get((study_uid, series_uid))

    def save(self, decision: ViewDecision) -> None:
        self._decisions[(decision.study_uid, decision.series_uid)] = decision


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


def _instance(uid: str, tmp_path: Path, *, clip_mode: str = "2d") -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="series-1",
        modality="US",
        number_of_frames=8,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="Cine",
        path=tmp_path / f"{uid}.dcm",
        media_format="dicom",
        clip_mode=clip_mode,
    )


def _controller(
    tmp_path: Path,
    thread_pool: _RecordingThreadPool,
    *,
    frames: list[np.ndarray] | None = None,
) -> AppController:
    services = in_memory_app_services()
    store = InMemoryDecisionStore()
    workflow = ViewRecognitionWorkflow(StubRecognizer("A4C", 0.9), store)
    controller = AppController(services=services, thread_pool=thread_pool)
    controller._view_workflow = workflow  # noqa: SLF001 - test wiring
    controller._view_attempted.clear()  # noqa: SLF001 - test wiring
    if frames is not None:
        # The frame cache is empty in tests; feed sampled frames directly.
        controller._sample_recognition_frames = lambda path: frames  # noqa: SLF001
    return controller


def _frames() -> list[np.ndarray]:
    return [np.zeros((4, 4), dtype=np.float32) for _ in range(3)]


def test_first_frame_triggers_recognition_worker(qapp: QApplication, tmp_path: Path) -> None:
    pool = _RecordingThreadPool()
    controller = _controller(tmp_path, pool, frames=_frames())
    controller._current_instance = _instance("inst-1", tmp_path)  # noqa: SLF001

    controller._maybe_start_view_recognition()

    assert len(pool.started) == 1
    worker = pool.started[0]
    assert isinstance(worker, ViewRecognitionWorker)


def test_recognition_runs_once_per_series(qapp: QApplication, tmp_path: Path) -> None:
    pool = _RecordingThreadPool()
    controller = _controller(tmp_path, pool, frames=_frames())
    controller._current_instance = _instance("inst-1", tmp_path)  # noqa: SLF001

    controller._maybe_start_view_recognition()
    controller._maybe_start_view_recognition()

    assert len(pool.started) == 1


def test_non_2d_clip_is_skipped(qapp: QApplication, tmp_path: Path) -> None:
    pool = _RecordingThreadPool()
    controller = _controller(tmp_path, pool)
    controller._current_instance = _instance(  # noqa: SLF001
        "inst-1", tmp_path, clip_mode="doppler"
    )

    controller._maybe_start_view_recognition()

    assert pool.started == []


def test_worker_result_emits_suggestion_signal(qapp: QApplication, tmp_path: Path) -> None:
    pool = _RecordingThreadPool()
    controller = _controller(tmp_path, pool, frames=_frames())
    controller._current_instance = _instance("inst-1", tmp_path)  # noqa: SLF001

    received: list[object] = []
    controller.view_suggestion_ready.connect(received.append)
    controller._maybe_start_view_recognition()

    worker = pool.started[0]
    worker.run()  # same-thread: direct emission

    assert len(received) == 1
    suggestion = received[0]
    assert suggestion.view == "A4C"
    assert suggestion.is_confident is True


def test_choose_view_persists_and_emits(qapp: QApplication, tmp_path: Path) -> None:
    pool = _RecordingThreadPool()
    controller = _controller(tmp_path, pool, frames=_frames())
    controller._current_instance = _instance("inst-1", tmp_path)  # noqa: SLF001

    received: list[object] = []
    controller.view_decision_changed.connect(received.append)
    controller.choose_view("A2C")

    assert len(received) == 1
    decision = received[0]
    assert isinstance(decision, ViewDecision)
    assert decision.view == "A2C"
    assert decision.source is ViewDecisionSource.MANUAL

    # The persisted choice is restored on the next suggestion (no re-run).
    controller._view_attempted.clear()  # noqa: SLF001
    controller._maybe_start_view_recognition()
    worker = pool.started[-1]
    worker.run()
