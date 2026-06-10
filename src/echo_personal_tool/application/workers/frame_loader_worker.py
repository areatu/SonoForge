"""Background worker for loading a single frame from disk."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
from echo_personal_tool.infrastructure.video_reader import VideoReader


class FrameLoaderSignals(QObject):
    finished = Signal(np.ndarray)
    failed = Signal(str)


class FrameLoaderWorker(QRunnable):
    """Load a frame from either a DICOM or MP4 file on a worker thread."""

    def __init__(self, path: Path, frame_index: int = 0, source_kind: str = "dicom") -> None:
        super().__init__()
        self._path = Path(path)
        self._frame_index = frame_index
        self._source_kind = source_kind
        self.signals = FrameLoaderSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            if self._source_kind == "mp4":
                with VideoReader() as reader:
                    reader.open(self._path)
                    pixels = reader.read_frame(self._frame_index)
            else:
                reader = DicomReaderImpl()
                pixels = reader.read_pixels(self._path, frame_index=self._frame_index)
            self.signals.finished.emit(pixels)
        except Exception as exc:  # noqa: BLE001 - surface to UI
            self.signals.failed.emit(str(exc))
