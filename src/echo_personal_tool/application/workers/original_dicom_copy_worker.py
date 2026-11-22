"""Background copy of the original compressed DICOM instance by UIDs.

The gallery works on de-identified files; after a disk export the cached
original is gone.  Copying the working file would duplicate the expanded,
uncompressed cine, so this worker re-downloads the exact instance from the
configured PACS and writes those bytes to the user's destination.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import pydicom
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.application.server_io import (
    close_dicom_web_client,
    make_dicom_retrieve_service,
    make_dicom_web_client,
    make_dimse_client,
)
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)

ORIGINAL_COPY_FAILURE_CODE = "original_copy_failed"


class OriginalDicomCopySignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class OriginalDicomCopyWorker(QRunnable):
    """Download one original DICOM instance and save it verbatim."""

    def __init__(
        self,
        settings: object,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
        destination: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._study_uid = study_uid
        self._series_uid = series_uid
        self._instance_uid = instance_uid
        self._destination = Path(destination)
        self.signals = OriginalDicomCopySignals(parent)
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        web = None
        try:
            web = make_dicom_web_client(self._settings)  # type: ignore[arg-type]
            dimse = make_dimse_client(self._settings)  # type: ignore[arg-type]
            service = make_dicom_retrieve_service(
                self._settings,  # type: ignore[arg-type]
                web_client=web,
                dimse_client=dimse,
            )
            data = service.retrieve_instance(
                self._study_uid, self._series_uid, self._instance_uid
            )
            probe = pydicom.dcmread(BytesIO(data), stop_before_pixels=True, force=True)
            returned_uid = str(getattr(probe, "SOPInstanceUID", "") or "")
            if returned_uid and returned_uid != self._instance_uid:
                raise ValueError("retrieved instance UID does not match the request")
            self._destination.parent.mkdir(parents=True, exist_ok=True)
            self._destination.write_bytes(data)
        except Exception as exc:  # noqa: BLE001 - worker boundary reports the failure
            log_boundary_failure(
                logger, "dicom.copy_original", exc, code="unexpected", level=logging.ERROR
            )
            self.signals.failed.emit(ORIGINAL_COPY_FAILURE_CODE)
        else:
            self.signals.finished.emit(str(self._destination))
        finally:
            if web is not None:
                close_dicom_web_client(web)
