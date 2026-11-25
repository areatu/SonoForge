"""Controller regressions: fusion run and LA-assist publication ownership (#552).

The segmentation slice (#609) protected LV/LA auto-segmentation with a single-use
owner; this closes the two paths it explicitly left open: temporal fusion (a
multi-worker run whose late neighbor callbacks could contaminate a newer run or
publish into a switched study) and the LA manual-assist delivery (which also
carried the OnnxWorker ndarray contract mismatch recorded in #609).

Fusion is driven through the public ``request_auto_segment`` path with a synthetic
manifest; frames and masks are synthetic. Offscreen Qt does not replace native
GUI acceptance.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from echo_personal_tool.application import app_controller as ac
from echo_personal_tool.domain.models import Contour
from tests.unit.test_auto_segment_controller import _FakeSignal, _prepared_controller

pytestmark = pytest.mark.gui


class _FakeFrameLoaderWorker:
    """Stands in for FrameLoaderWorker in fusion neighbor loads."""

    def __init__(self, path, frame_index=0, media_format="dicom", parent=None, **kwargs) -> None:
        self.path = path
        self.frame_index = frame_index
        self.decode_gate = None
        self.priority = None
        self.signals = SimpleNamespace(
            finished=_FakeSignal(),
            batch_finished=_FakeSignal(),
            failed=_FakeSignal(),
            cancelled=_FakeSignal(),
        )

    def setAutoDelete(self, v: bool) -> None:
        pass


class _FakeOnnxWorker:
    last: _FakeOnnxWorker | None = None

    def __init__(self, frame, *args, **kwargs) -> None:
        self.frame = np.ascontiguousarray(frame)
        _FakeOnnxWorker.last = self
        self.signals = SimpleNamespace(
            finished=_FakeSignal(),
            failed=_FakeSignal(),
            timed_out=_FakeSignal(),
        )

    def setAutoDelete(self, v: bool) -> None:
        pass


@pytest.fixture
def prepared(qapp, monkeypatch, synthetic_dicom_path):
    """Controller with faked workers and an enabled temporal-fusion manifest."""
    monkeypatch.setattr("echo_personal_tool.application.app_controller.FrameLoaderWorker", _FakeFrameLoaderWorker)
    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller._load_manifest",
        lambda models_dir: {"temporal_fusion": {"enabled": True, "window": 3}},
    )
    controller, pool, _, instance, _ = _prepared_controller(monkeypatch, synthetic_dicom_path)
    # OnnxWorker is re-patched after _prepared_controller (it installs its own fake).
    monkeypatch.setattr("echo_personal_tool.application.app_controller.OnnxWorker", _FakeOnnxWorker)
    # Display a realistic 64x48 frame (the gate-passing mask geometry of the
    # sibling auto-segment tests) instead of the 8x8 stub pixels.
    controller._pending_load_id = 2
    controller._on_frame_loaded(2, instance.path, 0, _mask(seed=0) * 140)
    controller.set_simpson_workflow_context(phase="ED", view="A4C", chamber="LV")
    return controller, pool, instance


def _mask(*, seed: int = 0) -> np.ndarray:
    """64x48 circle mask — the geometry that passes the LV quality gate."""
    ys, xs = np.ogrid[:64, :48]
    return ((ys - 32) ** 2 + (xs - 24) ** 2 <= 18**2 + seed).astype(np.uint8)


def _capture_tickets(monkeypatch) -> list:
    """Record every FusionTicket the controller opens, in order."""
    tickets: list = []
    real_begin = ac.begin_fusion_run

    def spy(controller_, **kwargs):
        ticket = real_begin(controller_, **kwargs)
        tickets.append(ticket)
        return ticket

    monkeypatch.setattr(ac, "begin_fusion_run", spy)
    return tickets


def _start_fusion(controller, pool) -> None:
    """Start a fusion run through the public auto-segment path."""
    controller.request_auto_segment()
    workers = _onnx_workers(pool)
    assert len(workers) == 1
    workers[0].signals.finished.emit(_mask(seed=1))
    assert controller._fusion_in_progress


def _neighbors(pool) -> list[_FakeFrameLoaderWorker]:
    return [worker for worker in pool.started if isinstance(worker, _FakeFrameLoaderWorker)]


def _onnx_workers(pool) -> list[_FakeOnnxWorker]:
    return [worker for worker in pool.started if isinstance(worker, _FakeOnnxWorker)]


def _drive_all_neighbors(controller, pool) -> None:
    """Deliver every neighbor: frame pixels -> ONNX mask until the run completes."""
    for _ in range(8):
        loads = _neighbors(pool)
        if not loads:
            return
        known = set(_onnx_workers(pool))
        delivered = 0
        for worker in loads:
            if worker.frame_index not in controller._fusion_processed:
                worker.signals.finished.emit(_mask(seed=worker.frame_index) * 100)
                delivered += 1
        for worker in _onnx_workers(pool):
            if worker not in known:
                worker.signals.finished.emit(_mask(seed=2))
        if not delivered:
            return


# ── Temporal fusion: late callbacks of a dead run ────────────────────────────


@pytest.mark.parametrize("change", ["reset", "reload", "close", "calibration", "contour_aba"])
def test_late_neighbor_after_context_change_never_segments_or_publishes(prepared, monkeypatch, change):
    controller, pool, instance = prepared
    tickets = _capture_tickets(monkeypatch)
    _start_fusion(controller, pool)
    from echo_personal_tool.application.composition import fusion_jobs_of

    ticket = tickets[-1]
    if change == "reset":
        controller.reset_measurements_and_calibration()
    elif change == "reload":
        controller.load_instance(instance)
    elif change == "close":
        controller.load_pre_scanned_studies([])
    elif change == "calibration":
        assert controller.on_manual_calibration((0.9, 0.9))
    else:
        other = Contour(
            phase="ES",
            view="A4C",
            chamber="LV",
            points=[(4.0, 9.0), (16.0, 9.0)],
            sop_instance_uid=instance.sop_instance_uid,
            frame_index=2,
        )
        controller.on_contours_changed([other])

    assert not fusion_jobs_of(controller).owns(ticket)
    baseline = list(controller.state_manager.snapshot.contours)
    started_onnx = len(_onnx_workers(pool))
    for worker in _neighbors(pool):
        worker.signals.finished.emit(_mask(seed=3) * 100)
    # The dead run's pixels never reach the segmenter and never publish.
    assert len(_onnx_workers(pool)) == started_onnx
    assert controller._fusion_masks == {}
    assert controller._fusion_in_progress is False
    assert list(controller.state_manager.snapshot.contours) == baseline


def test_superseded_run_callback_cannot_contaminate_the_new_run(prepared, monkeypatch):
    controller, pool, instance = prepared
    tickets = _capture_tickets(monkeypatch)
    _start_fusion(controller, pool)
    old_ticket = tickets[-1]
    old_loads = _neighbors(pool)
    from echo_personal_tool.application.composition import fusion_jobs_of

    # A newer run for the same chamber supersedes the old ticket.
    controller._segment_in_progress = False
    controller.request_auto_segment()
    _onnx_workers(pool)[-1].signals.finished.emit(_mask(seed=1))
    new_ticket = tickets[-1]
    assert new_ticket.request_id > old_ticket.request_id
    jobs = fusion_jobs_of(controller)
    assert jobs.owns(new_ticket) and not jobs.owns(old_ticket)
    new_loads = [worker for worker in _neighbors(pool) if worker not in old_loads]
    assert new_loads

    # The old run's late neighbor pixels arrive: they must not enter the new run.
    anchor_masks = dict(controller._fusion_masks)
    old_loads[0].signals.finished.emit(_mask(seed=9) * 100)
    assert controller._fusion_masks == anchor_masks

    # ...while the new run's own neighbors keep working.
    started = len(_onnx_workers(pool))
    new_loads[0].signals.finished.emit(_mask(seed=4) * 100)
    assert len(_onnx_workers(pool)) > started


def test_calibration_change_mid_run_revokes_publication(prepared, monkeypatch):
    controller, pool, instance = prepared
    _capture_tickets(monkeypatch)
    _start_fusion(controller, pool)

    # One neighbor completes while the context is intact.
    loads = _neighbors(pool)
    loads[0].signals.finished.emit(_mask(seed=5) * 100)
    onnx = _onnx_workers(pool)
    onnx[-1].signals.finished.emit(_mask(seed=6))
    assert 1 in controller._fusion_processed

    # The user recalibrates: the run may still finish, but must not publish.
    assert controller.on_manual_calibration((0.9, 0.9))
    before = list(controller.state_manager.snapshot.contours)
    _drive_all_neighbors(controller, pool)
    assert list(controller.state_manager.snapshot.contours) == before


def test_current_run_publishes_fused_contour_once(prepared, monkeypatch):
    controller, pool, instance = prepared
    tickets = _capture_tickets(monkeypatch)
    _start_fusion(controller, pool)
    from echo_personal_tool.application.composition import fusion_jobs_of

    ticket = tickets[-1]
    before = len(controller.state_manager.snapshot.contours)

    _drive_all_neighbors(controller, pool)

    assert not controller._fusion_in_progress
    contours = controller.state_manager.snapshot.contours
    assert len(contours) == before
    fused = contours[-1]
    assert (fused.phase, fused.view, fused.chamber) == ("ED", "A4C", "LV")
    # A consumed ticket cannot publish twice.
    assert not fusion_jobs_of(controller).owns(ticket)
    for worker in _neighbors(pool):
        worker.signals.finished.emit(_mask(seed=12) * 100)
    assert len(controller.state_manager.snapshot.contours) == before


# ── LA assist: ndarray contract and delivery ticket ──────────────────────────


@pytest.fixture
def assist_controller(prepared, monkeypatch):
    """Prepared controller whose LA segmenter resolves through a stub manifest."""
    controller, pool, _ = prepared
    monkeypatch.setattr("echo_personal_tool.infrastructure.onnx_engine._load_manifest", lambda models_dir: {})
    monkeypatch.setattr(
        "echo_personal_tool.infrastructure.onnx_engine._resolve_model_path",
        lambda models_dir, manifest, manifest_section="inference": Path(__file__),
    )
    return controller, pool


def test_la_assist_accepts_ndarray_payload_and_emits_once(assist_controller):
    controller, pool = assist_controller
    emitted: list = []
    controller.la_assist_contour_ready.connect(emitted.append)

    controller.request_la_assist_for_manual(
        frame_index=2,
        user_septal=(10.0, 8.0),
        user_lateral=(10.0, 24.0),
        user_apex=(24.0, 16.0),
    )
    worker = _FakeOnnxWorker.last
    assert worker is not None
    # OnnxWorker emits the mask ndarray directly; the old dict contract was dead code.
    worker.signals.finished.emit(_mask(seed=0))
    assert len(emitted) == 1
    assert emitted[0].chamber == "LA"
    assert emitted[0].frame_index == 2 and emitted[0].source == "manual"
    # One terminal delivery: a second emission is rejected by the consumed ticket.
    worker.signals.finished.emit(_mask(seed=7))
    assert len(emitted) == 1


def test_la_assist_stale_request_is_never_delivered(assist_controller):
    controller, pool = assist_controller
    emitted: list = []
    controller.la_assist_contour_ready.connect(emitted.append)

    controller.request_la_assist_for_manual(
        frame_index=2, user_septal=(10.0, 8.0), user_lateral=(10.0, 24.0), user_apex=(24.0, 16.0)
    )
    worker = _FakeOnnxWorker.last
    assert worker is not None
    instance = controller._current_instance
    controller.load_instance(instance)  # switch/reload revokes the pending proposal
    worker.signals.finished.emit(_mask(seed=0))
    assert emitted == []
