"""Unit tests for OpticalFlowRefineWorker."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers.optical_flow_refine_worker import (
    OpticalFlowRefineWorker,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _make_worker(
    source_path: Path | None = None,
    media_format: str = "mp4",
    contour_points: list[tuple[float, float]] | None = None,
    current_frame_idx: int = 3,
    total_frames: int = 10,
    frame_time_ms: float | None = 33.3,
) -> OpticalFlowRefineWorker:
    path = source_path or Path(tempfile.mkdtemp()) / "test.mp4"
    pts = contour_points or [(30.0, 25.0), (32.0, 25.0), (34.0, 25.0)]
    return OpticalFlowRefineWorker(
        source_path=path,
        media_format=media_format,
        contour_points=pts,
        current_frame_idx=current_frame_idx,
        total_frames=total_frames,
        frame_time_ms=frame_time_ms,
    )


class TestOpticalFlowRefineWorkerInit:
    def test_auto_delete_is_true(self) -> None:
        w = _make_worker()
        assert w.autoDelete() is True

    def test_signals_attribute_exists(self) -> None:
        w = _make_worker()
        assert hasattr(w, "signals")
        assert hasattr(w.signals, "finished")
        assert hasattr(w.signals, "failed")


class TestOpticalFlowRefineWorkerRun:
    def test_fewer_than_3_frames_returns_original(self, qapp) -> None:
        """When load returns < 3 frames, should emit original points."""
        pts = [(30.0, 25.0), (32.0, 25.0), (34.0, 25.0)]
        w = _make_worker(contour_points=pts)

        received = []
        w.signals.finished.connect(lambda p: received.append(p))

        with patch.object(w, "_load_neighbor_frames", return_value=[np.zeros((64, 64), dtype=np.uint8)]):
            QThreadPool.globalInstance().start(w)
            qapp.processEvents()

            import time
            time.sleep(0.3)
            qapp.processEvents()

        assert len(received) == 1
        assert received[0] == pts

    def test_exception_returns_original_points(self, qapp) -> None:
        """On exception, should return original points unchanged."""
        pts = [(30.0, 25.0), (32.0, 25.0), (34.0, 25.0)]
        w = _make_worker(contour_points=pts)

        received = []
        w.signals.finished.connect(lambda p: received.append(p))

        with patch.object(w, "_load_neighbor_frames", side_effect=Exception("test error")):
            QThreadPool.globalInstance().start(w)
            qapp.processEvents()

            import time
            time.sleep(0.3)
            qapp.processEvents()

        assert len(received) == 1
        assert received[0] == pts


class TestLoadNeighborFrames:
    def test_mp4_delegates_to_load_from_mp4(self) -> None:
        w = _make_worker(media_format="mp4", current_frame_idx=5, total_frames=20)
        fake_frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(7)]

        with patch.object(w, "_load_from_mp4", return_value=fake_frames) as mock_mp4:
            result = w._load_neighbor_frames()
        assert len(result) == 7
        mock_mp4.assert_called_once()

    def test_dicom_delegates_to_load_from_dicom(self) -> None:
        w = _make_worker(media_format="dicom", current_frame_idx=5, total_frames=20)
        fake_frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(5)]

        with patch.object(w, "_load_from_dicom", return_value=fake_frames) as mock_dcm:
            result = w._load_neighbor_frames()
        assert len(result) == 5
        mock_dcm.assert_called_once()

    def test_indices_are_centered_on_current_frame(self) -> None:
        w = _make_worker(media_format="mp4", current_frame_idx=10, total_frames=20)

        captured_indices = []
        def fake_mp4(indices):
            captured_indices.extend(indices)
            return [np.zeros((64, 64), dtype=np.uint8) for _ in indices]

        with patch.object(w, "_load_from_mp4", side_effect=fake_mp4):
            w._load_neighbor_frames()

        assert 10 in captured_indices
        assert all(0 <= idx < 20 for idx in captured_indices)


class TestLoadFromMp4Worker:
    def test_returns_empty_when_not_opened(self) -> None:
        w = _make_worker(media_format="mp4")
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        with patch("echo_personal_tool.application.workers.optical_flow_refine_worker.cv2.VideoCapture", return_value=mock_cap):
            result = w._load_from_mp4([0, 1, 2])
        assert result == []

    def test_loads_only_requested_indices(self) -> None:
        w = _make_worker(media_format="mp4")
        frames = [np.zeros((64, 64, 3), dtype=np.uint8) for _ in range(5)]

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.side_effect = [(True, f) for f in frames] + [(False, None)]

        with patch("echo_personal_tool.application.workers.optical_flow_refine_worker.cv2.VideoCapture", return_value=mock_cap):
            with patch("echo_personal_tool.application.workers.optical_flow_refine_worker.cv2.cvtColor", return_value=np.zeros((64, 64), dtype=np.uint8)):
                result = w._load_from_mp4([1, 3])
        # Should only include frames at indices 1 and 3
        assert len(result) == 2
