"""Unit tests for HeartRateWorker."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers.heart_rate_worker import (
    _MAX_FRAMES_FOR_OPTICAL_FLOW,
    HeartRateSignals,
    HeartRateWorker,
)
from echo_personal_tool.domain.services.heart_rate import HeartRateResult


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ── Signals ────────────────────────────────────────────────────────


class TestHeartRateSignals:
    def test_has_finished_and_failed(self):
        signals = HeartRateSignals()
        assert hasattr(signals, "finished")
        assert hasattr(signals, "failed")


# ── Construction ──────────────────────────────────────────────────


class TestHeartRateWorkerConstruction:
    def test_init_defaults(self):
        worker = HeartRateWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
        )
        assert worker._source_path == Path("/tmp/src.mp4")
        assert worker._media_format == "mp4"
        assert worker._frame_time_ms is None
        assert worker._contour_areas is None
        assert worker.autoDelete() is True

    def test_init_with_contours(self):
        worker = HeartRateWorker(
            source_path=Path("/tmp/src.dcm"),
            media_format="dicom",
            frame_time_ms=33.3,
            contour_areas=[100.0, 200.0, 300.0, 400.0],
            contour_frame_indices=[0, 1, 2, 3],
        )
        assert worker._contour_areas == [100.0, 200.0, 300.0, 400.0]
        assert worker._contour_frame_indices == [0, 1, 2, 3]


# ── _load_from_mp4 ────────────────────────────────────────────────


class TestLoadFromMp4:
    @patch("echo_personal_tool.application.workers.heart_rate_worker.cv2")
    def test_loads_grayscale_frames(self, mock_cv2):
        cap = MagicMock()
        cap.isOpened.return_value = True
        bgr_frames = [np.zeros((10, 10, 3), dtype=np.uint8) + i for i in range(3)]
        cap.read.side_effect = [(True, f) for f in bgr_frames] + [(False, None)]
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.COLOR_BGR2GRAY = 6
        mock_cv2.cvtColor.side_effect = lambda img, code: np.mean(img, axis=2).astype(np.uint8)

        worker = HeartRateWorker(source_path=Path("/tmp/src.mp4"), media_format="mp4")
        result = worker._load_from_mp4()
        assert len(result) == 3
        cap.release.assert_called_once()

    @patch("echo_personal_tool.application.workers.heart_rate_worker.cv2")
    def test_empty_when_cap_not_opened(self, mock_cv2):
        cap = MagicMock()
        cap.isOpened.return_value = False
        mock_cv2.VideoCapture.return_value = cap

        worker = HeartRateWorker(source_path=Path("/tmp/bad.mp4"), media_format="mp4")
        result = worker._load_from_mp4()
        assert result == []


# ── _load_from_dicom ──────────────────────────────────────────────


class TestLoadFromDicom:
    @patch("echo_personal_tool.application.workers.heart_rate_worker.cv2")
    def test_loads_2d_frames(self, mock_cv2):
        frames = [np.zeros((10, 10), dtype=np.uint8) + i for i in range(3)]
        session = MagicMock()
        session.decode_all_frames.return_value = frames
        mock_cv2.COLOR_BGR2GRAY = 6

        worker = HeartRateWorker(source_path=Path("/tmp/src.dcm"), media_format="dicom")
        with patch(
            "echo_personal_tool.infrastructure.dicom_session.get_thread_dicom_session",
            return_value=session,
        ):
            result = worker._load_from_dicom()
            assert len(result) == 3

    @patch("echo_personal_tool.application.workers.heart_rate_worker.cv2")
    def test_loads_3ch_frames(self, mock_cv2):
        frames = [np.zeros((10, 10, 3), dtype=np.uint8) for _ in range(2)]
        session = MagicMock()
        session.decode_all_frames.return_value = frames
        mock_cv2.COLOR_BGR2GRAY = 6
        mock_cv2.cvtColor.return_value = np.zeros((10, 10), dtype=np.uint8)

        worker = HeartRateWorker(source_path=Path("/tmp/src.dcm"), media_format="dicom")
        with patch(
            "echo_personal_tool.infrastructure.dicom_session.get_thread_dicom_session",
            return_value=session,
        ):
            result = worker._load_from_dicom()
            assert len(result) == 2
            mock_cv2.cvtColor.assert_called()


# ── _load_frames_subsampled ───────────────────────────────────────


class TestLoadFramesSubsampled:
    @patch.object(HeartRateWorker, "_load_from_mp4")
    def test_fewer_than_max_not_subsampled(self, mock_load):
        mock_load.return_value = [np.zeros((10, 10)) for _ in range(10)]
        worker = HeartRateWorker(source_path=Path("/tmp/src.mp4"), media_format="mp4")
        result = worker._load_frames_subsampled()
        assert len(result) == 10

    @patch.object(HeartRateWorker, "_load_from_mp4")
    def test_more_than_max_subsampled(self, mock_load):
        mock_load.return_value = [np.zeros((10, 10)) for _ in range(120)]
        worker = HeartRateWorker(source_path=Path("/tmp/src.mp4"), media_format="mp4")
        result = worker._load_frames_subsampled()
        assert len(result) == _MAX_FRAMES_FOR_OPTICAL_FLOW


# ── run ────────────────────────────────────────────────────────────


class TestHeartRateWorkerRun:
    @patch("echo_personal_tool.domain.services.heart_rate.estimate_hr_area_time")
    def test_area_time_path(self, mock_area):
        mock_area.return_value = HeartRateResult(
            bpm=72.0,
            method="area_time",
            confidence=0.9,
            es_intervals_ms=[833.3],
            frame_rate=30.0,
            num_frames_used=10,
        )

        worker = HeartRateWorker(
            source_path=Path("/tmp/src.dcm"),
            media_format="dicom",
            frame_time_ms=33.3,
            contour_areas=[100.0, 200.0, 300.0, 400.0],
        )
        finished = []
        worker.signals.finished.connect(lambda bpm, conf, method: finished.append((bpm, conf, method)))
        worker.run()
        assert finished == [(72.0, 0.9, "area_time")]

    @patch("echo_personal_tool.domain.services.heart_rate.estimate_hr_optical_flow")
    @patch("echo_personal_tool.domain.services.heart_rate.estimate_hr_area_time")
    def test_area_time_fails_falls_to_optical_flow(self, mock_area, mock_of):
        mock_area.return_value = HeartRateResult(
            bpm=0.0,
            method="area_time",
            confidence=0.0,
            es_intervals_ms=[],
            frame_rate=30.0,
            num_frames_used=0,
        )

        mock_of.return_value = HeartRateResult(
            bpm=65.0,
            method="optical_flow",
            confidence=0.7,
            es_intervals_ms=[923.0],
            frame_rate=30.0,
            num_frames_used=20,
        )

        worker = HeartRateWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            frame_time_ms=33.3,
            contour_areas=[100.0, 200.0, 300.0, 400.0],
        )

        with patch.object(
            worker,
            "_load_frames_subsampled",
            return_value=[np.zeros((10, 10)) for _ in range(10)],
        ):
            finished = []
            worker.signals.finished.connect(lambda bpm, conf, method: finished.append((bpm, conf, method)))
            worker.run()
            assert finished == [(65.0, 0.7, "optical_flow")]

    @patch("echo_personal_tool.domain.services.heart_rate.estimate_hr_optical_flow")
    def test_optical_flow_path(self, mock_of):
        mock_of.return_value = HeartRateResult(
            bpm=80.0,
            method="optical_flow",
            confidence=0.6,
            es_intervals_ms=[750.0],
            frame_rate=30.0,
            num_frames_used=30,
        )

        worker = HeartRateWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            frame_time_ms=33.3,
        )
        with patch.object(
            worker,
            "_load_frames_subsampled",
            return_value=[np.zeros((10, 10)) for _ in range(10)],
        ):
            finished = []
            worker.signals.finished.connect(lambda bpm, conf, method: finished.append((bpm, conf, method)))
            worker.run()
            assert finished == [(80.0, 0.6, "optical_flow")]

    def test_no_frames_returns_failed(self):
        worker = HeartRateWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            frame_time_ms=33.3,
        )
        with patch.object(worker, "_load_frames_subsampled", return_value=[]):
            failed = []
            worker.signals.failed.connect(lambda msg: failed.append(msg))
            worker.run()
            assert "No frames available" in failed[0]

    @patch("echo_personal_tool.domain.services.heart_rate.estimate_hr_optical_flow")
    def test_optical_flow_returns_zero_emits_failed(self, mock_of):
        mock_of.return_value = HeartRateResult(
            bpm=0.0,
            method="optical_flow",
            confidence=0.0,
            es_intervals_ms=[],
            frame_rate=30.0,
            num_frames_used=10,
        )

        worker = HeartRateWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            frame_time_ms=33.3,
        )
        with patch.object(
            worker,
            "_load_frames_subsampled",
            return_value=[np.zeros((10, 10)) for _ in range(10)],
        ):
            failed = []
            worker.signals.failed.connect(lambda msg: failed.append(msg))
            worker.run()
            assert "Could not estimate heart rate" in failed[0]

    @patch("echo_personal_tool.domain.services.heart_rate.estimate_hr_area_time", side_effect=RuntimeError("boom"))
    def test_exception_emits_failed(self, mock_area):
        worker = HeartRateWorker(
            source_path=Path("/tmp/src.dcm"),
            media_format="dicom",
            frame_time_ms=33.3,
            contour_areas=[100.0, 200.0, 300.0, 400.0],
        )
        failed = []
        worker.signals.failed.connect(lambda msg: failed.append(msg))
        worker.run()
        assert "boom" in failed[0]

    @patch("echo_personal_tool.domain.services.heart_rate.estimate_hr_optical_flow")
    def test_no_frame_time_uses_30fps(self, mock_of):
        mock_of.return_value = HeartRateResult(
            bpm=70.0,
            method="optical_flow",
            confidence=0.5,
            es_intervals_ms=[],
            frame_rate=30.0,
            num_frames_used=10,
        )
        worker = HeartRateWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            frame_time_ms=None,
        )
        with patch.object(
            worker,
            "_load_frames_subsampled",
            return_value=[np.zeros((10, 10)) for _ in range(10)],
        ):
            worker.run()
            _, kwargs = mock_of.call_args
            assert kwargs["fps"] == 30.0

    @patch("echo_personal_tool.domain.services.heart_rate.estimate_hr_optical_flow")
    def test_short_contour_areas_skips_area_method(self, mock_of):
        mock_of.return_value = HeartRateResult(
            bpm=75.0,
            method="optical_flow",
            confidence=0.6,
            es_intervals_ms=[800.0],
            frame_rate=30.0,
            num_frames_used=10,
        )
        worker = HeartRateWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            frame_time_ms=33.3,
            contour_areas=[100.0, 200.0],  # < 4
        )
        with patch.object(
            worker,
            "_load_frames_subsampled",
            return_value=[np.zeros((10, 10)) for _ in range(10)],
        ):
            with patch("echo_personal_tool.domain.services.heart_rate.estimate_hr_area_time") as mock_area:
                finished = []
                worker.signals.finished.connect(lambda bpm, conf, method: finished.append((bpm, conf, method)))
                worker.run()
                mock_area.assert_not_called()
                assert finished == [(75.0, 0.6, "optical_flow")]
