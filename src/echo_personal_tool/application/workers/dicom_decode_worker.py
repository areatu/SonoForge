"""Background worker that decodes DICOM frames progressively."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session

logger = logging.getLogger(__name__)


class DicomDecodeSignals(QObject):
    first_frame_ready = Signal(int, object, object)  # request_id, path, first_frame
    progress = Signal(int, int)  # current, total
    finished = Signal(int, object, object)  # request_id, path, all_frames
    failed = Signal(int, str)


class DicomDecodeWorker(QRunnable):
    """Decode DICOM progressively: first frame immediately, then all frames in parallel."""

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
        self.signals = DicomDecodeSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            session = get_thread_dicom_session()
            session.open(self._path)

            t_meta = time.perf_counter()
            logger.debug(
                "DICOM metadata parsed in %.1f ms", (t_meta - t0) * 1000
            )

            first_frame = session.decode_first_frame()
            t_first = time.perf_counter()
            logger.debug(
                "First frame decoded in %.1f ms", (t_first - t_meta) * 1000
            )

            self.signals.first_frame_ready.emit(
                self._request_id,
                self._path,
                first_frame,
            )
            total = session.frame_count

            if self._first_frame_only:
                self.signals.progress.emit(total, total)
                return

            frames = session.decode_all_frames()
            t_all = time.perf_counter()
            logger.debug(
                "All %d frames decoded in %.1f ms",
                total,
                (t_all - t_first) * 1000,
            )

            self.signals.progress.emit(total, total)
            self.signals.finished.emit(
                self._request_id,
                self._path,
                frames,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("DICOM decode failed for %s", self._path)
            self.signals.failed.emit(self._request_id, str(exc))
