"""Unit tests for DicomDecodeWorker."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers.dicom_decode_worker import (
    DicomDecodeSignals,
    DicomDecodeWorker,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ── Signals ────────────────────────────────────────────────────────


class TestDicomDecodeSignals:
    def test_has_required_signals(self):
        signals = DicomDecodeSignals()
        assert hasattr(signals, "first_frame_ready")
        assert hasattr(signals, "progress")
        assert hasattr(signals, "finished")
        assert hasattr(signals, "failed")


# ── Construction ──────────────────────────────────────────────────


class TestDicomDecodeWorkerConstruction:
    def test_init_defaults(self):
        worker = DicomDecodeWorker(Path("/tmp/src.dcm"), request_id=1)
        assert worker._path == Path("/tmp/src.dcm")
        assert worker._request_id == 1
        assert worker._first_frame_only is False
        assert worker.autoDelete() is True

    def test_first_frame_only(self):
        worker = DicomDecodeWorker(Path("/tmp/src.dcm"), request_id=2, first_frame_only=True)
        assert worker._first_frame_only is True


# ── run ────────────────────────────────────────────────────────────


class TestDicomDecodeWorkerRun:
    @patch("echo_personal_tool.application.workers.dicom_decode_worker.get_thread_dicom_session")
    def test_full_decode(self, mock_get_session):
        session = MagicMock()
        frame0 = np.zeros((16, 16), dtype=np.uint8)
        all_frames = np.zeros((5, 16, 16), dtype=np.uint8)
        session.decode_first_frame.return_value = frame0
        session.decode_all_frames.return_value = all_frames
        session.frame_count = 5
        mock_get_session.return_value = session

        worker = DicomDecodeWorker(Path("/tmp/src.dcm"), request_id=10)
        first_frames = []
        finished_events = []
        progress_events = []
        worker.signals.first_frame_ready.connect(lambda rid, p, f: first_frames.append((rid, f)))
        worker.signals.finished.connect(lambda rid, p, f: finished_events.append((rid, f)))
        worker.signals.progress.connect(lambda c, t: progress_events.append((c, t)))

        worker.run()

        assert len(first_frames) == 1
        assert first_frames[0] == (10, frame0)
        assert len(finished_events) == 1
        assert finished_events[0][0] == 10
        assert progress_events == [(5, 5)]

    @patch("echo_personal_tool.application.workers.dicom_decode_worker.get_thread_dicom_session")
    def test_first_frame_only(self, mock_get_session):
        session = MagicMock()
        frame0 = np.zeros((16, 16), dtype=np.uint8)
        session.decode_first_frame.return_value = frame0
        session.frame_count = 10
        mock_get_session.return_value = session

        worker = DicomDecodeWorker(Path("/tmp/src.dcm"), request_id=20, first_frame_only=True)
        first_frames = []
        finished_events = []
        progress_events = []
        worker.signals.first_frame_ready.connect(lambda rid, p, f: first_frames.append(f))
        worker.signals.finished.connect(lambda rid, p, f: finished_events.append(f))
        worker.signals.progress.connect(lambda c, t: progress_events.append((c, t)))

        worker.run()

        assert len(first_frames) == 1
        assert finished_events == []
        assert progress_events == [(10, 10)]
        session.decode_all_frames.assert_not_called()

    @patch("echo_personal_tool.application.workers.dicom_decode_worker.get_thread_dicom_session")
    def test_exception_emits_failed(self, mock_get_session):
        session = MagicMock()
        session.open.side_effect = OSError("file not found")
        mock_get_session.return_value = session

        worker = DicomDecodeWorker(Path("/tmp/bad.dcm"), request_id=30)
        failed = []
        worker.signals.failed.connect(lambda rid, msg: failed.append((rid, msg)))

        worker.run()

        assert len(failed) == 1
        assert failed[0][0] == 30
        assert "file not found" in failed[0][1]

    @patch("echo_personal_tool.application.workers.dicom_decode_worker.get_thread_dicom_session")
    def test_decode_failure_emits_failed(self, mock_get_session):
        session = MagicMock()
        session.open.return_value = None
        session.decode_first_frame.side_effect = OSError("corrupt data")
        mock_get_session.return_value = session

        worker = DicomDecodeWorker(Path("/tmp/corrupt.dcm"), request_id=40)
        failed = []
        worker.signals.failed.connect(lambda rid, msg: failed.append(msg))

        worker.run()

        assert len(failed) == 1
        assert "corrupt data" in failed[0]
