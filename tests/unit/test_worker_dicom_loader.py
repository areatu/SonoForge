"""Unit tests for DicomLoaderWorker."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers.dicom_loader_worker import DicomLoaderWorker
from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class TestDicomLoaderWorkerConstruction:
    def test_inherits_from_frame_loader_worker(self):
        assert issubclass(DicomLoaderWorker, FrameLoaderWorker)

    def test_init_sets_dicom_format(self):
        worker = DicomLoaderWorker(Path("/tmp/src.dcm"))
        assert worker._media_format == "dicom"
        assert worker._path == Path("/tmp/src.dcm")
        assert worker._frame_index == 0

    def test_init_with_frame_index(self):
        worker = DicomLoaderWorker(Path("/tmp/src.dcm"), frame_index=5)
        assert worker._frame_index == 5
        assert worker._media_format == "dicom"

    def test_has_signals(self):
        worker = DicomLoaderWorker(Path("/tmp/src.dcm"))
        assert hasattr(worker.signals, "finished")
        assert hasattr(worker.signals, "failed")
        assert hasattr(worker.signals, "batch_finished")

    def test_not_auto_delete(self):
        worker = DicomLoaderWorker(Path("/tmp/src.dcm"))
        assert worker.autoDelete() is False


class TestDicomLoaderWorkerRun:
    @patch(
        "echo_personal_tool.application.workers.frame_loader_worker.get_thread_dicom_session"
    )
    def test_run_single_frame(self, mock_get_session):
        session = MagicMock()
        session.decode_single_frame.return_value = np.zeros((64, 64), dtype=np.uint8)
        mock_get_session.return_value = session

        worker = DicomLoaderWorker(Path("/tmp/src.dcm"), frame_index=0)
        finished = []
        worker.signals.finished.connect(lambda arr: finished.append(arr))
        worker.run()

        assert len(finished) == 1
        assert finished[0].shape == (64, 64)
        session.open.assert_called_once_with(Path("/tmp/src.dcm"))
        session.decode_single_frame.assert_called_once_with(0)
        session.release_heavy.assert_called_once()
