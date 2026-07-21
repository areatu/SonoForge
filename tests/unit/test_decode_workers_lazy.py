"""Tests for lazy decode: first_frame_only in DicomDecodeWorker and VideoDecodeWorker."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
pytestmark = pytest.mark.gui
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.application.workers.dicom_decode_worker import DicomDecodeWorker
from echo_personal_tool.application.workers.video_decode_worker import VideoDecodeWorker
from tests.fixtures.generate_synthetic_dicom import write_synthetic_multiframe_dicom
from tests.fixtures.generate_synthetic_media import write_synthetic_mp4

pytest.importorskip("pytestqt")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_dicom_decode_worker_first_frame_only(qapp: QApplication, qtbot, tmp_path: Path) -> None:
    """first_frame_only=True: emits first_frame_ready, does NOT emit finished."""
    path = tmp_path / "multi.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=10, rows=16, cols=16)
    parent = QWidget()

    first_frames: list = []
    finished_events: list = []
    failed_events: list = []

    worker = DicomDecodeWorker(path, request_id=1, parent=parent, first_frame_only=True)
    worker.signals.first_frame_ready.connect(lambda rid, p, f: first_frames.append(f))
    worker.signals.finished.connect(lambda rid, p, f: finished_events.append(f))
    worker.signals.failed.connect(lambda rid, msg: failed_events.append(msg))

    QThreadPool.globalInstance().start(worker)
    qtbot.waitUntil(lambda: len(first_frames) == 1 or len(failed_events) == 1, timeout=10000)

    assert len(first_frames) == 1
    assert first_frames[0].shape == (16, 16)
    assert finished_events == []
    assert failed_events == []


def test_dicom_decode_worker_full_decode(qapp: QApplication, qtbot, tmp_path: Path) -> None:
    """first_frame_only=False (default): emits both first_frame_ready and finished."""
    path = tmp_path / "multi.dcm"
    write_synthetic_multiframe_dicom(path, frame_count=5, rows=16, cols=16)
    parent = QWidget()

    first_frames: list = []
    finished_events: list = []

    worker = DicomDecodeWorker(path, request_id=2, parent=parent)
    worker.signals.first_frame_ready.connect(lambda rid, p, f: first_frames.append(f))
    worker.signals.finished.connect(lambda rid, p, f: finished_events.append(f))

    QThreadPool.globalInstance().start(worker)
    qtbot.waitUntil(lambda: len(finished_events) == 1, timeout=10000)

    assert len(first_frames) == 1
    assert len(finished_events) == 1
    assert isinstance(finished_events[0], np.ndarray)
    assert finished_events[0].shape[0] == 5


def test_video_decode_worker_first_frame_only(qapp: QApplication, qtbot, tmp_path: Path) -> None:
    """first_frame_only=True: emits first_frame_ready, does NOT emit finished."""
    path = tmp_path / "clip.mp4"
    write_synthetic_mp4(path, frame_count=10, width=20, height=16)
    parent = QWidget()

    first_frames: list = []
    finished_events: list = []
    failed_events: list = []

    worker = VideoDecodeWorker(path, request_id=3, parent=parent, first_frame_only=True)
    worker.signals.first_frame_ready.connect(lambda rid, p, f: first_frames.append(f))
    worker.signals.finished.connect(lambda rid, p, f: finished_events.append(f))
    worker.signals.failed.connect(lambda rid, msg: failed_events.append(msg))

    QThreadPool.globalInstance().start(worker)
    qtbot.waitUntil(lambda: len(first_frames) == 1 or len(failed_events) == 1, timeout=10000)

    assert len(first_frames) == 1
    assert first_frames[0].shape == (16, 20, 3)
    assert finished_events == []
    assert failed_events == []


def test_video_decode_worker_full_decode(qapp: QApplication, qtbot, tmp_path: Path) -> None:
    """first_frame_only=False (default): emits both first_frame_ready and finished."""
    path = tmp_path / "clip.mp4"
    write_synthetic_mp4(path, frame_count=5, width=20, height=16)
    parent = QWidget()

    first_frames: list = []
    finished_events: list = []

    worker = VideoDecodeWorker(path, request_id=4, parent=parent)
    worker.signals.first_frame_ready.connect(lambda rid, p, f: first_frames.append(f))
    worker.signals.finished.connect(lambda rid, p, f: finished_events.append(f))

    QThreadPool.globalInstance().start(worker)
    qtbot.waitUntil(lambda: len(finished_events) == 1, timeout=10000)

    assert len(first_frames) == 1
    assert len(finished_events) == 1
    assert isinstance(finished_events[0], np.ndarray)
    assert finished_events[0].shape[0] == 5
