"""Unit tests for FrameLoaderWorker."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers.frame_loader_worker import (
    FrameLoaderSignals,
    FrameLoaderWorker,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ── Signals ────────────────────────────────────────────────────────


class TestFrameLoaderSignals:
    def test_has_required_signals(self):
        signals = FrameLoaderSignals()
        assert hasattr(signals, "finished")
        assert hasattr(signals, "batch_finished")
        assert hasattr(signals, "failed")


# ── Construction ──────────────────────────────────────────────────


class TestFrameLoaderWorkerConstruction:
    def test_init_defaults(self):
        worker = FrameLoaderWorker(Path("/tmp/src.dcm"))
        assert worker._path == Path("/tmp/src.dcm")
        assert worker._frame_index == 0
        assert worker._media_format == "dicom"
        assert worker._batch_size == 0
        assert worker.autoDelete() is False

    def test_init_with_params(self):
        worker = FrameLoaderWorker(
            Path("/tmp/src.mp4"),
            frame_index=5,
            media_format="mp4",
            total_frames=100,
            batch_size=10,
        )
        assert worker._frame_index == 5
        assert worker._media_format == "mp4"
        assert worker._total_frames == 100
        assert worker._batch_size == 10


# ── _run_single ────────────────────────────────────────────────────


class TestRunSingle:
    @patch("echo_personal_tool.application.workers.frame_loader_worker.get_thread_video_reader")
    def test_mp4_single(self, mock_get_reader):
        reader = MagicMock()
        pixels = np.zeros((480, 640, 3), dtype=np.uint8)
        reader.read_frame.return_value = pixels
        mock_get_reader.return_value = reader

        worker = FrameLoaderWorker(Path("/tmp/src.mp4"), frame_index=3, media_format="mp4")
        finished = []
        worker.signals.finished.connect(lambda arr: finished.append(arr))
        worker.run()

        assert len(finished) == 1
        reader.open.assert_called_once_with(Path("/tmp/src.mp4"))
        reader.read_frame.assert_called_once_with(3)

    @patch("echo_personal_tool.application.workers.frame_loader_worker.ImageReader")
    def test_jpeg_single(self, MockImageReader):
        reader_instance = MagicMock()
        pixels = np.zeros((100, 200, 3), dtype=np.uint8)
        reader_instance.read_pixels.return_value = pixels
        MockImageReader.return_value = reader_instance

        worker = FrameLoaderWorker(Path("/tmp/img.jpg"), media_format="jpeg")
        finished = []
        worker.signals.finished.connect(lambda arr: finished.append(arr))
        worker.run()

        assert len(finished) == 1
        reader_instance.read_pixels.assert_called_once_with(Path("/tmp/img.jpg"))

    @patch("echo_personal_tool.application.workers.frame_loader_worker.ImageReader")
    def test_png_single(self, MockImageReader):
        reader_instance = MagicMock()
        pixels = np.zeros((50, 50, 3), dtype=np.uint8)
        reader_instance.read_pixels.return_value = pixels
        MockImageReader.return_value = reader_instance

        worker = FrameLoaderWorker(Path("/tmp/img.png"), media_format="png")
        finished = []
        worker.signals.finished.connect(lambda arr: finished.append(arr))
        worker.run()

        assert len(finished) == 1

    @patch(
        "echo_personal_tool.application.workers.frame_loader_worker.get_thread_dicom_session"
    )
    def test_dicom_single(self, mock_get_session):
        session = MagicMock()
        pixels = np.zeros((64, 64), dtype=np.uint8)
        session.decode_single_frame.return_value = pixels
        mock_get_session.return_value = session

        worker = FrameLoaderWorker(Path("/tmp/src.dcm"), frame_index=2, media_format="dicom")
        finished = []
        worker.signals.finished.connect(lambda arr: finished.append(arr))
        worker.run()

        assert len(finished) == 1
        session.open.assert_called_once_with(Path("/tmp/src.dcm"))
        session.decode_single_frame.assert_called_once_with(2)
        session.release_heavy.assert_called_once()


# ── _run_batch ─────────────────────────────────────────────────────


class TestRunBatch:
    @patch("echo_personal_tool.application.workers.frame_loader_worker.get_thread_video_reader")
    def test_batch_mp4(self, mock_get_reader):
        reader = MagicMock()
        frames = [np.zeros((10, 10, 3), dtype=np.uint8) + i for i in range(3)]
        reader.read_frame.side_effect = frames
        mock_get_reader.return_value = reader

        worker = FrameLoaderWorker(
            Path("/tmp/src.mp4"),
            frame_index=5,
            media_format="mp4",
            total_frames=100,
            batch_size=3,
        )
        batch_results = []
        worker.signals.batch_finished.connect(lambda res: batch_results.append(res))
        worker.run()

        assert len(batch_results) == 1
        assert len(batch_results[0]) == 3
        assert batch_results[0][0][0] == 5
        assert batch_results[0][2][0] == 7

    @patch(
        "echo_personal_tool.application.workers.frame_loader_worker.get_thread_dicom_session"
    )
    def test_batch_dicom(self, mock_get_session):
        session = MagicMock()
        frames = [np.zeros((10, 10), dtype=np.uint8) + i for i in range(4)]
        session.decode_single_frame.side_effect = frames
        session.frame_count = 100
        mock_get_session.return_value = session

        worker = FrameLoaderWorker(
            Path("/tmp/src.dcm"),
            frame_index=10,
            media_format="dicom",
            total_frames=100,
            batch_size=4,
        )
        batch_results = []
        worker.signals.batch_finished.connect(lambda res: batch_results.append(res))
        worker.run()

        assert len(batch_results) == 1
        assert len(batch_results[0]) == 4
        session.release_heavy.assert_called_once()

    @patch(
        "echo_personal_tool.application.workers.frame_loader_worker.get_thread_dicom_session"
    )
    def test_batch_dicom_clips_to_actual_count(self, mock_get_session):
        session = MagicMock()
        session.frame_count = 3
        mock_get_session.return_value = session

        worker = FrameLoaderWorker(
            Path("/tmp/src.dcm"),
            frame_index=0,
            media_format="dicom",
            total_frames=100,
            batch_size=10,
        )
        batch_results = []
        worker.signals.batch_finished.connect(lambda res: batch_results.append(res))
        worker.run()

        assert len(batch_results) == 1
        assert len(batch_results[0]) == 3


# ── run dispatch ───────────────────────────────────────────────────


class TestRunDispatch:
    @patch.object(FrameLoaderWorker, "_run_batch")
    def test_batch_mode_dispatches_to_batch(self, mock_batch):
        worker = FrameLoaderWorker(
            Path("/tmp/src.mp4"),
            batch_size=5,
            media_format="mp4",
            total_frames=100,
        )
        worker.run()
        mock_batch.assert_called_once()

    @patch.object(FrameLoaderWorker, "_run_single")
    def test_single_mode_dispatches_to_single(self, mock_single):
        worker = FrameLoaderWorker(Path("/tmp/src.mp4"), media_format="mp4")
        worker.run()
        mock_single.assert_called_once()

    @patch.object(FrameLoaderWorker, "_run_single")
    def test_invalid_format_dispatches_to_single(self, mock_single):
        worker = FrameLoaderWorker(
            Path("/tmp/img.jpg"),
            media_format="jpeg",
            batch_size=5,
        )
        worker.run()
        mock_single.assert_called_once()


# ── exception handling ─────────────────────────────────────────────


class TestExceptionHandling:
    @patch("echo_personal_tool.application.workers.frame_loader_worker.ImageReader")
    def test_exception_emits_failed(self, MockImageReader):
        reader_instance = MagicMock()
        reader_instance.read_pixels.side_effect = OSError("file missing")
        MockImageReader.return_value = reader_instance

        worker = FrameLoaderWorker(Path("/tmp/missing.jpg"), media_format="jpeg")
        failed = []
        worker.signals.failed.connect(lambda msg: failed.append(msg))
        worker.run()

        assert len(failed) == 1
        assert "file missing" in failed[0]

    @patch(
        "echo_personal_tool.application.workers.frame_loader_worker.get_thread_dicom_session"
    )
    def test_failed_emit_runtime_error_swallowed(self, mock_get_session):
        session = MagicMock()
        session.open.side_effect = ValueError("bad")
        mock_get_session.return_value = session

        worker = FrameLoaderWorker(Path("/tmp/src.dcm"), media_format="dicom")
        with patch.object(
            type(worker.signals.failed), "emit", side_effect=RuntimeError("deleted")
        ):
            worker.run()
