"""Unit tests for Mp4ExportWorker and _to_bgr / _open_video_writer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from echo_personal_tool.application.workers.mp4_export_worker import (
    Mp4ExportWorker,
    _MP4_FOURCCS,
    _open_video_writer,
)


class TestToBgr:
    def test_grayscale(self) -> None:
        gray = np.zeros((50, 80), dtype=np.uint8)
        result = Mp4ExportWorker._to_bgr(gray)
        assert result.ndim == 3
        assert result.shape[2] == 3

    def test_rgb(self) -> None:
        rgb = np.zeros((50, 80, 3), dtype=np.uint8)
        result = Mp4ExportWorker._to_bgr(rgb)
        assert result.shape == (50, 80, 3)

    def test_bgra(self) -> None:
        bgra = np.zeros((50, 80, 4), dtype=np.uint8)
        result = Mp4ExportWorker._to_bgr(bgra)
        assert result.shape[2] == 3

    def test_already_bgr(self) -> None:
        bgr = np.zeros((50, 80, 3), dtype=np.uint8)
        result = Mp4ExportWorker._to_bgr(bgr)
        assert result.shape == (50, 80, 3)


class TestMp4ExportWorker:
    def test_instantiation(self) -> None:
        worker = Mp4ExportWorker(
            source_path=Path("/test.dcm"),
            dest_path="/output.mp4",
            media_format="dicom",
        )
        assert worker._source_path == Path("/test.dcm")
        assert worker._dest_path == "/output.mp4"
        assert worker._media_format == "dicom"

    def test_has_signals(self) -> None:
        worker = Mp4ExportWorker(
            source_path=Path("/test.dcm"),
            dest_path="/output.mp4",
            media_format="dicom",
        )
        assert hasattr(worker.signals, "progress")
        assert hasattr(worker.signals, "finished")
        assert hasattr(worker.signals, "failed")

    def test_auto_delete(self) -> None:
        worker = Mp4ExportWorker(
            source_path=Path("/test.dcm"),
            dest_path="/output.mp4",
            media_format="dicom",
        )
        assert worker.autoDelete() is True

    def test_with_frame_time(self) -> None:
        worker = Mp4ExportWorker(
            source_path=Path("/test.dcm"),
            dest_path="/output.mp4",
            media_format="dicom",
            frame_time_ms=33.3,
        )
        assert worker._frame_time_ms == 33.3


class TestOpenVideoWriter:
    def test_raises_on_failure(self) -> None:
        # Patch VideoWriter to always fail isOpened
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = False

        with patch("echo_personal_tool.application.workers.mp4_export_worker.cv2") as mock_cv2:
            mock_cv2.VideoWriter.return_value = mock_writer
            mock_cv2.VideoWriter_fourcc.return_value = 0
            mock_cv2.COLOR_GRAY2BGR = cv2.COLOR_GRAY2BGR

            import pytest
            with pytest.raises(OSError, match="cannot open"):
                _open_video_writer("/tmp/test.mp4", "mp4v", 30.0, 640, 480)

    def test_fourcc_list(self) -> None:
        assert "mp4v" in _MP4_FOURCCS
        assert "" in _MP4_FOURCCS
