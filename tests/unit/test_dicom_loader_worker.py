"""Unit tests for DicomLoaderWorker (thin wrapper over FrameLoaderWorker)."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.application.workers.dicom_loader_worker import DicomLoaderWorker
from echo_personal_tool.application.workers.frame_loader_worker import FrameLoaderWorker


class TestDicomLoaderWorker:
    def test_inherits_frame_loader(self) -> None:
        assert issubclass(DicomLoaderWorker, FrameLoaderWorker)

    def test_instantiation(self) -> None:
        worker = DicomLoaderWorker(path=Path("/test.dcm"), frame_index=5)
        assert worker._path == Path("/test.dcm")
        assert worker._frame_index == 5
        assert worker._media_format == "dicom"

    def test_default_frame_index(self) -> None:
        worker = DicomLoaderWorker(path=Path("/test.dcm"))
        assert worker._frame_index == 0

    def test_has_signals(self) -> None:
        worker = DicomLoaderWorker(path=Path("/test.dcm"))
        assert hasattr(worker.signals, "finished")
        assert hasattr(worker.signals, "failed")
        assert hasattr(worker.signals, "batch_finished")

    def test_auto_delete(self) -> None:
        worker = DicomLoaderWorker(path=Path("/test.dcm"))
        assert worker.autoDelete() is False
