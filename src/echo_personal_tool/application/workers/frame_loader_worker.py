"""Background worker for loading frames from disk (single or batch)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session
from echo_personal_tool.infrastructure.image_reader import ImageReader
from echo_personal_tool.infrastructure.video_reader import get_thread_video_reader

logger = logging.getLogger(__name__)

_DECODE_WORKERS = 4


class FrameLoaderSignals(QObject):
    finished = Signal(np.ndarray)
    batch_finished = Signal(list)
    failed = Signal(str)


class FrameLoaderWorker(QRunnable):
    """Load frames from DICOM, MP4, JPEG, or PNG on a worker thread.

    Single mode: decode one frame, emit ``finished``.
    Batch mode (batch_size > 0): decode consecutive frames starting at
    ``frame_index``, emit ``batch_finished`` with ``[(idx, pixels), ...]``.
    """

    def __init__(
        self,
        path: Path,
        frame_index: int = 0,
        media_format: str = "dicom",
        parent: QObject | None = None,
        total_frames: int = 0,
        batch_size: int = 0,
    ) -> None:
        super().__init__()
        self._path = Path(path)
        self._frame_index = frame_index
        self._media_format = media_format
        self._total_frames = total_frames
        self._batch_size = batch_size
        self.signals = FrameLoaderSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            if self._batch_size > 0 and self._media_format in ("dicom", "mp4"):
                self._run_batch()
            else:
                self._run_single()
        except Exception as exc:  # noqa: BLE001
            logger.exception("FrameLoader failed for %s", self._path)
            self.signals.failed.emit(str(exc))

    def _run_single(self) -> None:
        if self._media_format == "mp4":
            reader = get_thread_video_reader()
            reader.open(self._path)
            pixels = reader.read_frame(self._frame_index)
        elif self._media_format in ("jpeg", "png"):
            pixels = ImageReader().read_pixels(self._path)
        else:
            session = get_thread_dicom_session()
            session.open(self._path)
            pixels = session.decode_single_frame(self._frame_index)
        self.signals.finished.emit(np.ascontiguousarray(pixels))

    def _run_batch(self) -> None:
        end = min(self._frame_index + self._batch_size, self._total_frames)
        results: list[tuple[int, np.ndarray]] = []

        if self._media_format == "mp4":
            reader = get_thread_video_reader()
            reader.open(self._path)
            for i in range(self._frame_index, end):
                pixels = reader.read_frame(i)
                results.append((i, np.ascontiguousarray(pixels)))
        elif self._media_format == "dicom":
            # Parallel decode: each thread opens its own session (thread-local),
            # _raw_bytes is immutable so concurrent reads are safe.
            indices = list(range(self._frame_index, end))

            def _decode_frame(idx: int) -> tuple[int, np.ndarray]:
                session = get_thread_dicom_session()
                session.open(self._path)
                return idx, np.ascontiguousarray(session.decode_single_frame(idx))

            with ThreadPoolExecutor(max_workers=_DECODE_WORKERS) as pool:
                futures = {pool.submit(_decode_frame, i): i for i in indices}
                for future in as_completed(futures):
                    idx, pixels = future.result()
                    results.append((idx, pixels))

        self.signals.batch_finished.emit(results)
