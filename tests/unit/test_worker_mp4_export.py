"""Unit tests for Mp4ExportWorker and _open_video_writer."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers.mp4_export_worker import (
    Mp4ExportSignals,
    Mp4ExportWorker,
    _open_video_writer,
    _MP4_FOURCCS,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ── _open_video_writer ────────────────────────────────────────────


class TestOpenVideoWriter:
    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_first_codec_succeeds(self, mock_cv2):
        writer = MagicMock()
        writer.isOpened.return_value = True
        mock_cv2.VideoWriter.return_value = writer

        result = _open_video_writer("/tmp/out.mp4", "mp4v", 30.0, 640, 480)
        mock_cv2.VideoWriter.assert_called_once_with(
            "/tmp/out.mp4", mock_cv2.VideoWriter_fourcc.return_value, 30.0, (640, 480)
        )
        assert result is writer

    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_fallback_to_second_codec(self, mock_cv2):
        fail_writer = MagicMock()
        fail_writer.isOpened.return_value = False
        good_writer = MagicMock()
        good_writer.isOpened.return_value = True
        mock_cv2.VideoWriter.side_effect = [fail_writer, good_writer]

        result = _open_video_writer("/tmp/out.mp4", "mp4v", 30.0, 100, 100)
        assert result is good_writer
        fail_writer.release.assert_called_once()

    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_all_codecs_fail_raises(self, mock_cv2):
        writers = []
        for _ in _MP4_FOURCCS:
            w = MagicMock()
            w.isOpened.return_value = False
            writers.append(w)
        mock_cv2.VideoWriter.side_effect = writers

        with pytest.raises(OSError, match="cannot open"):
            _open_video_writer("/tmp/out.mp4", "mp4v", 30.0, 100, 100)
        for w in writers:
            w.release.assert_called_once()


# ── Mp4ExportSignals ──────────────────────────────────────────────


class TestMp4ExportSignals:
    def test_has_required_signals(self):
        signals = Mp4ExportSignals()
        assert hasattr(signals, "progress")
        assert hasattr(signals, "finished")
        assert hasattr(signals, "failed")


# ── Mp4ExportWorker construction ──────────────────────────────────


class TestMp4ExportWorkerConstruction:
    def test_init_defaults(self):
        worker = Mp4ExportWorker(
            source_path=Path("/tmp/src.mp4"),
            dest_path="/tmp/dest.mp4",
            media_format="mp4",
        )
        assert worker._source_path == Path("/tmp/src.mp4")
        assert worker._dest_path == "/tmp/dest.mp4"
        assert worker._media_format == "mp4"
        assert worker._frame_time_ms is None
        assert worker.autoDelete() is True

    def test_init_with_frame_time(self):
        worker = Mp4ExportWorker(
            source_path=Path("/tmp/src.dcm"),
            dest_path="/tmp/dest.mp4",
            media_format="dicom",
            frame_time_ms=33.3,
        )
        assert worker._frame_time_ms == 33.3


# ── _to_bgr ───────────────────────────────────────────────────────


class TestToBgr:
    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_2d_gray(self, mock_cv2):
        frame = np.zeros((10, 10), dtype=np.uint8)
        Mp4ExportWorker._to_bgr(frame)
        mock_cv2.cvtColor.assert_called_once_with(frame, mock_cv2.COLOR_GRAY2BGR)

    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_3ch_rgb(self, mock_cv2):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        Mp4ExportWorker._to_bgr(frame)
        mock_cv2.cvtColor.assert_called_once_with(frame, mock_cv2.COLOR_RGB2BGR)

    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_4ch_bgra(self, mock_cv2):
        frame = np.zeros((10, 10, 4), dtype=np.uint8)
        Mp4ExportWorker._to_bgr(frame)
        mock_cv2.cvtColor.assert_called_once_with(frame, mock_cv2.COLOR_BGRA2BGR)

    def test_unknown_shape_passthrough(self):
        frame = np.zeros((10, 10, 5), dtype=np.uint8)
        result = Mp4ExportWorker._to_bgr(frame)
        np.testing.assert_array_equal(result, frame)


# ── export from mp4 ───────────────────────────────────────────────


class TestExportFromMp4:
    @patch("echo_personal_tool.application.workers.mp4_export_worker._open_video_writer")
    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_successful_export(self, mock_cv2, mock_open_writer):
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.side_effect = lambda prop: {
            mock_cv2.CAP_PROP_FRAME_COUNT: 3,
            mock_cv2.CAP_PROP_FPS: 25.0,
            mock_cv2.CAP_PROP_FRAME_WIDTH: 640,
            mock_cv2.CAP_PROP_FRAME_HEIGHT: 480,
        }[prop]
        frames = [np.zeros((480, 640, 3), dtype=np.uint8) for _ in range(3)]
        cap.read.side_effect = [(True, f) for f in frames] + [(False, None)]
        mock_cv2.VideoCapture.return_value = cap

        writer = MagicMock()
        mock_open_writer.return_value = writer

        worker = Mp4ExportWorker(Path("/tmp/src.mp4"), "/tmp/dest.mp4", "mp4")

        progress_received = []
        finished_received = []
        worker.signals.progress.connect(lambda cur, tot: progress_received.append((cur, tot)))
        worker.signals.finished.connect(lambda p: finished_received.append(p))

        worker.run()

        assert len(finished_received) == 1
        assert finished_received[0] == "/tmp/dest.mp4"
        assert writer.write.call_count == 3
        writer.release.assert_called_once()
        cap.release.assert_called_once()

    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_capture_not_opened(self, mock_cv2):
        cap = MagicMock()
        cap.isOpened.return_value = False
        mock_cv2.VideoCapture.return_value = cap

        worker = Mp4ExportWorker(Path("/tmp/src.mp4"), "/tmp/dest.mp4", "mp4")
        failed_received = []
        worker.signals.failed.connect(lambda msg: failed_received.append(msg))

        worker.run()
        assert len(failed_received) == 1
        assert "Cannot open video" in failed_received[0]
        cap.release.assert_called_once()

    @patch("echo_personal_tool.application.workers.mp4_export_worker._open_video_writer")
    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_progress_emitted(self, mock_cv2, mock_open_writer):
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.side_effect = lambda prop: {
            mock_cv2.CAP_PROP_FRAME_COUNT: 6,
            mock_cv2.CAP_PROP_FPS: 30.0,
            mock_cv2.CAP_PROP_FRAME_WIDTH: 100,
            mock_cv2.CAP_PROP_FRAME_HEIGHT: 100,
        }[prop]
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(6)]
        cap.read.side_effect = [(True, f) for f in frames] + [(False, None)]
        mock_cv2.VideoCapture.return_value = cap

        writer = MagicMock()
        mock_open_writer.return_value = writer

        worker = Mp4ExportWorker(Path("/tmp/src.mp4"), "/tmp/dest.mp4", "mp4")
        progress_received = []
        worker.signals.progress.connect(lambda cur, tot: progress_received.append((cur, tot)))

        worker.run()
        # Progress emitted at i=5 and i=6 (total)
        assert any(cur == 5 for cur, _ in progress_received)
        assert any(cur == 6 for cur, _ in progress_received)


# ── export from dicom ─────────────────────────────────────────────


class TestExportFromDicom:
    @patch("echo_personal_tool.application.workers.mp4_export_worker._open_video_writer")
    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_single_frame_dicom(self, mock_cv2, mock_open_writer):
        frame = np.zeros((64, 64), dtype=np.uint8)
        session = MagicMock()
        session.frame_count = 1
        session.decode_first_frame.return_value = frame

        mock_cv2.cvtColor.return_value = np.zeros((64, 64, 3), dtype=np.uint8)
        mock_cv2.COLOR_GRAY2BGR = 7

        writer = MagicMock()
        mock_open_writer.return_value = writer

        with patch(
            "echo_personal_tool.infrastructure.dicom_session.get_thread_dicom_session",
            return_value=session,
        ):
            worker = Mp4ExportWorker(
                Path("/tmp/src.dcm"), "/tmp/dest.mp4", "dicom", frame_time_ms=33.3
            )
            finished_received = []
            worker.signals.finished.connect(lambda p: finished_received.append(p))

            worker.run()

            assert len(finished_received) == 1
            session.open.assert_called_once_with(Path("/tmp/src.dcm"))
            writer.write.assert_called_once()
            writer.release.assert_called_once()

    @patch("echo_personal_tool.application.workers.mp4_export_worker._open_video_writer")
    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_multi_frame_dicom(self, mock_cv2, mock_open_writer):
        frames = [np.zeros((32, 32), dtype=np.uint8) for _ in range(5)]
        session = MagicMock()
        session.frame_count = 5
        session.decode_first_frame.return_value = frames[0]
        session.decode_all_frames.return_value = frames

        mock_cv2.cvtColor.return_value = np.zeros((32, 32, 3), dtype=np.uint8)
        mock_cv2.COLOR_GRAY2BGR = 7

        writer = MagicMock()
        mock_open_writer.return_value = writer

        with patch(
            "echo_personal_tool.infrastructure.dicom_session.get_thread_dicom_session",
            return_value=session,
        ):
            worker = Mp4ExportWorker(
                Path("/tmp/src.dcm"), "/tmp/dest.mp4", "dicom", frame_time_ms=33.3
            )
            finished_received = []
            worker.signals.finished.connect(lambda p: finished_received.append(p))

            worker.run()

            assert len(finished_received) == 1
            assert writer.write.call_count == 5
            writer.release.assert_called_once()

    @patch("echo_personal_tool.application.workers.mp4_export_worker._open_video_writer")
    @patch("echo_personal_tool.application.workers.mp4_export_worker.cv2")
    def test_dicom_no_frame_time_uses_30fps(self, mock_cv2, mock_open_writer):
        frame = np.zeros((32, 32), dtype=np.uint8)
        session = MagicMock()
        session.frame_count = 1
        session.decode_first_frame.return_value = frame

        mock_cv2.cvtColor.return_value = np.zeros((32, 32, 3), dtype=np.uint8)
        mock_cv2.COLOR_GRAY2BGR = 7
        writer = MagicMock()
        mock_open_writer.return_value = writer

        with patch(
            "echo_personal_tool.infrastructure.dicom_session.get_thread_dicom_session",
            return_value=session,
        ):
            worker = Mp4ExportWorker(
                Path("/tmp/src.dcm"), "/tmp/dest.mp4", "dicom", frame_time_ms=None
            )
            worker.run()
            _, _, fps, _, _ = mock_open_writer.call_args[0]
            assert fps == 30.0


# ── run dispatches to correct method ──────────────────────────────


class TestRunDispatch:
    @patch.object(Mp4ExportWorker, "_export_from_dicom")
    def test_dispatch_to_dicom(self, mock_export):
        worker = Mp4ExportWorker(Path("/tmp/src.dcm"), "/tmp/dest.mp4", "dicom")
        worker.run()
        mock_export.assert_called_once()

    @patch.object(Mp4ExportWorker, "_export_from_mp4")
    def test_dispatch_to_mp4(self, mock_export):
        worker = Mp4ExportWorker(Path("/tmp/src.mp4"), "/tmp/dest.mp4", "mp4")
        worker.run()
        mock_export.assert_called_once()

    @patch.object(Mp4ExportWorker, "_export_from_mp4", side_effect=RuntimeError("boom"))
    def test_run_catches_exception(self, mock_export):
        worker = Mp4ExportWorker(Path("/tmp/src.mp4"), "/tmp/dest.mp4", "mp4")
        failed_received = []
        worker.signals.failed.connect(lambda msg: failed_received.append(msg))

        worker.run()
        assert len(failed_received) == 1
        assert "boom" in failed_received[0]
