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
from pydicom.errors import InvalidDicomError
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from echo_personal_tool.application.server_io import (
    ServerSettings,
    close_dicom_web_client,
    make_dicom_retrieve_service,
    make_dicom_web_client,
    make_dimse_client,
)
from echo_personal_tool.application.services.dicom_retrieve_service import RetrieveError
from echo_personal_tool.domain.ports import DicomWebClient
from echo_personal_tool.infrastructure.safe_diagnostics import log_boundary_failure

logger = logging.getLogger(__name__)

ORIGINAL_COPY_FAILURE_CODE = "original_copy_failed"

# The retrieve service folds every adapter/network error into RetrieveError and
# re-raises only TransportPolicyError; the remaining types come from DICOM
# parsing and file I/O. Keeping the list explicit avoids adding a new broad
# handler to the application-layer ratchet.
_COPY_ERRORS = (
    RetrieveError,
    InvalidDicomError,
    OSError,
    ValueError,
    EOFError,
    RuntimeError,
)


class OriginalDicomCopySignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class OriginalDicomCopyWorker(QRunnable):
    """Download one original DICOM instance and save it verbatim."""

    def __init__(
        self,
        settings: ServerSettings,
        source_path: Path,
        series_uid: str,
        instance_uid: str,
        destination: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._source_path = Path(source_path)
        self._series_uid = series_uid
        self._instance_uid = instance_uid
        self._destination = Path(destination)
        self.signals = OriginalDicomCopySignals(parent)
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        web: DicomWebClient | None = None
        try:
            probe = pydicom.dcmread(str(self._source_path), stop_before_pixels=True, force=True)
            study_uid = str(getattr(probe, "StudyInstanceUID", "") or "")
            if not study_uid:
                raise ValueError("working DICOM has no StudyInstanceUID")

            web = make_dicom_web_client(self._settings)
            dimse = make_dimse_client(self._settings)
            service = make_dicom_retrieve_service(
                self._settings,
                web_client=web,
                dimse_client=dimse,
            )
            data = service.retrieve_instance(study_uid, self._series_uid, self._instance_uid)
            downloaded = pydicom.dcmread(BytesIO(data), stop_before_pixels=True, force=True)
            returned_uid = str(getattr(downloaded, "SOPInstanceUID", "") or "")
            if returned_uid and returned_uid != self._instance_uid:
                raise ValueError("retrieved instance UID does not match the request")
            self._destination.parent.mkdir(parents=True, exist_ok=True)
            self._destination.write_bytes(data)
        except _COPY_ERRORS as exc:
            log_boundary_failure(logger, "dcm.export", exc, code="unexpected", level=logging.ERROR)
            self.signals.failed.emit(ORIGINAL_COPY_FAILURE_CODE)
        else:
            self.signals.finished.emit(str(self._destination))
        finally:
            if web is not None:
                close_dicom_web_client(web)
