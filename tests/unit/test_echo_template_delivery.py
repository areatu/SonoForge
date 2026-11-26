"""Real queued ML.3 publication without a viewer or GPU."""

import multiprocessing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from echo_personal_tool.application.composition import bind_controller_services
from echo_personal_tool.application.segmentation_jobs import SegmentationJobs
from echo_personal_tool.application.template_segmentation_delivery import (
    connect_template_segmentation,
    request_template_segmentation,
)
from echo_personal_tool.application.workers.echo_template_worker import EchoTemplateWorker
from echo_personal_tool.domain.models.metadata import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from tests.unit.test_echo_template_core import decode

pytestmark = pytest.mark.gui


class Signals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    timed_out = Signal()


class StubWorker:
    def __init__(self):
        self.signals = Signals()

    def setAutoDelete(self, value):  # noqa: N802
        self.auto_delete = value


class Harness:
    def __init__(self):
        self._current_instance = InstanceMetadata(
            sop_instance_uid="sop",
            series_uid="series",
            modality="US",
            number_of_frames=2,
            pixel_spacing=(0.5, 0.5),
            frame_time_ms=33.0,
            series_description="synthetic",
        )
        state = ViewerState(self._current_instance, 0, 2, 33.0, False)
        self._state_manager = SimpleNamespace(snapshot=state)
        self._study_load_generation, self._loaded_frame_index = 1, 0
        self._segment_in_progress = True
        self._thread_pool = SimpleNamespace(start=lambda worker: None)
        self.workers = []
        self._current_frame_pixels = np.zeros((200, 200))
        self.status_message = SimpleNamespace(emit=lambda message: None)
        bind_controller_services(
            self,
            SimpleNamespace(segmentation_jobs=SegmentationJobs(), capabilities=SimpleNamespace(ai_segmentation=True)),
        )

    def _resolve_study_uid(self):
        return "study"

    def _retain_worker(self, worker):
        self.workers.append(worker)

    def _release_worker(self, worker, *_payload):
        if worker in self.workers:
            self.workers.remove(worker)

    def _resolve_pixel_spacing(self, state):
        return (0.5, 0.5), None

    def on_contours_changed(self, contours):
        self._state_manager.snapshot = replace(self._state_manager.snapshot, contours=tuple(contours))


@pytest.fixture
def core_app(qapp):
    return qapp


@pytest.mark.parametrize(
    "change", ["none", "frame", "calibration", "contours", "instance", "generation", "loaded_frame"]
)
def test_real_queued_template_delivery_consumes_once_and_releases_stale(core_app, change):
    harness, worker = Harness(), StubWorker()
    received, errors = [], []
    connect_template_segmentation(harness, worker, received.append, errors.append, lambda: errors.append("timeout"))
    assert harness.workers == [worker] and not worker.auto_delete
    worker.signals.finished.emit(decode())
    state = harness._state_manager.snapshot
    if change == "frame":
        harness._state_manager.snapshot = replace(state, current_frame_index=1)
    if change == "calibration":
        harness._state_manager.snapshot = replace(state, manual_pixel_spacing=(1.0, 1.0))
    if change == "contours":
        harness._state_manager.snapshot = replace(state, contours=decode().contours)
    if change == "instance":
        harness._current_instance = replace(harness._current_instance, sop_instance_uid="other")
    if change == "generation":
        harness._study_load_generation += 1
    if change == "loaded_frame":
        harness._loaded_frame_index = 1
    core_app.processEvents()
    worker.signals.failed.emit("late")
    core_app.processEvents()
    assert not harness.workers and not harness._segment_in_progress and not errors
    assert len(received) == (1 if change == "none" else 0)
    if received:
        assert all(c.review_pending and c.sop_instance_uid == "sop" for c in received[0])


def test_explicit_request_publishes_drafts_but_never_replaces_confirmed_inputs(core_app, monkeypatch, tmp_path):
    harness, worker = Harness(), StubWorker()
    harness._segment_in_progress = False
    monkeypatch.setattr(
        "echo_personal_tool.application.workers.echo_template_worker.EchoTemplateWorker", lambda *a, **k: worker
    )
    args = dict(models_dir=tmp_path, phase="ED", view="A4C", sector_mask=np.ones((200, 200), bool))
    assert request_template_segmentation(harness, **args)
    worker.signals.finished.emit(decode())
    core_app.processEvents()
    assert len(harness._state_manager.snapshot.contours) == 3
    assert all(c.review_pending for c in harness._state_manager.snapshot.contours)
    accepted = tuple(replace(c, review_pending=False) for c in harness._state_manager.snapshot.contours)
    harness._state_manager.snapshot = replace(harness._state_manager.snapshot, contours=accepted)
    assert not request_template_segmentation(harness, **args)
    assert harness._state_manager.snapshot.contours == accepted


@pytest.mark.parametrize("outcome", ["success", "error", "timeout"])
def test_worker_copies_inputs_and_uses_static_terminal_tokens(monkeypatch, outcome):
    frame = np.zeros((64, 64), np.uint8)
    mask = np.ones((64, 64), bool)
    worker = EchoTemplateWorker(
        frame, models_dir=Path("."), phase="ED", frame_index=0, pixel_spacing=(1.0, 1.0), sector_mask=mask
    )
    frame[:], mask[:] = 100, False
    captured = []
    prediction = decode()

    def submit(fn, args):
        captured.append(args)

        def get(timeout):
            if outcome == "error":
                raise RuntimeError("private-patient-name")
            if outcome == "timeout":
                raise multiprocessing.TimeoutError()
            return prediction

        return SimpleNamespace(get=get)

    monkeypatch.setattr(
        "echo_personal_tool.application.workers.echo_template_worker._get_pool",
        lambda: SimpleNamespace(apply_async=submit),
    )
    terminals = []
    worker.signals.finished.connect(terminals.append)
    worker.signals.failed.connect(terminals.append)
    worker.signals.timed_out.connect(lambda: terminals.append("timeout"))
    worker.run()
    assert len(terminals) == 1
    assert terminals[0] == {"success": prediction, "error": "template_inference", "timeout": "timeout"}[outcome]
    assert not captured[0][0].any() and captured[0][5].all()
