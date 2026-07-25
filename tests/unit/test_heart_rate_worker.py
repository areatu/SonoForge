"""Unit tests for HeartRateWorker — signal delivery and fallback logic."""

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

from echo_personal_tool.application.workers.heart_rate_worker import (
    HeartRateWorker,
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
    frame_time_ms: float | None = 33.3,
    contour_areas: list[float] | None = None,
    contour_frame_indices: list[int] | None = None,
) -> HeartRateWorker:
    path = source_path or Path(tempfile.mkdtemp()) / "test.mp4"
    return HeartRateWorker(
        source_path=path,
        media_format=media_format,
        frame_time_ms=frame_time_ms,
        contour_areas=contour_areas,
        contour_frame_indices=contour_frame_indices,
    )


class TestHeartRateWorkerInit:
    def test_auto_delete_is_true(self) -> None:
        w = _make_worker()
        assert w.autoDelete() is True

    def test_signals_attribute_exists(self) -> None:
        w = _make_worker()
        assert hasattr(w, "signals")
        assert hasattr(w.signals, "finished")
        assert hasattr(w.signals, "failed")


class TestHeartRateWorkerAreaTime:
    def test_area_time_success(self, qapp, qtbot) -> None:
        """When contour_areas has enough data, area-time method should fire."""
        # Create a sinusoidal area signal (mimics cardiac cycle)
        fps = 30.0
        n = 60
        t = np.arange(n) / fps
        areas = 1000.0 + 200.0 * np.sin(2 * np.pi * 1.2 * t)  # ~72 bpm

        w = _make_worker(
            frame_time_ms=1000.0 / fps,
            contour_areas=areas.tolist(),
            contour_frame_indices=list(range(n)),
        )

        finished = []
        failed = []
        w.signals.finished.connect(lambda bpm, conf, method: finished.append((bpm, conf, method)))
        w.signals.failed.connect(lambda msg: failed.append(msg))

        QThreadPool.globalInstance().start(w)
        qtbot.waitUntil(lambda: len(finished) + len(failed) > 0, timeout=5000)

        assert len(finished) == 1
        bpm, conf, method = finished[0]
        assert bpm > 0
        assert method == "area_time"
        assert 0.0 <= conf <= 1.0

    def test_area_time_too_few_points_falls_through(self, qapp) -> None:
        """With fewer than 4 contour areas, should fall through to optical flow."""
        w = _make_worker(
            frame_time_ms=33.3,
            contour_areas=[100.0, 200.0, 300.0],  # < 4
        )

        failed = []
        w.signals.failed.connect(lambda msg: failed.append(msg))

        with patch.object(w, "_load_frames_subsampled", return_value=[]):
            QThreadPool.globalInstance().start(w)
            qapp.processEvents()

            import time
            time.sleep(0.3)
            qapp.processEvents()

        assert len(failed) == 1
        assert "No frames" in failed[0]


class TestHeartRateWorkerOpticalFlow:
    def test_no_frames_emits_failed(self, qapp) -> None:
        w = _make_worker(frame_time_ms=33.3)

        failed = []
        w.signals.failed.connect(lambda msg: failed.append(msg))

        with patch.object(w, "_load_frames_subsampled", return_value=[]):
            QThreadPool.globalInstance().start(w)
            qapp.processEvents()

            import time
            time.sleep(0.3)
            qapp.processEvents()

        assert len(failed) == 1
        assert "No frames" in failed[0]


class TestLoadFramesSubsampled:
    def test_mp4_fewer_than_max_returns_all(self) -> None:
        w = _make_worker(media_format="mp4")
        fake_frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(10)]

        with patch.object(w, "_load_from_mp4", return_value=fake_frames):
            result = w._load_frames_subsampled()
        assert len(result) == 10

    def test_mp4_more_than_max_subsamples(self) -> None:
        w = _make_worker(media_format="mp4")
        fake_frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(120)]

        with patch.object(w, "_load_from_mp4", return_value=fake_frames):
            result = w._load_frames_subsampled()
        assert len(result) == 60  # _MAX_FRAMES_FOR_OPTICAL_FLOW

    def test_dicom_format_calls_load_from_dicom(self) -> None:
        w = _make_worker(media_format="dicom")
        fake_frames = [np.zeros((64, 64), dtype=np.uint8) for _ in range(5)]

        with patch.object(w, "_load_from_dicom", return_value=fake_frames):
            result = w._load_frames_subsampled()
        assert len(result) == 5


class TestLoadFromMp4:
    def test_returns_empty_when_not_opened(self) -> None:
        w = _make_worker(media_format="mp4")
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        with patch("echo_personal_tool.application.workers.heart_rate_worker.cv2.VideoCapture", return_value=mock_cap):
            result = w._load_from_mp4()
        assert result == []

    def test_reads_frames_until_fail(self) -> None:
        w = _make_worker(media_format="mp4")
        frame1 = np.zeros((64, 64, 3), dtype=np.uint8)
        frame2 = np.zeros((64, 64, 3), dtype=np.uint8)

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.side_effect = [
            (True, frame1),
            (True, frame2),
            (False, None),
        ]

        with patch("echo_personal_tool.application.workers.heart_rate_worker.cv2.VideoCapture", return_value=mock_cap):
            with patch("echo_personal_tool.application.workers.heart_rate_worker.cv2.cvtColor", return_value=np.zeros((64, 64), dtype=np.uint8)):
                result = w._load_from_mp4()
        assert len(result) == 2
