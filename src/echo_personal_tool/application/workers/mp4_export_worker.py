"""Background worker that exports DICOM/MP4 to MP4 file."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

logger = logging.getLogger(__name__)


class Mp4ExportSignals(QObject):
    progress = Signal(int, int)  # current_frame, total_frames
    finished = Signal(str)  # output_path
    failed = Signal(str)  # error message


class Mp4ExportWorker(QRunnable):
    """Export DICOM or MP4 source to MP4 file in a background thread."""

    def __init__(
        self,
        source_path: Path,
        dest_path: str,
        media_format: str,
        frame_time_ms: float | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._source_path = Path(source_path)
        self._dest_path = dest_path
        self._media_format = media_format
        self._frame_time_ms = frame_time_ms
        self.signals = Mp4ExportSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            if self._media_format == "mp4":
                self._export_from_mp4()
            else:
                self._export_from_dicom()
        except Exception as exc:  # noqa: BLE001
            logger.exception("MP4 export failed for %s", self._source_path)
            self.signals.failed.emit(str(exc))

    def _export_from_mp4(self) -> None:
        cap = cv2.VideoCapture(str(self._source_path))
        try:
            if not cap.isOpened():
                raise OSError(f"Cannot open video: {self._source_path}")

            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(self._dest_path, fourcc, fps, (w, h))
            try:
                i = 0
                while True:
                    ok, bgr = cap.read()
                    if not ok or bgr is None:
                        break
                    writer.write(bgr)
                    i += 1
                    if i % 5 == 0 or i == total:
                        self.signals.progress.emit(i, total)
            finally:
                writer.release()
        finally:
            cap.release()

        self.signals.finished.emit(self._dest_path)

    def _export_from_dicom(self) -> None:
        from echo_personal_tool.infrastructure.dicom_session import (
            get_thread_dicom_session,
        )

        session = get_thread_dicom_session()
        session.open(self._source_path)
        total = session.frame_count

        first_frame = session.decode_first_frame()
        self.signals.progress.emit(1, total)

        if total <= 1:
            self._write_single_frame(first_frame, total)
            return

        fps = 1000.0 / self._frame_time_ms if self._frame_time_ms else 30.0
        h, w = first_frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(self._dest_path, fourcc, fps, (w, h))
        try:
            bgr = self._to_bgr(first_frame)
            writer.write(bgr)

            all_frames = session.decode_all_frames()
            for i, frame in enumerate(all_frames):
                if i == 0:
                    continue
                bgr = self._to_bgr(frame)
                writer.write(bgr)
                if i % 5 == 0 or i == total - 1:
                    self.signals.progress.emit(i + 1, total)
        finally:
            writer.release()

        self.signals.finished.emit(self._dest_path)

    def _write_single_frame(self, frame: np.ndarray, total: int) -> None:
        fps = 1000.0 / self._frame_time_ms if self._frame_time_ms else 30.0
        h, w = frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(self._dest_path, fourcc, fps, (w, h))
        try:
            bgr = self._to_bgr(frame)
            writer.write(bgr)
            self.signals.progress.emit(1, total)
        finally:
            writer.release()
        self.signals.finished.emit(self._dest_path)

    @staticmethod
    def _to_bgr(frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        if frame.ndim == 3 and frame.shape[2] == 3:
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        if frame.ndim == 3 and frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        return frame
