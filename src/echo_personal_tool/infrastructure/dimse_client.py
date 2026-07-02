"""DIMSE client implementation using pynetdicom."""

from __future__ import annotations

import logging
from io import BytesIO

import pydicom
from pydicom.dataset import Dataset
from pynetdicom import AE, StoragePresentationContexts
from pynetdicom.sop_class import (
    StudyRootQueryRetrieveInformationModelFind,
    Verification,
)

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo
from echo_personal_tool.infrastructure.dimse_find_mapper import (
    map_instance,
    map_series,
    map_study,
)
from echo_personal_tool.infrastructure.server_settings import ServerSettings

logger = logging.getLogger(__name__)


class DimseAssociationError(Exception):
    """Raised when DIMSE association fails."""


class PynetdimseClient:
    """DimseClient implementation via pynetdicom."""

    def __init__(
        self,
        *,
        ae_title: str = "ECHO2026",
        called_ae: str = "ORTHANC",
        host: str = "127.0.0.1",
        port: int = 4242,
        timeout_s: float = 10.0,
    ) -> None:
        self._ae_title = ae_title
        self._called_ae = called_ae
        self._host = host
        self._port = port
        self._timeout_s = timeout_s

    @classmethod
    def from_settings(cls, settings: ServerSettings) -> PynetdimseClient:
        return cls(
            ae_title=settings.dimse_ae_title,
            called_ae=settings.dimse_called_ae,
            host=settings.dimse_host,
            port=settings.dimse_port,
        )

    def _build_ae(self) -> AE:
        ae = AE(ae_title=self._ae_title)
        ae.acse_timeout = self._timeout_s
        ae.dimse_timeout = self._timeout_s
        ae.network_timeout = self._timeout_s
        ae.add_requested_context(Verification)
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        for ctx in StoragePresentationContexts:
            ae.add_requested_context(ctx.abstract_syntax)
        return ae

    def _associate(self) -> object:
        ae = self._build_ae()
        assoc = ae.associate(self._host, self._port, ae_title=self._called_ae)
        if not assoc.is_established:
            raise DimseAssociationError(
                f"Cannot associate with {self._host}:{self._port} "
                f"(called AE: {self._called_ae})"
            )
        return assoc

    def c_echo(self) -> bool:
        """C-ECHO — verify connection to DICOM node."""
        try:
            assoc = self._associate()
            try:
                status = assoc.send_c_echo()
                return status and status.Status == 0x0000
            finally:
                assoc.release()
        except DimseAssociationError:
            return False
        except Exception:  # noqa: BLE001
            logger.debug("C-ECHO failed", exc_info=True)
            return False

    def c_find_studies(
        self,
        *,
        patient_name: str | None = None,
        patient_id: str | None = None,
        study_date: str | None = None,
    ) -> list[StudyInfo]:
        """C-FIND at STUDY level using Study Root model."""
        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = ""
        ds.PatientName = f"*{patient_name}*" if patient_name else ""
        ds.PatientID = f"*{patient_id}*" if patient_id else ""
        ds.StudyDate = study_date or ""
        ds.StudyDescription = ""
        ds.NumberOfStudyRelatedSeries = ""
        return self._c_find(ds, map_study)

    def c_find_series(self, study_uid: str) -> list[SeriesInfo]:
        """C-FIND at SERIES level using Study Root model."""
        ds = Dataset()
        ds.QueryRetrieveLevel = "SERIES"
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = ""
        ds.Modality = ""
        ds.SeriesDescription = ""
        ds.NumberOfSeriesRelatedInstances = ""
        return self._c_find(ds, lambda identifier: map_series(identifier, study_uid))

    def c_find_instances(self, study_uid: str, series_uid: str) -> list[InstanceInfo]:
        """C-FIND at IMAGE level using Study Root model."""
        ds = Dataset()
        ds.QueryRetrieveLevel = "IMAGE"
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.SOPInstanceUID = ""
        return self._c_find(
            ds,
            lambda identifier: map_instance(identifier, study_uid, series_uid),
        )

    def _c_find(self, query_ds: Dataset, mapper) -> list:  # noqa: ANN001
        results: list = []
        try:
            assoc = self._associate()
            try:
                responses = assoc.send_c_find(
                    query_ds, StudyRootQueryRetrieveInformationModelFind
                )
                for status, identifier in responses:
                    if status is None:
                        break
                    if status.Status in (0xFF00, 0xFF01):
                        if identifier is not None:
                            results.append(mapper(identifier))
                    elif status.Status == 0x0000:
                        break
            finally:
                assoc.release()
        except DimseAssociationError:
            logger.warning("C-FIND: association failed")
        except Exception:  # noqa: BLE001
            logger.exception("C-FIND failed")
        return results

    def c_store(self, dicom_bytes: bytes) -> bool:
        """C-STORE a single DICOM object."""
        try:
            ds = pydicom.dcmread(BytesIO(dicom_bytes), force=True)
            assoc = self._associate()
            try:
                status = assoc.send_c_store(ds)
                return status and status.Status == 0x0000
            finally:
                assoc.release()
        except DimseAssociationError:
            return False
        except Exception:  # noqa: BLE001
            logger.exception("C-STORE failed")
            return False
