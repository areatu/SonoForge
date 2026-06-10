"""Background worker for series/instance thumbnail generation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, Signal, Slot
from PySide6.QtGui import QImage

from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl

THUMBNAIL_SIZE = 64


def thumbnail_frame_index(number_of_frames: int) -> int:
    """Pick first frame for single-frame instances, middle frame otherwise."""
    if number_of_frames <= 1:
        return 0
    return (number_of_frames - 1) // 2


def numpy_grayscale_to_qimage(pixels: np.ndarray, size: int = THUMBNAIL_SIZE) -> QImage:
    """Convert a 2D grayscale array to a scaled QImage."""
    if pixels.ndim != 2:
        msg = f"Expected 2D grayscale array, got shape {pixels.shape}"
        raise ValueError(msg)

    arr = np.ascontiguousarray(pixels)
    if arr.dtype != np.uint8:
        lo = float(arr.min())
        hi = float(arr.max())
        if hi > lo:
            arr = ((arr.astype(np.float64) - lo) / (hi - lo) * 255.0).astype(np.uint8)
        else:
            arr = np.zeros(arr.shape, dtype=np.uint8)
    else:
        arr = arr.copy()

    height, width = arr.shape
    qimg = QImage(arr.data, width, height, width, QImage.Format.Format_Grayscale8).copy()
    return qimg.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class ThumbnailLoaderSignals(QObject):
    finished = Signal(str, QImage)
    failed = Signal(str, str)


class ThumbnailLoaderWorker(QRunnable):
    """Load a DICOM frame and return a scaled QImage for tree icons."""

    def __init__(
        self,
        path: Path,
        sop_instance_uid: str,
        number_of_frames: int = 1,
    ) -> None:
        super().__init__()
        self._path = Path(path)
        self._sop_instance_uid = sop_instance_uid
        self._number_of_frames = number_of_frames
        self.signals = ThumbnailLoaderSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            frame_index = thumbnail_frame_index(self._number_of_frames)
            reader = DicomReaderImpl()
            pixels = reader.read_pixels(self._path, frame_index=frame_index)
            image = numpy_grayscale_to_qimage(pixels)
            self.signals.finished.emit(self._sop_instance_uid, image)
        except Exception as exc:  # noqa: BLE001 - surface to UI
            self.signals.failed.emit(self._sop_instance_uid, str(exc))
