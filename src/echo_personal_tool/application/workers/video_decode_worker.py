"""Background worker that decodes MP4 frames progressively."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.pixel_utils import to_bgr_uint8


class VideoDecodeSignals(QObject):
    first_frame_ready = Signal(int, object, object)  # request_id, path, first_frame
    progress = Signal(int, int)  # current, total
    finished = Signal(int, object, object)  # request_id, path, all_frames
    failed = Signal(int, str)


class VideoDecodeWorker(QRunnable):
    """Decode MP4 progressively: first frame immediately, then all frames."""

    def __init__(
        self,
        path: Path,
        request_id: int,
        parent: QObject | None = None,
        first_frame_only: bool = False,
    ) -> None:
        super().__init__()
        self._path = Path(path)
        self._request_id = request_id
        self._first_frame_only = first_frame_only
        self.signals = VideoDecodeSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        cap = None
        try:
            import cv2

            cap = cv2.VideoCapture(str(self._path))
            if not cap.isOpened():
                raise OSError(f"Cannot open video: {self._path}")

            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total <= 0:
                raise OSError(f"Cannot determine frame count: {self._path}")

            ok, bgr = cap.read()
            if not ok or bgr is None:
                raise OSError(f"Cannot read first frame: {self._path}")

            first_frame = to_bgr_uint8(bgr)
            self.signals.first_frame_ready.emit(
                self._request_id,
                self._path,
                first_frame,
            )

            if self._first_frame_only:
                self.signals.progress.emit(total, total)
                return

            h, w = first_frame.shape[:2]
            result = np.empty((total, h, w, first_frame.shape[2]), dtype=np.uint8)
            result[0] = first_frame
            count = 1
            for i in range(1, total):
                ok, bgr = cap.read()
                if not ok or bgr is None:
                    break
                result[count] = to_bgr_uint8(bgr)
                count += 1
                if i % 10 == 0 or i == total - 1:
                    self.signals.progress.emit(i + 1, total)

            if count == 0:
                raise OSError(f"No frames decoded from: {self._path}")

            self.signals.finished.emit(
                self._request_id,
                self._path,
                np.ascontiguousarray(result[:count]),
            )
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self._request_id, str(exc))
        finally:
            if cap is not None:
                cap.release()
