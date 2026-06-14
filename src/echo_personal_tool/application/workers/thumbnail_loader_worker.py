"""Background worker for series/instance thumbnail generation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, Signal, Slot
from PySide6.QtGui import QImage

from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
from echo_personal_tool.infrastructure.image_reader import ImageReader
from echo_personal_tool.infrastructure.pixel_utils import bgr_to_rgb, is_color_frame
from echo_personal_tool.infrastructure.video_reader import get_thread_video_reader

THUMBNAIL_SIZE = 128


def thumbnail_frame_index(number_of_frames: int) -> int:
    """Pick first frame for single-frame instances, middle frame otherwise."""
    if number_of_frames <= 1:
        return 0
    return (number_of_frames - 1) // 2


def numpy_pixels_to_qimage(pixels: np.ndarray, size: int = THUMBNAIL_SIZE) -> QImage:
    """Convert a grayscale or BGR frame to a scaled QImage preserving aspect ratio.

    ``size`` is the maximum width and height of the bounding box; the result fits
    inside ``size x size`` without stretching.
    """
    arr = np.ascontiguousarray(pixels)
    if is_color_frame(arr):
        rgb = bgr_to_rgb(arr)
        height, width, _channels = rgb.shape
        qimg = QImage(
            rgb.data,
            width,
            height,
            width * 3,
            QImage.Format.Format_RGB888,
        ).copy()
    else:
        if arr.ndim == 3:
            arr = arr[:, :, 0]
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


# Backward-compatible alias for existing tests and imports.
numpy_grayscale_to_qimage = numpy_pixels_to_qimage


class ThumbnailLoaderSignals(QObject):
    finished = Signal(str, QImage)
    failed = Signal(str, str)


class ThumbnailLoaderWorker(QRunnable):
    """Load a frame and return a scaled QImage for tree icons."""

    def __init__(
        self,
        path: Path,
        sop_instance_uid: str,
        number_of_frames: int = 1,
        media_format: str = "dicom",
        preview_size: int = 96,
        preview_only: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._path = Path(path)
        self._sop_instance_uid = sop_instance_uid
        self._number_of_frames = number_of_frames
        self._media_format = media_format
        self._preview_size = int(preview_size)
        self._preview_only = bool(preview_only)
        self.signals = ThumbnailLoaderSignals(parent)
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            frame_index = thumbnail_frame_index(self._number_of_frames)
            if self._media_format == "mp4":
                reader = get_thread_video_reader()
                reader.open(self._path)
                pixels = reader.read_frame(frame_index)
            elif self._media_format in ("jpeg", "png"):
                pixels = ImageReader().read_pixels(self._path)
            else:
                reader = DicomReaderImpl()
                pixels = reader.read_pixels(self._path, frame_index=frame_index)
            # MVP is strict preview-only: preview_only=False is kept for compatibility
            # but currently does not switch to full-size rendering.
            image = numpy_pixels_to_qimage(pixels, size=self._preview_size)
            self.signals.finished.emit(self._sop_instance_uid, image)
        except Exception as exc:  # noqa: BLE001 - surface to UI
            self.signals.failed.emit(self._sop_instance_uid, str(exc))
