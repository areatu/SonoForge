"""Background worker for optical flow contour refinement."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

logger = logging.getLogger(__name__)


class OpticalFlowRefineSignals(QObject):
    finished = Signal(list)  # refined_points: list[(x, y)]
    failed = Signal(str)


class OpticalFlowRefineWorker(QRunnable):
    """Refine contour points using optical flow in a background thread."""

    def __init__(
        self,
        source_path: Path,
        media_format: str,
        contour_points: list[tuple[float, float]],
        current_frame_idx: int,
        total_frames: int,
        frame_time_ms: float | None = None,
    ) -> None:
        super().__init__()
        self._source_path = Path(source_path)
        self._media_format = media_format
        self._contour_points = list(contour_points)
        self._current_frame_idx = current_frame_idx
        self._total_frames = total_frames
        self._frame_time_ms = frame_time_ms
        self.signals = OpticalFlowRefineSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            from echo_personal_tool.domain.services.optical_flow_refine import (
                refine_contour_with_optical_flow,
            )

            fps = 1000.0 / self._frame_time_ms if self._frame_time_ms else 30.0

            # Load neighboring frames (±3 frames from current)
            frames = self._load_neighbor_frames()
            if not frames or len(frames) < 3:
                self.signals.finished.emit(self._contour_points)
                return

            # Find the index of current_frame_idx in loaded frames
            local_idx = min(3, len(frames) // 2)

            refined = refine_contour_with_optical_flow(
                frames,
                self._contour_points,
                current_frame_idx=local_idx,
                fps=fps,
                roi_half_size=5,
                shift_fraction=0.4,
                max_shift_px=3.0,
            )

            self.signals.finished.emit(refined)

        except Exception as exc:  # noqa: BLE001
            logger.exception("Optical flow refinement failed for %s", self._source_path)
            # On failure, return original points unchanged
            self.signals.finished.emit(self._contour_points)

    def _load_neighbor_frames(self) -> list[np.ndarray]:
        """Load up to 7 frames centered on current_frame_idx."""
        neighbor_range = 3
        start = max(0, self._current_frame_idx - neighbor_range)
        end = min(self._total_frames - 1, self._current_frame_idx + neighbor_range)
        target_indices = list(range(start, end + 1))

        if self._media_format == "mp4":
            return self._load_from_mp4(target_indices)
        return self._load_from_dicom(target_indices)

    def _load_from_mp4(self, indices: list[int]) -> list[np.ndarray]:
        cap = cv2.VideoCapture(str(self._source_path))
        try:
            if not cap.isOpened():
                return []
            frames: list[np.ndarray] = []
            idx_set = set(indices)
            i = 0
            while True:
                ok, bgr = cap.read()
                if not ok or bgr is None:
                    break
                if i in idx_set:
                    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                    frames.append(gray)
                i += 1
                if i > max(indices):
                    break
            return frames
        finally:
            cap.release()

    def _load_from_dicom(self, indices: list[int]) -> list[np.ndarray]:
        from echo_personal_tool.infrastructure.dicom_session import (
            get_thread_dicom_session,
        )

        session = get_thread_dicom_session()
        session.open(self._source_path)
        all_frames = session.decode_all_frames()
        result: list[np.ndarray] = []
        for idx in indices:
            if 0 <= idx < len(all_frames):
                frame = all_frames[idx]
                if frame.ndim == 3:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.shape[2] == 3 else np.mean(frame, axis=2).astype(np.uint8)
                else:
                    gray = frame.astype(np.uint8)
                result.append(gray)
        return result
