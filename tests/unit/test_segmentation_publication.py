"""Controller and real queued-signal regressions for segmentation ownership."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from echo_personal_tool.domain.models.contour import Contour
from tests.unit.test_auto_segment_controller import _prepared_controller

pytestmark = pytest.mark.gui


@pytest.fixture
def prepared(qapp, monkeypatch, synthetic_dicom_path):
    controller, pool, _, instance, pixels = _prepared_controller(monkeypatch, synthetic_dicom_path)
    controller.set_simpson_workflow_context(phase="ED", view="A4C", chamber="LV")
    return controller, pool, instance, pixels


def _start(controller, pool, monkeypatch, kind):
    finished, errors, timeouts = [], [], []
    handler = "_on_auto_segment_finished" if kind == "LV" else "_on_la_auto_segment_finished"
    monkeypatch.setattr(controller, handler, lambda *args: finished.append(args))
    monkeypatch.setattr(controller, "_on_auto_segment_failed", lambda *args: errors.append(args))
    monkeypatch.setattr(controller, "_on_auto_segment_timed_out", lambda *args: timeouts.append(args))
    if kind == "LV":
        controller.request_auto_segment()
    else:
        monkeypatch.setattr(controller, "_la_segmenter_available", lambda: True)
        controller.request_la_auto_segment()
    return pool.started[-1], finished, errors, timeouts


@pytest.mark.parametrize("kind", ["LV", "LA"])
def test_current_job_publishes_once_and_has_immutable_frame(prepared, monkeypatch, kind):
    controller, pool, _, pixels = prepared
    worker, finished, errors, timeouts = _start(controller, pool, monkeypatch, kind)
    before = worker.frame.copy()
    pixels[:] = 0
    assert np.array_equal(worker.frame, before)
    worker.signals.finished.emit(np.ones((8, 8), dtype=np.uint8))
    worker.signals.failed.emit("obsolete")
    worker.signals.timed_out.emit()
    assert len(finished) == 1 and not errors and not timeouts
    assert not controller._segment_in_progress
    assert worker not in controller._live_workers


@pytest.mark.parametrize("kind", ["LV", "LA"])
@pytest.mark.parametrize(
    "change", ["frame_aba", "calibration_aba", "contour_aba", "workflow_aba", "reset", "close", "reload"]
)
def test_changed_context_revokes_old_success_failure_and_timeout(prepared, monkeypatch, kind, change):
    controller, pool, instance, _ = prepared
    contour = Contour("ED", frame_index=0, points=[(0.0, 0.0), (1.0, 1.0)], sop_instance_uid=instance.sop_instance_uid)
    controller.on_contours_changed([contour])
    worker, finished, errors, timeouts = _start(controller, pool, monkeypatch, kind)
    if change == "frame_aba":
        controller.state_manager.set_frame(1)
        controller.state_manager.set_frame(0)
    elif change == "calibration_aba":
        assert controller.on_manual_calibration((0.3, 0.3))
        controller.clear_manual_calibration()
    elif change == "contour_aba":
        controller.on_contours_changed([replace(contour, points=[(9.0, 9.0), (1.0, 1.0)])])
        controller.on_contours_changed([contour])
    elif change == "workflow_aba":
        controller.set_simpson_workflow_context(phase="ES", view="A4C", chamber="LV")
        controller.set_simpson_workflow_context(phase="ED", view="A4C", chamber="LV")
    elif change == "reset":
        controller.reset_measurements_and_calibration()
    elif change == "close":
        controller.load_pre_scanned_studies([])
    else:
        controller.load_instance(instance)
    worker.signals.failed.emit("old")
    worker.signals.finished.emit(np.ones((8, 8), dtype=np.uint8))
    worker.signals.timed_out.emit()
    assert not finished and not errors and not timeouts
    assert worker not in controller._live_workers


@pytest.mark.parametrize("kind", ["LV", "LA"])
def test_late_old_terminal_cannot_clear_new_job_busy_flag(prepared, monkeypatch, kind):
    controller, pool, instance, pixels = prepared
    old, _, errors, timeouts = _start(controller, pool, monkeypatch, kind)
    controller.load_instance(instance)
    controller._pending_load_id = 123
    controller._on_frame_loaded(123, instance.path, 0, pixels)
    new, finished, _, _ = _start(controller, pool, monkeypatch, kind)
    assert new is not old and controller._segment_in_progress
    old.signals.failed.emit("old")
    assert controller._segment_in_progress and not errors and not timeouts
    new.signals.finished.emit(np.ones((8, 8), dtype=np.uint8))
    assert len(finished) == 1 and not controller._segment_in_progress


@pytest.mark.parametrize("terminal", ["finished", "failed", "timed_out"])
def test_real_queued_completion_rechecks_state_at_delivery(prepared, monkeypatch, qtbot, terminal):
    controller, pool, _, _ = prepared

    class Signals(QObject):
        finished = Signal(object)
        failed = Signal(str)
        timed_out = Signal()

    class Worker:
        def __init__(self, *args, **kwargs):
            self.signals = Signals()

        def setAutoDelete(self, enabled):  # noqa: N802 - Qt API
            pass

    monkeypatch.setattr("echo_personal_tool.application.app_controller.OnnxWorker", Worker)
    worker, finished, errors, timeouts = _start(controller, pool, monkeypatch, "LV")
    if terminal == "finished":
        worker.signals.finished.emit(np.ones((8, 8), dtype=np.uint8))
    elif terminal == "failed":
        worker.signals.failed.emit("inference")
    else:
        worker.signals.timed_out.emit()
    assert controller.on_manual_calibration((0.3, 0.3))
    qtbot.waitUntil(lambda: worker not in controller._live_workers)
    assert not finished and not errors and not timeouts
    assert not controller._segment_in_progress


@pytest.mark.parametrize("kind", ["LV", "LA"])
def test_stale_actual_error_does_not_clear_new_request_or_emit_status(prepared, monkeypatch, kind):
    controller, pool, instance, pixels = prepared
    monkeypatch.setattr(controller, "_la_segmenter_available", lambda: True)
    start = controller.request_auto_segment if kind == "LV" else controller.request_la_auto_segment
    start()
    old = pool.started[-1]
    controller.load_instance(instance)
    controller._pending_load_id = 123
    controller._on_frame_loaded(123, instance.path, 0, pixels)
    start()
    new = pool.started[-1]
    assert old is not new and controller._segment_in_progress
    messages = []
    controller.status_message.connect(messages.append)
    old.signals.failed.emit("inference")
    assert controller._segment_in_progress and not messages
    new.signals.failed.emit("inference")
    assert not controller._segment_in_progress and len(messages) == 1


def test_in_place_contour_change_is_checked_again_at_publication(prepared, monkeypatch):
    controller, pool, instance, _ = prepared
    contour = Contour("ED", frame_index=0, points=[(0.0, 0.0), (1.0, 1.0)], sop_instance_uid=instance.sop_instance_uid)
    controller.on_contours_changed([contour])
    worker, finished, _, _ = _start(controller, pool, monkeypatch, "LV")
    contour.points[0] = (4.0, 4.0)  # mutation without a state signal
    worker.signals.finished.emit(np.ones((8, 8), dtype=np.uint8))
    assert not finished and not controller._segment_in_progress


def test_current_real_result_remains_ai_draft(prepared, monkeypatch):
    from tests.unit.test_auto_segment_controller import _circle_mask

    controller, pool, instance, _ = prepared
    controller._current_frame_pixels = np.zeros((64, 48), dtype=np.uint8)
    monkeypatch.setattr(controller, "_should_auto_refine_after_segment", lambda: False)
    monkeypatch.setattr(controller, "_resolve_temporal_fusion_config", lambda: None)
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.explain_lv_auto_reject_reason", lambda *args: None
    )
    controller.request_auto_segment()
    worker = pool.started[-1]
    mask = _circle_mask(height=64, width=48, center_y=32, center_x=24, radius=18)
    worker.signals.finished.emit(mask)
    contours = controller.state_manager.snapshot.contours
    assert len(contours) == 1 and contours[0].source == "ai" and contours[0].review_pending
    assert contours[0].sop_instance_uid == instance.sop_instance_uid
    assert not controller._segment_in_progress


def test_delivery_adapter_independently_releases_stale_worker(prepared, qtbot):
    from echo_personal_tool.application.segmentation_delivery import connect_segmentation

    controller, pool, _, _ = prepared

    class Signals(QObject):
        finished = Signal(object)
        failed = Signal(str)
        timed_out = Signal()

    class Worker:
        def __init__(self):
            self.signals = Signals()

        def setAutoDelete(self, enabled):  # noqa: N802 - Qt API
            pass

    worker = Worker()
    received = []
    controller._segment_in_progress = True
    connect_segmentation(controller, worker, received.append, received.append, lambda: received.append("timeout"))
    assert pool.started[-1] is worker and worker in controller._live_workers
    worker.signals.failed.emit("inference")
    controller.state_manager.set_frame(1)
    qtbot.waitUntil(lambda: worker not in controller._live_workers)
    assert received == [] and not controller._segment_in_progress


def test_segmentation_ticket_does_not_invalidate_ste_ticket(prepared):
    from echo_personal_tool.application.analysis_jobs import analysis_basis
    from echo_personal_tool.application.composition import analysis_jobs_of, segmentation_jobs_of

    controller, _, _, _ = prepared
    basis = analysis_basis(
        controller.state_manager.snapshot,
        controller._current_instance,
        document_id=controller._resolve_study_uid(),
        generation=controller._study_load_generation,
    )
    ste = analysis_jobs_of(controller)
    ticket = ste.begin(basis)
    segmentation_jobs_of(controller).invalidate()
    assert ste.finish(ticket, basis)
