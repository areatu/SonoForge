"""Background worker for uploading DICOM files to a server."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.domain.models.orthanc import StowResult
from echo_personal_tool.domain.ports import DicomUploadClient

logger = logging.getLogger(__name__)


class DicomUploadSignals(QObject):
    progress = Signal(int, int)  # (current, total)
    finished = Signal(object)  # StowResult
    failed = Signal(str)


class DicomUploadWorker(QRunnable):
    """Upload DICOM files to a server via DicomUploadClient (STOW-RS or C-STORE)."""

    def __init__(
        self,
        files: list[bytes],
        uploader: DicomUploadClient,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._files = files
        self._uploader = uploader
        self.signals = DicomUploadSignals(parent)
        self._cancelled = False
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            total = len(self._files)
            success = 0
            failed_uids: list[str] = []

            for i, dicom_bytes in enumerate(self._files):
                if self._cancelled:
                    break
                ok = self._uploader.upload_instance(dicom_bytes)
                if ok:
                    success += 1
                self.signals.progress.emit(i + 1, total)

            if self._cancelled:
                self.signals.failed.emit("Upload cancelled")
            else:
                self.signals.finished.emit(
                    StowResult(success_count=success, failed_uids=failed_uids)
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("DicomUploadWorker failed")
            self.signals.failed.emit(str(exc))
