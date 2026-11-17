"""Deterministic queue/cancellation acceptance for #553 (no vendor/GUI claims).

Real FrameLoaderWorker run loops and gate, controlled decoder cost. Events, not
sleeps, place scrub/switch requests inside an in-flight native-frame boundary.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from PySide6.QtCore import Qt

from echo_personal_tool.application.decode_gate import DecodeGate, DecodePriority
from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker

pytestmark = pytest.mark.gui
_DIRECT = Qt.ConnectionType.DirectConnection


def _worker(path, gate, *, start=0, size=0, priority=DecodePriority.PLAYBACK):
    worker = FrameLoaderWorker(path, frame_index=start, batch_size=size, total_frames=512)
    worker.decode_gate = gate
    worker.priority = priority
    worker.estimated_frame_bytes = 512 * 512 * 2
    return worker


def test_scrub_preempts_playback_at_next_frame_boundary(qapp, tmp_path, monkeypatch):
    """200 stale targets coalesce; newest frame precedes the rest of the batch."""
    gate = DecodeGate()
    entered, resume = threading.Event(), threading.Event()
    decoded = []
    pixel = np.zeros((8, 8), dtype=np.uint16)

    class Session:
        frame_count = 512

        def open(self, path):
            pass

        def decode_single_frame(self, index):
            decoded.append(index)
            if index == 0:
                entered.set()
                assert resume.wait(10), "producer did not release in-flight frame"
            return pixel

    monkeypatch.setattr(
        "echo_personal_tool.application.workers.frame_loader_worker.get_thread_dicom_session",
        lambda path: Session(),
    )
    path = tmp_path / "cine.dcm"
    owner = _worker(path, gate, size=30)
    targets, published, cancelled = [], [], []
    batches = []
    owner.signals.batch_finished.connect(batches.append, _DIRECT)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owner.run)
        try:
            assert entered.wait(10)
            started = time.perf_counter()
            for index in range(200):
                target = _worker(path, gate, start=100 + index, priority=DecodePriority.INTERACTIVE)
                target.signals.finished.connect(lambda pixels, i=index: published.append(i), _DIRECT)
                target.signals.cancelled.connect(lambda i=index: cancelled.append(i), _DIRECT)
                targets.append(target)  # retain Qt signal owners through hand-off
                target.run()
            producer_ms = (time.perf_counter() - started) * 1000
            stats = gate.stats()
            assert stats.parked_requests == 1
            assert stats.parked_frames == 1
            assert stats.pending_bytes == 512 * 512 * 2
            assert sorted(cancelled) == list(range(199))
        finally:
            resumed_at = time.perf_counter()
            resume.set()
        future.result(timeout=10)
    assert decoded == [0, 299, *range(1, 30)]
    assert published == [199]
    assert len(batches) == 1
    assert [index for index, _ in batches[0]] == list(range(30))
    assert gate.stats().parked_requests == 0
    assert not gate.is_busy(path)
    print(f"scrub producer={producer_ms:.3f}ms; resume-to-drain={(time.perf_counter() - resumed_at) * 1000:.3f}ms")


def test_tab_switch_cancels_running_and_parked_without_stale_publication(qapp, tmp_path, monkeypatch):
    """An independent file progresses while the old file is inside its decoder."""
    gate = DecodeGate()
    entered, resume = threading.Event(), threading.Event()
    decoded = []
    pixel = np.zeros((8, 8), dtype=np.uint16)
    old_path, new_path = tmp_path / "old.dcm", tmp_path / "new.dcm"

    class Session:
        frame_count = 512

        def __init__(self, path):
            self.path = path

        def open(self, path):
            pass

        def decode_single_frame(self, index):
            decoded.append((self.path, index))
            if self.path == old_path:
                entered.set()
                assert resume.wait(10)
            return pixel

    monkeypatch.setattr("echo_personal_tool.application.workers.frame_loader_worker.get_thread_dicom_session", Session)
    owner = _worker(old_path, gate, size=30)
    parked = _worker(old_path, gate, start=60, size=30)
    current = _worker(new_path, gate, priority=DecodePriority.INTERACTIVE)
    stale, published, cancelled = [], [], []
    owner.signals.batch_finished.connect(stale.append, _DIRECT)
    parked.signals.batch_finished.connect(stale.append, _DIRECT)
    current.signals.finished.connect(published.append, _DIRECT)
    owner.signals.cancelled.connect(lambda: cancelled.append("owner"), _DIRECT)
    parked.signals.cancelled.connect(lambda: cancelled.append("parked"), _DIRECT)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(owner.run)
        try:
            assert entered.wait(10)
            parked.run()
            assert gate.stats().parked_frames == 30
            started = time.perf_counter()
            owner.cancel()
            parked.cancel()
            owner.cancel()  # terminal notification must be idempotent
            parked.cancel()
            pool.submit(current.run).result(timeout=10)
            switch_ms = (time.perf_counter() - started) * 1000
            assert len(published) == 1
            assert sorted(cancelled) == ["owner", "parked"]
            assert gate.stats().pending_bytes == 0
        finally:
            resume.set()
        future.result(timeout=10)
    assert decoded == [(old_path, 0), (new_path, 0)]
    assert stale == []
    assert not gate.is_busy(old_path)
    assert not gate.is_busy(new_path)
    print(f"switch cancel-to-new-frame={switch_ms:.3f}ms (old decoder still blocked)")
