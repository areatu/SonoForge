"""Unit tests for OpticalFlowRefineWorker."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers.optical_flow_refine_worker import (
    OpticalFlowRefineSignals,
    OpticalFlowRefineWorker,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ── Signals ────────────────────────────────────────────────────────


class TestOpticalFlowRefineSignals:
    def test_has_finished_and_failed(self):
        signals = OpticalFlowRefineSignals()
        assert hasattr(signals, "finished")
        assert hasattr(signals, "failed")


# ── Construction ──────────────────────────────────────────────────


class TestOpticalFlowRefineWorkerConstruction:
    def test_init(self):
        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            contour_points=[(1.0, 2.0), (3.0, 4.0)],
            current_frame_idx=5,
            total_frames=20,
            frame_time_ms=33.3,
        )
        assert worker._source_path == Path("/tmp/src.mp4")
        assert worker._media_format == "mp4"
        assert worker._contour_points == [(1.0, 2.0), (3.0, 4.0)]
        assert worker._current_frame_idx == 5
        assert worker._total_frames == 20
        assert worker._frame_time_ms == 33.3
        assert worker.autoDelete() is True


# ── _load_from_mp4 ────────────────────────────────────────────────


class TestLoadFromMp4:
    @patch("echo_personal_tool.application.workers.optical_flow_refine_worker.cv2")
    def test_loads_frames_at_target_indices(self, mock_cv2):
        cap = MagicMock()
        cap.isOpened.return_value = True
        gray_frames = [np.zeros((10, 10), dtype=np.uint8) + i for i in range(5)]
        bgr_frames = [np.stack([gf, gf, gf], axis=-1) for gf in gray_frames]
        cap.read.side_effect = [(True, bf) for bf in bgr_frames] + [(False, None)]
        mock_cv2.VideoCapture.return_value = cap
        mock_cv2.COLOR_BGR2GRAY = 6
        mock_cv2.cvtColor.side_effect = lambda img, code: np.mean(img, axis=2).astype(np.uint8)

        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            contour_points=[(1.0, 2.0)],
            current_frame_idx=3,
            total_frames=5,
        )

        result = worker._load_from_mp4([2, 3, 4])
        assert len(result) == 3

    @patch("echo_personal_tool.application.workers.optical_flow_refine_worker.cv2")
    def test_empty_when_cap_not_opened(self, mock_cv2):
        cap = MagicMock()
        cap.isOpened.return_value = False
        mock_cv2.VideoCapture.return_value = cap

        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/bad.mp4"),
            media_format="mp4",
            contour_points=[(1.0, 2.0)],
            current_frame_idx=0,
            total_frames=10,
        )
        result = worker._load_from_mp4([0, 1, 2])
        assert result == []
        cap.release.assert_called_once()


# ── _load_from_dicom ──────────────────────────────────────────────


class TestLoadFromDicom:
    @patch("echo_personal_tool.application.workers.optical_flow_refine_worker.cv2")
    def test_loads_grayscale_frames(self, mock_cv2):
        frames = [np.zeros((10, 10), dtype=np.uint8) + i for i in range(5)]
        session = MagicMock()
        session.decode_all_frames.return_value = frames

        mock_cv2.COLOR_BGR2GRAY = 6

        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.dcm"),
            media_format="dicom",
            contour_points=[(1.0, 2.0)],
            current_frame_idx=2,
            total_frames=5,
        )

        with patch(
            "echo_personal_tool.infrastructure.dicom_session.get_thread_dicom_session",
            return_value=session,
        ):
            result = worker._load_from_dicom([1, 2, 3])
            assert len(result) == 3
            session.open.assert_called_once()

    @patch("echo_personal_tool.application.workers.optical_flow_refine_worker.cv2")
    def test_converts_3ch_frame(self, mock_cv2):
        frame_rgb = np.zeros((10, 10, 3), dtype=np.uint8)
        session = MagicMock()
        session.decode_all_frames.return_value = [frame_rgb]

        mock_cv2.COLOR_BGR2GRAY = 6
        mock_cv2.cvtColor.return_value = np.zeros((10, 10), dtype=np.uint8)

        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.dcm"),
            media_format="dicom",
            contour_points=[],
            current_frame_idx=0,
            total_frames=1,
        )

        with patch(
            "echo_personal_tool.infrastructure.dicom_session.get_thread_dicom_session",
            return_value=session,
        ):
            result = worker._load_from_dicom([0])
            assert len(result) == 1
            mock_cv2.cvtColor.assert_called_once()

    @patch("echo_personal_tool.application.workers.optical_flow_refine_worker.cv2")
    def test_converts_4ch_frame(self, mock_cv2):
        frame_rgba = np.zeros((10, 10, 4), dtype=np.uint8)
        session = MagicMock()
        session.decode_all_frames.return_value = [frame_rgba]

        mock_cv2.COLOR_BGR2GRAY = 6

        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.dcm"),
            media_format="dicom",
            contour_points=[],
            current_frame_idx=0,
            total_frames=1,
        )

        with patch(
            "echo_personal_tool.infrastructure.dicom_session.get_thread_dicom_session",
            return_value=session,
        ):
            result = worker._load_from_dicom([0])
            assert len(result) == 1
            assert result[0].shape == (10, 10)

    @patch("echo_personal_tool.application.workers.optical_flow_refine_worker.cv2")
    def test_skips_out_of_range_indices(self, mock_cv2):
        session = MagicMock()
        session.decode_all_frames.return_value = [np.zeros((10, 10), dtype=np.uint8)]
        mock_cv2.COLOR_BGR2GRAY = 6

        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.dcm"),
            media_format="dicom",
            contour_points=[],
            current_frame_idx=0,
            total_frames=1,
        )

        with patch(
            "echo_personal_tool.infrastructure.dicom_session.get_thread_dicom_session",
            return_value=session,
        ):
            result = worker._load_from_dicom([0, 5, 10])
            assert len(result) == 1


# ── _load_neighbor_frames ─────────────────────────────────────────


class TestLoadNeighborFrames:
    @patch.object(OpticalFlowRefineWorker, "_load_from_mp4")
    def test_mp4_delegates_to_mp4_loader(self, mock_mp4):
        mock_mp4.return_value = [np.zeros((10, 10)) for _ in range(5)]
        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            contour_points=[],
            current_frame_idx=5,
            total_frames=20,
        )
        worker._load_neighbor_frames()
        mock_mp4.assert_called_once()
        indices = mock_mp4.call_args[0][0]
        assert indices == list(range(2, 9))

    @patch.object(OpticalFlowRefineWorker, "_load_from_dicom")
    def test_dicom_delegates_to_dicom_loader(self, mock_dicom):
        mock_dicom.return_value = [np.zeros((10, 10)) for _ in range(5)]
        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.dcm"),
            media_format="dicom",
            contour_points=[],
            current_frame_idx=5,
            total_frames=20,
        )
        worker._load_neighbor_frames()
        mock_dicom.assert_called_once()

    @patch.object(OpticalFlowRefineWorker, "_load_from_mp4")
    def test_clamps_start_at_zero(self, mock_mp4):
        mock_mp4.return_value = []
        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            contour_points=[],
            current_frame_idx=1,
            total_frames=20,
        )
        worker._load_neighbor_frames()
        indices = mock_mp4.call_args[0][0]
        assert indices[0] == 0

    @patch.object(OpticalFlowRefineWorker, "_load_from_mp4")
    def test_clamps_end_at_total_minus_1(self, mock_mp4):
        mock_mp4.return_value = []
        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            contour_points=[],
            current_frame_idx=18,
            total_frames=20,
        )
        worker._load_neighbor_frames()
        indices = mock_mp4.call_args[0][0]
        assert indices[-1] == 19


# ── run ────────────────────────────────────────────────────────────


class TestOpticalFlowRefineWorkerRun:
    @patch.object(OpticalFlowRefineWorker, "_load_neighbor_frames")
    def test_few_frames_returns_original(self, mock_load):
        mock_load.return_value = [np.zeros((10, 10))]
        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            contour_points=[(1.0, 2.0)],
            current_frame_idx=5,
            total_frames=20,
            frame_time_ms=33.3,
        )
        finished_received = []
        worker.signals.finished.connect(lambda pts: finished_received.append(pts))
        worker.run()
        assert finished_received == [[(1.0, 2.0)]]

    @patch("echo_personal_tool.domain.services.optical_flow_refine.refine_contour_with_optical_flow")
    @patch.object(OpticalFlowRefineWorker, "_load_neighbor_frames")
    def test_successful_refinement(self, mock_load, mock_refine):
        mock_load.return_value = [np.zeros((10, 10)) for _ in range(7)]
        mock_refine.return_value = [(5.0, 6.0), (7.0, 8.0)]

        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            contour_points=[(1.0, 2.0), (3.0, 4.0)],
            current_frame_idx=5,
            total_frames=20,
            frame_time_ms=33.3,
        )
        finished_received = []
        worker.signals.finished.connect(lambda pts: finished_received.append(pts))
        worker.run()
        assert finished_received == [[(5.0, 6.0), (7.0, 8.0)]]
        mock_refine.assert_called_once()

    @patch(
        "echo_personal_tool.domain.services.optical_flow_refine.refine_contour_with_optical_flow",
        side_effect=RuntimeError("flow failed"),
    )
    @patch.object(OpticalFlowRefineWorker, "_load_neighbor_frames")
    def test_exception_returns_original_points(self, mock_load, mock_refine):
        mock_load.return_value = [np.zeros((10, 10)) for _ in range(7)]
        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            contour_points=[(1.0, 2.0)],
            current_frame_idx=5,
            total_frames=20,
            frame_time_ms=33.3,
        )
        finished_received = []
        worker.signals.finished.connect(lambda pts: finished_received.append(pts))
        worker.run()
        assert finished_received == [[(1.0, 2.0)]]

    @patch.object(OpticalFlowRefineWorker, "_load_neighbor_frames")
    def test_no_frames_returns_original(self, mock_load):
        mock_load.return_value = []
        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            contour_points=[(1.0, 2.0)],
            current_frame_idx=5,
            total_frames=20,
            frame_time_ms=33.3,
        )
        finished_received = []
        worker.signals.finished.connect(lambda pts: finished_received.append(pts))
        worker.run()
        assert finished_received == [[(1.0, 2.0)]]

    @patch("echo_personal_tool.domain.services.optical_flow_refine.refine_contour_with_optical_flow")
    @patch.object(OpticalFlowRefineWorker, "_load_neighbor_frames")
    def test_no_frame_time_uses_30fps(self, mock_load, mock_refine):
        mock_load.return_value = [np.zeros((10, 10)) for _ in range(7)]
        mock_refine.return_value = [(1.0, 2.0)]

        worker = OpticalFlowRefineWorker(
            source_path=Path("/tmp/src.mp4"),
            media_format="mp4",
            contour_points=[(1.0, 2.0)],
            current_frame_idx=5,
            total_frames=20,
            frame_time_ms=None,
        )
        worker.run()
        _, kwargs = mock_refine.call_args
        assert kwargs["fps"] == 30.0
