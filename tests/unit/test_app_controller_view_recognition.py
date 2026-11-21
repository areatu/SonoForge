"""Tests for the view-recognition coordinator hook (#639 step 4).

The coordinator (a ``QObject``) owns the once-per-series recognition run;
the controller only forwards loaded frames via ``frame_loaded``.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.application.view_recognition_coordinator import (
    ViewRecognitionCoordinator,
)
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


def _coordinator(
    tmp_path: Path,
    thread_pool: _RecordingThreadPool,
    *,
    frames: list[np.ndarray] | None = None,
) -> tuple[ViewRecognitionCoordinator, InMemoryDecisionStore]:
    store = InMemoryDecisionStore()
    workflow = ViewRecognitionWorkflow(StubRecognizer("A4C", 0.9), store)
    coordinator = ViewRecognitionCoordinator(
        workflow,
        thread_pool,
        resolve_study_uid=lambda instance: (instance.series_uid and "study-1") or "study-1",
        current_instance=lambda: None,
        frame_cache=FrameCache(max_cache_bytes=64 * 1024 * 1024),
        current_frame_pixels=lambda: None,
    )
    coordinator._current_instance = lambda: None  # type: ignore[method-assign]  # noqa: SLF001
    if frames is not None:
        # The frame cache is empty in tests; feed sampled frames directly.
        coordinator._sample_frames = lambda path: frames  # type: ignore[method-assign]  # noqa: SLF001
    return coordinator, store


def _frames() -> list[np.ndarray]:
    return [np.zeros((4, 4), dtype=np.float32) for _ in range(3)]


def test_first_frame_triggers_recognition_worker(qapp: QApplication, tmp_path: Path) -> None:
    pool = _RecordingThreadPool()
    coordinator, _ = _coordinator(tmp_path, pool, frames=_frames())
    coordinator._current_instance = lambda: _instance("inst-1", tmp_path)  # type: ignore[method-assign]  # noqa: SLF001

    coordinator.maybe_start()

    assert len(pool.started) == 1
    worker = pool.started[0]
    assert isinstance(worker, ViewRecognitionWorker)


def test_recognition_runs_once_per_series(qapp: QApplication, tmp_path: Path) -> None:
    pool = _RecordingThreadPool()
    coordinator, _ = _coordinator(tmp_path, pool, frames=_frames())
    coordinator._current_instance = lambda: _instance("inst-1", tmp_path)  # type: ignore[method-assign]  # noqa: SLF001

    coordinator.maybe_start()
    coordinator.maybe_start()

    assert len(pool.started) == 1


def test_non_2d_clip_is_skipped(qapp: QApplication, tmp_path: Path) -> None:
    pool = _RecordingThreadPool()
    coordinator, _ = _coordinator(tmp_path, pool)
    coordinator._current_instance = lambda: _instance(  # type: ignore[method-assign]  # noqa: SLF001
        "inst-1", tmp_path, clip_mode="doppler"
    )

    coordinator.maybe_start()

    assert pool.started == []


def test_worker_result_emits_suggestion_signal(qapp: QApplication, tmp_path: Path) -> None:
    pool = _RecordingThreadPool()
    coordinator, _ = _coordinator(tmp_path, pool, frames=_frames())
    coordinator._current_instance = lambda: _instance("inst-1", tmp_path)  # type: ignore[method-assign]  # noqa: SLF001

    received: list[object] = []
    coordinator.suggestion_ready.connect(received.append)
    coordinator.maybe_start()

    worker = pool.started[0]
    worker.run()  # same-thread: direct emission

    assert len(received) == 1
    suggestion = received[0]
    assert suggestion.view == "A4C"
    assert suggestion.is_confident is True


def test_choose_view_persists_and_emits(qapp: QApplication, tmp_path: Path) -> None:
    pool = _RecordingThreadPool()
    coordinator, store = _coordinator(tmp_path, pool, frames=_frames())
    coordinator._current_instance = lambda: _instance("inst-1", tmp_path)  # type: ignore[method-assign]  # noqa: SLF001

    received: list[object] = []
    coordinator.decision_changed.connect(received.append)
    decision = coordinator.choose_view("A2C")

    assert decision is not None
    assert len(received) == 1
    stored = received[0]
    assert isinstance(stored, ViewDecision)
    assert stored.view == "A2C"
    assert stored.source is ViewDecisionSource.MANUAL

    # The persisted choice is restored on the next suggestion (no re-run).
    assert store.load("study-1", "series-1") is not None
