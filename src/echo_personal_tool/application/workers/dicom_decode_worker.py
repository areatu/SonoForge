"""Background worker that decodes DICOM frames progressively."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.application.localization import tr
from echo_personal_tool.infrastructure.dicom_session import get_thread_dicom_session
from echo_personal_tool.infrastructure.pixel_budget import StudyTooLargeError
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)


class DicomDecodeSignals(QObject):
    first_frame_ready = Signal(int, object, object)  # request_id, path, first_frame
    progress = Signal(int, int)  # current, total
    finished = Signal(int, object, object)  # request_id, path, all_frames
    failed = Signal(int, str)


#: Static UI-safe failure message (QH-4a ER-09): the worker never emits raw
#: exception text (paths, codec errors) into the ``failed`` signal.
DICOM_DECODE_FAILURE_MESSAGE = "DICOM decode failed"


def _study_too_large_message(error: StudyTooLargeError) -> str:
    """Localized, path-free explanation of the decode-budget refusal (S3-04)."""
    return tr(
        "status.study_too_large",
        megapixels=f"{error.megapixels:.0f}",
        limit=f"{error.limit_megapixels:.0f}",
    )


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
            session = get_thread_dicom_session(self._path)
            session.open(self._path)

            t_meta = time.perf_counter()
            logger.debug("DICOM metadata parsed in %.1f ms", (t_meta - t0) * 1000)

            first_frame = session.decode_first_frame()
            t_first = time.perf_counter()
            logger.debug("First frame decoded in %.1f ms", (t_first - t_meta) * 1000)

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
            session.release_heavy()
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
        except StudyTooLargeError as exc:
            # The budget refused the study before decoding: the user gets the
            # measured size and the limit, never a path or a raw exception (S3-04).
            log_boundary_failure(logger, "dicom.decode", exc, code=exc.code, level=logging.WARNING)
            self.signals.failed.emit(self._request_id, _study_too_large_message(exc))
        except Exception as exc:  # noqa: BLE001 - safe event only, never to the UI
            log_boundary_failure(logger, "dicom.decode", exc, code="unexpected")
            self.signals.failed.emit(self._request_id, DICOM_DECODE_FAILURE_MESSAGE)
