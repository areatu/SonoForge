"""Background worker for uploading DICOM files to a server."""

from __future__ import annotations

import logging
from typing import Literal

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.domain.models.orthanc import StowResult
from echo_personal_tool.domain.ports import DicomUploadClient, DicomWebClient

logger = logging.getLogger(__name__)

UploadProtocol = Literal["stow", "dimse"]


class DicomUploadSignals(QObject):
    progress = Signal(int, int)  # (current, total)
    finished = Signal(object)  # StowResult
    failed = Signal(str)


class DicomUploadWorker(QRunnable):
    """Upload DICOM files via STOW-RS batch or sequential C-STORE."""

    def __init__(
        self,
        files: list[bytes],
        *,
        uploader: DicomUploadClient | None = None,
        stow_client: DicomWebClient | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        if (uploader is None) == (stow_client is None):
            raise ValueError("Provide exactly one of uploader or stow_client")
        self._files = files
        self._uploader = uploader
        self._stow_client = stow_client
        self.signals = DicomUploadSignals(parent)
        self._cancelled = False
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            total = len(self._files)
            if total == 0:
                self.signals.finished.emit(StowResult(0))
                return

            if self._stow_client is not None:
                if self._cancelled:
                    self.signals.failed.emit("Upload cancelled")
                    return
                result = self._stow_client.stow_instances(self._files)
                self.signals.progress.emit(total, total)
                self.signals.finished.emit(result)
                return

            success = 0
            failed_uids: list[str] = []
            for i, dicom_bytes in enumerate(self._files):
                if self._cancelled:
                    self.signals.failed.emit("Upload cancelled")
                    return
                if self._uploader is not None and self._uploader.upload_instance(dicom_bytes):
                    success += 1
                self.signals.progress.emit(i + 1, total)

            self.signals.finished.emit(
                StowResult(success_count=success, failed_uids=failed_uids)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("DicomUploadWorker failed")
            self.signals.failed.emit(str(exc))
