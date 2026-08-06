"""DIMSE client implementation using pynetdicom."""

from __future__ import annotations

import logging
from collections.abc import Callable
from io import BytesIO

import pydicom
from pydicom.dataset import Dataset
from pynetdicom import AE, StoragePresentationContexts, build_role, evt
from pynetdicom.sop_class import (
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelMove,
    Verification,
)

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo
from echo_personal_tool.domain.ports import CMoveResult
from echo_personal_tool.infrastructure.dimse_find_mapper import (
    map_instance,
    map_series,
    map_study,
)
from echo_personal_tool.infrastructure.server_settings import ServerSettings

logger = logging.getLogger(__name__)

_MOVE_DESTINATION_UNKNOWN = 0xA801


class DimseAssociationError(Exception):
    """Raised when DIMSE association fails."""


class DimseMoveDestinationError(DimseAssociationError):
    """Raised when PACS does not know the C-MOVE destination AE."""


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
        use_tls: bool = False,
        tls_verify: bool = True,
        tls_ca_path: str = "",
        tls_cert_path: str = "",
        tls_key_path: str = "",
    ) -> None:
        self._ae_title = ae_title
        self._called_ae = called_ae
        self._host = host
        self._port = port
        self._timeout_s = timeout_s
        self._use_tls = use_tls
        self._tls_verify = tls_verify
        self._tls_ca_path = tls_ca_path
        self._tls_cert_path = tls_cert_path
        self._tls_key_path = tls_key_path

    @classmethod
    def from_settings(cls, settings: ServerSettings) -> PynetdimseClient:
        return cls(
            ae_title=settings.dimse_ae_title,
            called_ae=settings.dimse_called_ae,
            host=settings.dimse_host,
            port=settings.dimse_port,
            timeout_s=settings.network_timeout,
            use_tls=settings.dimse_use_tls,
            tls_verify=settings.dimse_tls_verify,
            tls_ca_path=settings.dimse_tls_ca_path,
            tls_cert_path=settings.dimse_tls_cert_path,
            tls_key_path=settings.dimse_tls_key_path,
        )

    def _build_tls_context(
        self,
        *,
        use_tls: bool = False,
        verify: bool = True,
        ca_path: str = "",
        cert_path: str = "",
        key_path: str = "",
    ) -> tuple | None:
        """Build SSL context for TLS association."""
        if not use_tls:
            return None

        import ssl

        ssl_cx = ssl.create_default_context()
        if ca_path:
            ssl_cx.load_verify_locations(cafile=ca_path)
        if not verify:
            logger.warning("TLS certificate verification DISABLED — MITM risk!")
            ssl_cx.check_hostname = False
            ssl_cx.verify_mode = ssl.CERT_NONE
        if cert_path and key_path:
            ssl_cx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        return (ssl_cx, self._host)

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

    def _associate(self, tls_args: tuple | None = None) -> object:
        ae = self._build_ae()
        # Use provided tls_args or build from stored settings
        if tls_args is None and self._use_tls:
            tls_args = self._build_tls_context(
                use_tls=self._use_tls,
                verify=self._tls_verify,
                ca_path=self._tls_ca_path,
                cert_path=self._tls_cert_path,
                key_path=self._tls_key_path,
            )
        assoc = ae.associate(
            self._host,
            self._port,
            ae_title=self._called_ae,
            tls_args=tls_args,
        )
        if not assoc.is_established:
            raise DimseAssociationError(
                f"Cannot associate with {self._host}:{self._port} (called AE: {self._called_ae})"
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
                responses = assoc.send_c_find(query_ds, StudyRootQueryRetrieveInformationModelFind)
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

    def c_get_instance(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
        *,
        tls_args: tuple | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> bytes:
        """Download a single instance via C-GET."""
        received: dict[str, bytes] = {}

        def _handle_store(event: evt.Event) -> int:
            ds = event.dataset
            sop_uid = str(ds.SOPInstanceUID)
            file_meta = getattr(event, "file_meta", None)
            if file_meta is None:
                from pydicom.dataset import FileMetaDataset

                file_meta = FileMetaDataset()
            if not file_meta.get("TransferSyntaxUID"):
                from pydicom.uid import ExplicitVRLittleEndian

                file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds.file_meta = file_meta
            buf = BytesIO()
            ds.save_as(buf, enforce_file_format=True)
            received[sop_uid] = buf.getvalue()
            return 0x0000

        ae = AE(ae_title=self._ae_title)
        ae.acse_timeout = self._timeout_s
        ae.dimse_timeout = self._timeout_s
        ae.network_timeout = self._timeout_s
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
        for ctx in StoragePresentationContexts:
            ae.add_requested_context(ctx.abstract_syntax)

        assoc = ae.associate(
            self._host,
            self._port,
            ae_title=self._called_ae,
            ext_neg=[build_role(ctx.abstract_syntax, scp_role=True) for ctx in StoragePresentationContexts],
            evt_handlers=[(evt.EVT_C_STORE, _handle_store)],
            tls_args=tls_args,
        )
        if not assoc.is_established:
            raise DimseAssociationError(
                f"Cannot associate with {self._host}:{self._port} (called AE: {self._called_ae})"
            )

        try:
            ds = Dataset()
            ds.QueryRetrieveLevel = "IMAGE"
            ds.StudyInstanceUID = study_uid
            ds.SeriesInstanceUID = series_uid
            ds.SOPInstanceUID = instance_uid

            for status, _identifier in assoc.send_c_get(ds, StudyRootQueryRetrieveInformationModelGet):
                if is_cancelled and is_cancelled():
                    assoc.abort()
                    raise DimseAssociationError("C-GET cancelled")
                if status is None:
                    raise DimseAssociationError("C-GET: connection lost")
                if status.Status == 0x0000:
                    break
                if status.Status in (0xFF00, 0xFF01):
                    continue
                if status.Status >= 0xA000:
                    raise DimseAssociationError(f"C-GET failed with status 0x{status.Status:04X}")
        finally:
            assoc.release()

        if instance_uid not in received:
            raise DimseAssociationError(f"C-GET: instance {instance_uid} not received")
        return received[instance_uid]

    def c_move_instances(
        self,
        study_uid: str,
        series_uid: str,
        instance_uids: list[str],
        *,
        move_destination_ae: str,
        scp_host: str,
        scp_port: int,
        received: dict[str, bytes],
        tls_args: tuple | None = None,
    ) -> CMoveResult:
        """Download instances via C-MOVE to embedded Storage SCP."""
        ae = AE(ae_title=self._ae_title)
        ae.acse_timeout = self._timeout_s
        ae.dimse_timeout = self._timeout_s
        ae.network_timeout = self._timeout_s
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)

        assoc = ae.associate(
            self._host,
            self._port,
            ae_title=self._called_ae,
            tls_args=tls_args,
        )
        if not assoc.is_established:
            raise DimseAssociationError(
                f"Cannot associate with {self._host}:{self._port} (called AE: {self._called_ae})"
            )

        try:
            # Build query for all instances in series
            ds = Dataset()
            ds.QueryRetrieveLevel = "IMAGE"
            ds.StudyInstanceUID = study_uid
            ds.SeriesInstanceUID = series_uid
            ds.SOPInstanceUID = ""

            # Send C-MOVE
            responses = assoc.send_c_move(
                ds,
                move_destination_ae,
                StudyRootQueryRetrieveInformationModelMove,
            )

            completed = 0
            failed = 0
            warning = 0

            for status, _identifier in responses:
                if status is None:
                    break
                if status.Status == 0x0000:
                    break
                if status.Status in (0xFF00, 0xFF01):
                    # Pending - check sub-operation counts
                    if hasattr(status, "NumberOfCompletedSuboperations"):
                        completed = status.NumberOfCompletedSuboperations
                    if hasattr(status, "NumberOfFailedSuboperations"):
                        failed = status.NumberOfFailedSuboperations
                    if hasattr(status, "NumberOfWarningSuboperations"):
                        warning = status.NumberOfWarningSuboperations
                elif status.Status == _MOVE_DESTINATION_UNKNOWN:
                    raise DimseMoveDestinationError(
                        "C-MOVE: unknown move destination AE — add an entry in Orthanc "
                        "DicomModalities (Host/Port must match SCP bind address)."
                    )
                elif status.Status >= 0xA000:
                    failed += 1

        finally:
            assoc.release()

        return CMoveResult(completed=completed, failed=failed, warning=warning)

    def c_move_series(
        self,
        study_uid: str,
        series_uid: str,
        *,
        move_destination_ae: str,
        scp_host: str,
        scp_port: int,
        received: dict[str, bytes],
        tls_args: tuple | None = None,
    ) -> CMoveResult:
        """Download all instances in a series via C-MOVE (series-level query)."""
        ae = AE(ae_title=self._ae_title)
        ae.acse_timeout = self._timeout_s
        ae.dimse_timeout = self._timeout_s
        ae.network_timeout = self._timeout_s
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)

        assoc = ae.associate(
            self._host,
            self._port,
            ae_title=self._called_ae,
            tls_args=tls_args,
        )
        if not assoc.is_established:
            raise DimseAssociationError(
                f"Cannot associate with {self._host}:{self._port} (called AE: {self._called_ae})"
            )

        try:
            # Series-level query — more efficient than per-instance
            ds = Dataset()
            ds.QueryRetrieveLevel = "SERIES"
            ds.StudyInstanceUID = study_uid
            ds.SeriesInstanceUID = series_uid

            responses = assoc.send_c_move(
                ds,
                move_destination_ae,
                StudyRootQueryRetrieveInformationModelMove,
            )

            completed = 0
            failed = 0
            warning = 0

            for status, _identifier in responses:
                if status is None:
                    break
                if status.Status == 0x0000:
                    break
                if status.Status in (0xFF00, 0xFF01):
                    if hasattr(status, "NumberOfCompletedSuboperations"):
                        completed = status.NumberOfCompletedSuboperations
                    if hasattr(status, "NumberOfFailedSuboperations"):
                        failed = status.NumberOfFailedSuboperations
                    if hasattr(status, "NumberOfWarningSuboperations"):
                        warning = status.NumberOfWarningSuboperations
                elif status.Status == _MOVE_DESTINATION_UNKNOWN:
                    raise DimseMoveDestinationError(
                        "C-MOVE: unknown move destination AE — add an entry in Orthanc "
                        "DicomModalities (Host/Port must match SCP bind address)."
                    )
                elif status.Status >= 0xA000:
                    failed += 1

        finally:
            assoc.release()

        return CMoveResult(completed=completed, failed=failed, warning=warning)
