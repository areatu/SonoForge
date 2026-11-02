"""Regressions for queued worker-signal lifetime in AppController.

A very fast QRunnable can finish before the GUI event loop handles its queued
signal.  The controller must retain the worker/signals object until that event
has been consumed rather than silently losing the result.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import Contour

pytestmark = pytest.mark.gui


def test_scan_worker_result_survives_thread_pool_completion(qtbot, tmp_path, monkeypatch) -> None:
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    controller = AppController(thread_pool=pool)

    # Keep this regression focused on ScanWorker -> AppController delivery;
    # measurement persistence has its own asynchronous tests.
    monkeypatch.setattr(controller.measurement_persistence, "flush", lambda: True)
    monkeypatch.setattr(
        controller.measurement_persistence,
        "load",
        lambda _studies, ready: ready(),
    )

    delivered: list[list] = []
    controller.studies_loaded.connect(delivered.append)

    controller.open_folder(tmp_path)

    qtbot.waitUntil(lambda: len(delivered) == 1, timeout=30_000)
    qtbot.waitUntil(lambda: not controller._live_workers, timeout=5_000)
    assert delivered == [[]]
    assert controller._scan_started_at is None


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks: list = []

    def connect(self, callback, *_args) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in tuple(self.callbacks):
            callback(*args)


class _FakeSpeckleWorker:
    last: _FakeSpeckleWorker | None = None

    def __init__(self, **_kwargs) -> None:
        self.signals = SimpleNamespace(finished=_FakeSignal(), error=_FakeSignal())
        self.auto_delete = True
        _FakeSpeckleWorker.last = self

    def setAutoDelete(self, enabled: bool) -> None:  # noqa: N802 - Qt API
        self.auto_delete = enabled


class _RecordingPool:
    def __init__(self) -> None:
        self.started: list[object] = []

    def start(self, worker: object) -> None:
        self.started.append(worker)


def test_speckle_worker_is_retained_until_queued_result(monkeypatch, tmp_path) -> None:
    from echo_personal_tool.application.workers import speckle_worker

    pool = _RecordingPool()
    controller = AppController(thread_pool=pool)  # type: ignore[arg-type]
    controller._frame_cache.load(tmp_path / "cine.dcm", np.zeros((3, 32, 32), dtype=np.uint8))
    monkeypatch.setattr(speckle_worker, "SpeckleTrackingWorker", _FakeSpeckleWorker)

    controller.run_speckle_tracking(
        Contour(
            phase="ED",
            points=[(8.0, 24.0), (16.0, 6.0), (24.0, 24.0)],
        )
    )

    worker = _FakeSpeckleWorker.last
    assert worker is not None
    assert pool.started == [worker]
    assert worker.auto_delete is False
    assert worker in controller._live_workers

    worker.signals.error.emit("tracking failed")

    assert worker not in controller._live_workers
