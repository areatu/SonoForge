"""Background worker for loading a single frame from disk."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
from echo_personal_tool.infrastructure.image_reader import ImageReader
from echo_personal_tool.infrastructure.video_reader import get_thread_video_reader


class FrameLoaderSignals(QObject):
    finished = Signal(np.ndarray)
    failed = Signal(str)


class FrameLoaderWorker(QRunnable):
    """Load a frame from DICOM, MP4, JPEG, or PNG on a worker thread."""

    def __init__(
        self,
        path: Path,
        frame_index: int = 0,
        media_format: str = "dicom",
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._path = Path(path)
        self._frame_index = frame_index
        self._media_format = media_format
        # Parent keeps signals alive until queued cross-thread delivery completes.
        self.signals = FrameLoaderSignals(parent)
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            if self._media_format == "mp4":
                reader = get_thread_video_reader()
                reader.open(self._path)
                pixels = reader.read_frame(self._frame_index)
            elif self._media_format in ("jpeg", "png"):
                pixels = ImageReader().read_pixels(self._path)
            else:
                reader = DicomReaderImpl()
                pixels = reader.read_pixels(self._path, frame_index=self._frame_index)
            self.signals.finished.emit(np.ascontiguousarray(pixels).copy())
        except Exception as exc:  # noqa: BLE001 - surface to UI
            self.signals.failed.emit(str(exc))
