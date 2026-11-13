"""Background worker that decodes DICOM frames progressively."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.infrastructure.dicom_frame_geometry import DicomFrameGeometryError
from echo_personal_tool.infrastructure.dicom_session import DicomDecodeCancelled, get_thread_dicom_session
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)


class DicomDecodeSignals(QObject):
    first_frame_ready = Signal(int, object, object)  # request_id, path, first_frame
    progress = Signal(int, int)  # current, total
    finished = Signal(int, object, object)  # request_id, path, all_frames
    cancelled = Signal(int)
    failed = Signal(int, str)


#: Static UI-safe failure message (QH-4a ER-09): the worker never emits raw
#: exception text (paths, codec errors) into the ``failed`` signal.
DICOM_DECODE_FAILURE_MESSAGE = "DICOM decode failed"
#: #475: a header whose single frame is above the per-frame limit, or whose geometry is
#: impossible, is refused before decoding — and the user is told which of the two it is.
DICOM_FRAME_TOO_LARGE_MESSAGE = "DICOM frame is larger than the viewer accepts"
DICOM_FRAME_INVALID_MESSAGE = "DICOM frame geometry is invalid"


def frame_geometry_failure_message(error: DicomFrameGeometryError) -> str:
    """Static UI text for a typed frame-geometry refusal (never the exception text)."""
    return DICOM_FRAME_TOO_LARGE_MESSAGE if error.code == "limit" else DICOM_FRAME_INVALID_MESSAGE


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
        self._cancel_event = threading.Event()
        self.signals = DicomDecodeSignals()
        self.setAutoDelete(True)

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self) -> None:
        """Withdraw this request; the session stops between frames and never publishes."""
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        t0 = time.perf_counter()
        session = None
        try:
            if self.cancelled:
                self.signals.cancelled.emit(self._request_id)
                return
            session = get_thread_dicom_session(self._path)
            session.open(self._path)
            if self.cancelled:
                session.release_heavy()
                self.signals.cancelled.emit(self._request_id)
                return

            t_meta = time.perf_counter()
            logger.debug("DICOM metadata parsed in %.1f ms", (t_meta - t0) * 1000)

            first_frame = session.decode_first_frame()
            t_first = time.perf_counter()
            logger.debug("First frame decoded in %.1f ms", (t_first - t_meta) * 1000)
            if self.cancelled:
                session.release_heavy()
                self.signals.cancelled.emit(self._request_id)
                return

            self.signals.first_frame_ready.emit(
                self._request_id,
                self._path,
                first_frame,
            )
            total = session.frame_count

            if self._first_frame_only:
                self.signals.progress.emit(total, total)
                return

            frames = session.decode_all_frames(cancel_check=lambda: self.cancelled)
            session.release_heavy()
            if self.cancelled:
                self.signals.cancelled.emit(self._request_id)
                return
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
        except DicomDecodeCancelled:
            if session is not None:
                session.release_heavy()
            self.signals.cancelled.emit(self._request_id)
        except DicomFrameGeometryError as exc:
            log_boundary_failure(logger, "dicom.decode", exc, code=exc.code)
            self.signals.failed.emit(self._request_id, frame_geometry_failure_message(exc))
        except Exception as exc:  # noqa: BLE001 - safe event only, never to the UI
            log_boundary_failure(logger, "dicom.decode", exc, code="unexpected")
            self.signals.failed.emit(self._request_id, DICOM_DECODE_FAILURE_MESSAGE)
