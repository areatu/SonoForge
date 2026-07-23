"""Background worker for heart rate estimation from cine echo."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

logger = logging.getLogger(__name__)

_MAX_FRAMES_FOR_OPTICAL_FLOW = 60


class HeartRateSignals(QObject):
    finished = Signal(float, float, str)  # bpm, confidence, method
    failed = Signal(str)


class HeartRateWorker(QRunnable):
    """Estimate heart rate from DICOM/MP4 in a background thread."""

    def __init__(
        self,
        source_path: Path,
        media_format: str,
        frame_time_ms: float | None = None,
        contour_areas: list[float] | None = None,
        contour_frame_indices: list[int] | None = None,
    ) -> None:
        super().__init__()
        self._source_path = Path(source_path)
        self._media_format = media_format
        self._frame_time_ms = frame_time_ms
        self._contour_areas = contour_areas
        self._contour_frame_indices = contour_frame_indices
        self.signals = HeartRateSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        from echo_personal_tool.domain.services.heart_rate import (
            estimate_hr_area_time,
            estimate_hr_optical_flow,
        )

        try:
            fps = 1000.0 / self._frame_time_ms if self._frame_time_ms else 30.0

            # Try area-time first if contours are available (instant)
            if self._contour_areas and len(self._contour_areas) >= 4:
                result = estimate_hr_area_time(
                    self._contour_areas,
                    fps=fps,
                    frame_indices=self._contour_frame_indices,
                )
                if result.bpm > 0:
                    self.signals.finished.emit(result.bpm, result.confidence, result.method)
                    return

            # Fall back to optical flow (subsampled)
            frames = self._load_frames_subsampled()
            if not frames:
                self.signals.failed.emit("No frames available")
                return

            result = estimate_hr_optical_flow(frames, fps=fps)
            if result.bpm > 0:
                self.signals.finished.emit(result.bpm, result.confidence, result.method)
            else:
                self.signals.failed.emit("Could not estimate heart rate")

        except Exception as exc:  # noqa: BLE001
            logger.exception("Heart rate estimation failed for %s", self._source_path)
            self.signals.failed.emit(str(exc))

    def _load_frames_subsampled(self) -> list[np.ndarray]:
        """Load frames and subsample to _MAX_FRAMES_FOR_OPTICAL_FLOW."""
        if self._media_format == "mp4":
            all_frames = self._load_from_mp4()
        else:
            all_frames = self._load_from_dicom()

        if len(all_frames) <= _MAX_FRAMES_FOR_OPTICAL_FLOW:
            return all_frames

        # Evenly subsample
        n = len(all_frames)
        target = _MAX_FRAMES_FOR_OPTICAL_FLOW
        indices = np.linspace(0, n - 1, target, dtype=int)
        return [all_frames[i] for i in indices]

    def _load_from_mp4(self) -> list[np.ndarray]:
        cap = cv2.VideoCapture(str(self._source_path))
        try:
            if not cap.isOpened():
                return []
            frames: list[np.ndarray] = []
            while True:
                ok, bgr = cap.read()
                if not ok or bgr is None:
                    break
                gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                frames.append(gray)
            return frames
        finally:
            cap.release()

    def _load_from_dicom(self) -> list[np.ndarray]:
        from echo_personal_tool.infrastructure.dicom_session import (
            get_thread_dicom_session,
        )

        session = get_thread_dicom_session()
        session.open(self._source_path)
        all_frames = session.decode_all_frames()
        result: list[np.ndarray] = []
        for frame in all_frames:
            if frame.ndim == 3:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.shape[2] == 3 else np.mean(frame, axis=2).astype(np.uint8)
            else:
                gray = frame.astype(np.uint8)
            result.append(gray)
        return result
