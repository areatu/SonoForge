"""DICOM Modality Worklist (C-FIND) and MPPS (N-CREATE/N-SET) SCP on pynetdicom,
with the IHE ECHO Verification SOP class (#626).

The MWL answers from the local worklist store (fed by inbound HL7/FHIR);
MPPS updates drive the worklist status back. No PHI is logged.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from typing import Any

from pydicom.dataset import Dataset
from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    ModalityPerformedProcedureStep,
    ModalityWorklistInformationFind,
    Verification,
)

from echo_personal_tool.domain.models.worklist import MppsUpdate, WorklistStatus
from echo_personal_tool.domain.ports import IWorklistSink
from echo_personal_tool.domain.services.listener_policy import TransportPolicyError, evaluate_listener_bind

logger = logging.getLogger(__name__)

MWL_SOP_CLASS = ModalityWorklistInformationFind
MPPS_SOP_CLASS = ModalityPerformedProcedureStep
ECHO_SOP_CLASS = Verification


def _attribute_list(primitive: Any) -> Dataset:
    """Decode the AttributeList of a DIMSE N-* primitive (BytesIO/bytes -> Dataset)."""
    import io

    raw = getattr(primitive, "AttributeList", None)
    if isinstance(raw, Dataset):
        return raw
    if isinstance(raw, io.BytesIO):
        pass  # decode() wants the stream itself
    elif isinstance(raw, (bytes, bytearray)) and raw:
        raw = io.BytesIO(bytes(raw))
    if isinstance(raw, io.BytesIO):
        from pynetdicom.dsutils import decode

        # DIMSE attribute lists use the negotiated transfer syntax; MPPS
        # defaults to Implicit VR Little Endian.
        decoded = decode(raw, True, True)
        return decoded if isinstance(decoded, Dataset) else Dataset()
    return Dataset()


def _mwl_dataset(item: Any) -> Dataset:
    """Map one :class:`WorklistItem` to a MWL response dataset."""
    ds = Dataset()
    ds.PatientName = item.patient_name
    ds.PatientID = item.patient_id
    ds.PatientBirthDate = item.birth_date.replace("-", "")
    ds.PatientSex = item.sex or "O"
    ds.AccessionNumber = item.accession_number
    ds.ReferringPhysicianName = item.referring_physician
    ds.RequestedProcedureDescription = item.procedure_description
    ds.RequestedProcedureID = item.accession_number
    ds.RequestedProcedureCodeSequence = []
    station = Dataset()
    station.ScheduledProcedureStepID = item.accession_number
    station.ScheduledProcedureStepDescription = item.procedure_description
    station.ScheduledStationAETitle = item.scheduled_station_ae
    date_part = item.scheduled_datetime[:10].replace("-", "")
    time_part = item.scheduled_datetime[11:19].replace(":", "") if "T" in item.scheduled_datetime else ""
    station.ScheduledProcedureStepStartDate = date_part
    station.ScheduledProcedureStepStartTime = time_part
    ds.ScheduledProcedureStepSequence = [station]
    return ds


class MwlMppsScp:
    """Start/stop wrapper around a pynetdicom AE serving MWL, MPPS and ECHO."""

    def __init__(
        self,
        *,
        ae_title: str,
        host: str,
        port: int,
        worklist: IWorklistSink,
        use_tls: bool = False,
        tls_verify: bool = True,
        tls_cert_path: str = "",
        tls_key_path: str = "",
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        decision = evaluate_listener_bind(
            host, port, use_tls=use_tls, tls_verify=tls_verify, allowed_hosts=allowed_hosts
        )
        if decision.verdict.name != "ALLOW":
            raise TransportPolicyError(decision)
        if decision.insecure:
            logger.warning("MWL/MPPS SCP on %s:%s is insecure (allowlisted)", host, port)
        self._host = host
        self._port = port
        self._worklist = worklist
        self._ae = AE(ae_title=ae_title.encode("ascii", "replace")[:16] or b"SONOFORGE")
        self._ae.maximumPDUSize = 16382
        self._ae.add_supported_context(ECHO_SOP_CLASS)
        self._ae.add_supported_context(MWL_SOP_CLASS)
        self._ae.add_supported_context(MPPS_SOP_CLASS)
        self._tls_context = None
        if use_tls:
            import ssl

            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(certfile=tls_cert_path, keyfile=tls_key_path or None)
            self._tls_context = context
        self._thread: threading.Thread | None = None
        self._server = None
        # MPPS SOP instance UID -> accession number, learned at N-CREATE.
        self._mpps_instances: dict[str, str] = {}

    def _on_echo(self, event: Any) -> int:
        return 0x0000

    def _on_c_find(self, event: Any) -> Iterator[tuple[int, Dataset | None]]:
        request: Dataset = event.identifier
        patient_id = str(getattr(request, "PatientID", "") or "")
        station = ""
        sps_seq = getattr(request, "ScheduledProcedureStepSequence", None)
        if sps_seq:
            station = str(getattr(sps_seq[0], "ScheduledStationAETitle", "") or "")
        for item in self._worklist.query_worklist(patient_id=patient_id, station_ae=station):
            yield 0xFF00, _mwl_dataset(item)  # pending
        yield 0x0000, None  # success

    def _on_n_create(self, event: Any) -> tuple[int, Dataset | None]:
        primitive = event.request
        request = _attribute_list(primitive)
        accession = str(getattr(request, "AccessionNumber", "") or "")
        sop_uid = str(getattr(primitive, "AffectedSOPInstanceUID", "") or "")
        ok = self._worklist.apply_mpps(
            MppsUpdate(accession_number=accession, status=WorklistStatus.IN_PROGRESS, sop_instance_uid=sop_uid)
        )
        if ok and sop_uid:
            self._mpps_instances[sop_uid] = accession
        return (0x0000, None) if ok else (0x0110, None)  # 0x0110: processing failure

    def _on_n_set(self, event: Any) -> tuple[int, Dataset | None]:
        primitive = event.request
        request = _attribute_list(primitive)
        sop_uid = str(
            getattr(primitive, "RequestedSOPInstanceUID", "") or getattr(primitive, "AffectedSOPInstanceUID", "") or ""
        )
        accession = str(getattr(request, "AccessionNumber", "") or "") or self._mpps_instances.get(sop_uid, "")
        status_text = str(getattr(request, "PerformedProcedureStepStatus", "") or "")
        status = {
            "IN PROGRESS": WorklistStatus.IN_PROGRESS,
            "COMPLETED": WorklistStatus.COMPLETED,
            "DISCONTINUED": WorklistStatus.DISCONTINUED,
        }.get(status_text)
        if status is None:
            return 0x0122, None  # no such attribute
        ok = self._worklist.apply_mpps(MppsUpdate(accession_number=accession, status=status))
        return (0x0000, None) if ok else (0x0110, None)

    def start(self) -> None:
        if self._thread is not None:
            return
        handlers = [
            (evt.EVT_C_ECHO, self._on_echo),
            (evt.EVT_C_FIND, self._on_c_find),
            (evt.EVT_N_CREATE, self._on_n_create),
            (evt.EVT_N_SET, self._on_n_set),
        ]
        self._thread = threading.Thread(
            target=self._ae.start_server,
            args=((self._host, self._port),),
            kwargs={"block": False, "evt_handlers": handlers, "ssl_context": self._tls_context},
            name="mwl-mpps-scp",
            daemon=True,
        )
        self._thread.start()
        ae_title = self._ae.ae_title
        ae_text = ae_title.decode("ascii", "replace") if isinstance(ae_title, bytes) else str(ae_title)
        logger.info("MWL/MPPS SCP started on %s:%s (ae=%s)", self._host, self._port, ae_text)

    def stop(self) -> None:
        self._ae.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None
