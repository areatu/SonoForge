"""Unit tests for VideoDecodeWorker."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers.video_decode_worker import (
    VideoDecodeSignals,
    VideoDecodeWorker,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ── Signals ────────────────────────────────────────────────────────


class TestVideoDecodeSignals:
    def test_has_required_signals(self):
        signals = VideoDecodeSignals()
        assert hasattr(signals, "first_frame_ready")
        assert hasattr(signals, "progress")
        assert hasattr(signals, "finished")
        assert hasattr(signals, "failed")


# ── Construction ──────────────────────────────────────────────────


class TestVideoDecodeWorkerConstruction:
    def test_init_defaults(self):
        worker = VideoDecodeWorker(Path("/tmp/src.mp4"), request_id=1)
        assert worker._path == Path("/tmp/src.mp4")
        assert worker._request_id == 1
        assert worker._first_frame_only is False
        assert worker.autoDelete() is True

    def test_first_frame_only(self):
        worker = VideoDecodeWorker(
            Path("/tmp/src.mp4"), request_id=2, first_frame_only=True
        )
        assert worker._first_frame_only is True


# ── run – full decode ─────────────────────────────────────────────


class TestVideoDecodeWorkerRun:
    @patch("echo_personal_tool.application.workers.video_decode_worker.to_bgr_uint8")
    def test_full_decode(self, mock_to_bgr):
        mock_cv2 = MagicMock()
        frames = [np.zeros((10, 20, 3), dtype=np.uint8) + i for i in range(4)]
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.return_value = 4
        cap.read.side_effect = [(True, f) for f in frames] + [(False, None)]
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        mock_to_bgr.side_effect = lambda f: np.ascontiguousarray(f[:, :, :3], dtype=np.uint8)

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            worker = VideoDecodeWorker(Path("/tmp/src.mp4"), request_id=42)
            first_frames = []
            finished_events = []
            progress_events = []
            worker.signals.first_frame_ready.connect(
                lambda rid, p, f: first_frames.append((rid, f))
            )
            worker.signals.finished.connect(
                lambda rid, p, f: finished_events.append((rid, f))
            )
            worker.signals.progress.connect(lambda c, t: progress_events.append((c, t)))

            worker.run()

            assert len(first_frames) == 1
            assert first_frames[0][0] == 42
            assert len(finished_events) == 1
            assert finished_events[0][0] == 42
            assert isinstance(finished_events[0][1], np.ndarray)
            assert finished_events[0][1].shape[0] == 4

    @patch("echo_personal_tool.application.workers.video_decode_worker.to_bgr_uint8")
    def test_first_frame_only(self, mock_to_bgr):
        mock_cv2 = MagicMock()
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.return_value = 10
        frame = np.zeros((10, 20, 3), dtype=np.uint8)
        cap.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        mock_to_bgr.return_value = np.ascontiguousarray(frame)

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            worker = VideoDecodeWorker(
                Path("/tmp/src.mp4"), request_id=5, first_frame_only=True
            )
            first_frames = []
            finished_events = []
            progress_events = []
            worker.signals.first_frame_ready.connect(
                lambda rid, p, f: first_frames.append(f)
            )
            worker.signals.finished.connect(
                lambda rid, p, f: finished_events.append(f)
            )
            worker.signals.progress.connect(lambda c, t: progress_events.append((c, t)))

            worker.run()

            assert len(first_frames) == 1
            assert finished_events == []
            assert progress_events == [(10, 10)]

    def test_cap_not_opened(self):
        mock_cv2 = MagicMock()
        cap = MagicMock()
        cap.isOpened.return_value = False
        mock_cv2.VideoCapture.return_value = cap

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            worker = VideoDecodeWorker(Path("/tmp/bad.mp4"), request_id=1)
            failed = []
            worker.signals.failed.connect(lambda rid, msg: failed.append((rid, msg)))

            worker.run()

            assert len(failed) == 1
            assert failed[0][0] == 1
            assert "Cannot open video" in failed[0][1]

    def test_zero_frame_count(self):
        mock_cv2 = MagicMock()
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.return_value = 0
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 7

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            worker = VideoDecodeWorker(Path("/tmp/empty.mp4"), request_id=1)
            failed = []
            worker.signals.failed.connect(lambda rid, msg: failed.append(msg))

            worker.run()

            assert len(failed) == 1
            assert "Cannot determine frame count" in failed[0]

    def test_first_frame_read_failure(self):
        mock_cv2 = MagicMock()
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.return_value = 5
        cap.read.return_value = (False, None)
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 7

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            worker = VideoDecodeWorker(Path("/tmp/bad.mp4"), request_id=1)
            failed = []
            worker.signals.failed.connect(lambda rid, msg: failed.append(msg))

            worker.run()

            assert len(failed) == 1
            assert "Cannot read first frame" in failed[0]

    @patch("echo_personal_tool.application.workers.video_decode_worker.to_bgr_uint8")
    def test_partial_decode_stops_on_none(self, mock_to_bgr):
        mock_cv2 = MagicMock()
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.return_value = 10
        frame = np.zeros((10, 20, 3), dtype=np.uint8)
        cap.read.side_effect = [(True, frame), (False, None)]
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        mock_to_bgr.return_value = np.ascontiguousarray(frame)

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            worker = VideoDecodeWorker(Path("/tmp/partial.mp4"), request_id=1)
            finished_events = []
            worker.signals.finished.connect(
                lambda rid, p, f: finished_events.append(f)
            )

            worker.run()

            assert len(finished_events) == 1
            assert finished_events[0].shape[0] == 1
            cap.release.assert_called_once()

    def test_cap_release_called_in_finally(self):
        mock_cv2 = MagicMock()
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.return_value = 1
        cap.read.return_value = (False, None)
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 7

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            worker = VideoDecodeWorker(Path("/tmp/src.mp4"), request_id=1)
            worker.run()
            cap.release.assert_called_once()
