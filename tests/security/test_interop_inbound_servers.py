"""Integration tests for Stage-4 inbound interop (#626).

Loopback only: a real MLLP listener + client roundtrip, a real pynetdicom
MWL/MPPS SCP + SCU exchange, a loopback HTTP FHIR poll, and the SQLite WAL
worklist store. Audit events must stay PHI-free.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from echo_personal_tool.application.interop_inbound import InteropInboundService
from echo_personal_tool.application.worklist_service import WorklistService
from echo_personal_tool.domain.models.worklist import WorklistStatus
from echo_personal_tool.infrastructure.fhir_inbound_client import FhirInboundClient
from echo_personal_tool.infrastructure.hl7_mllp import Hl7MllpClient
from echo_personal_tool.infrastructure.hl7_mllp_server import Hl7MllpServer
from echo_personal_tool.infrastructure.worklist_repository import WorklistRepository

ORM_NEW = (
    "MSH|^~\\&|RIS|HOSP|SonoForge|US|20261118120000||ORM^O01|MSG1|P|2.5\r"
    "PID|1||P1^^^HOSP^MR||Ivanov^Ivan||19800101|M\r"
    "PV1|1|O|USLAB\r"
    "ORC|NW|ORD1\r"
    "OBR|1|ORD1|ACC42|ECHO^Echocardiography|||20261118130000\r"
)

ADT_MERGE = (
    "MSH|^~\\&|HIS|HOSP|SonoForge|US|20261118120000||ADT^A40|MSG3|P|2.5\r"
    "MRG|P1^^^HOSP^MR||||||P2^^^HOSP^MR\r"
    "PID|1||P2^^^HOSP^MR||Petrov^Petr||19900202|F"
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _AuditSession:
    """Minimal session double capturing PHI-free audit events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, str]]] = []

    def record_study_audit(self, action: object, *, study_key: str = "", details: dict[str, str] | None = None) -> None:
        self.events.append((getattr(action, "value", str(action)), study_key, details or {}))


@pytest.fixture()
def store(tmp_path: Path) -> WorklistRepository:
    repo = WorklistRepository(tmp_path / "worklist.db")
    yield repo
    repo.close()


class TestWorklistStore:
    def test_upsert_query_status_merge(self, store: WorklistRepository):
        from echo_personal_tool.domain.models.worklist import PatientDemographics, WorklistItem

        store.upsert_worklist_item(
            WorklistItem(
                accession_number="A1", patient_id="P1", patient_name="Ivanov Ivan", procedure_description="Echo"
            )
        )
        store.upsert_worklist_item(WorklistItem(accession_number="A2", patient_id="P2"))
        assert store.get_worklist_item("A1") is not None
        assert len(store.query_worklist(patient_id="P1")) == 1
        assert store.set_worklist_status("A1", WorklistStatus.IN_PROGRESS.value, updated_at="t")
        assert store.get_worklist_item("A1").status is WorklistStatus.IN_PROGRESS  # type: ignore[attr-defined]
        assert not store.set_worklist_status("NOPE", WorklistStatus.COMPLETED.value)
        store.upsert_patient(PatientDemographics(patient_id="P1", name="Ivanov Ivan"))
        store.apply_merge("P1", "P2", merged_at="t")
        assert store.get_worklist_item("A1").patient_id == "P2"  # type: ignore[attr-defined]
        assert store.get_patient("P1") is not None

    def test_wal_mode(self, store: WorklistRepository):
        mode = store._db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"


class TestMllpRoundtrip:
    def test_listener_acks_and_applies_order(self, store: WorklistRepository):
        session = _AuditSession()
        worklist = WorklistService(store=store, session=session)
        inbound = InteropInboundService(worklist=worklist)
        port = _free_port()
        server = Hl7MllpServer(host="127.0.0.1", port=port, handler=inbound.handle_hl7_message)
        server.start()
        try:
            client = Hl7MllpClient(host="127.0.0.1", port=port)
            ack = client.send_oru(ORM_NEW.encode("utf-8"))
            assert ack.accepted and ack.code == "AA"
            client.send_oru(ADT_MERGE.encode("utf-8"))
            time.sleep(0.2)
        finally:
            server.stop()
        item = store.get_worklist_item("ACC42")
        assert item is not None
        assert item.patient_id == "P2"  # merge applied before order? order carried P1, merge moved it
        assert item.status is WorklistStatus.SCHEDULED
        # audit events exist and carry no PHI
        assert session.events
        blob = json.dumps([e[2] for e in session.events])
        assert "Ivanov" not in blob and "Petrov" not in blob

    def test_listener_rejects_remote_plaintext_bind(self):
        from echo_personal_tool.application.transport_policy import TransportPolicyError

        with pytest.raises(TransportPolicyError):
            Hl7MllpServer(host="192.0.2.10", port=6761, handler=lambda m: m)
        # allowlisted host is accepted
        server = Hl7MllpServer(host="192.0.2.10", port=6761, handler=lambda m: m, allowed_hosts=("192.0.2.10",))
        assert server.insecure

    def test_malformed_message_gets_ae(self, store: WorklistRepository):
        worklist = WorklistService(store=store)
        inbound = InteropInboundService(worklist=worklist)
        port = _free_port()
        server = Hl7MllpServer(host="127.0.0.1", port=port, handler=inbound.handle_hl7_message)
        server.start()
        try:
            client = Hl7MllpClient(host="127.0.0.1", port=port)
            ack = client.send_oru(b"GARBAGE without msh")
            assert not ack.accepted and ack.code == "AE"
        finally:
            server.stop()


class _FhirHandler(BaseHTTPRequestHandler):
    bundles: dict[str, dict] = {}

    def do_GET(self):  # noqa: N802
        resource = self.path.lstrip("/").split("?")[0].split("/")[-1]
        body = json.dumps(self.bundles.get(resource, {"resourceType": "Bundle", "entry": []})).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


class TestFhirInbound:
    def test_poll_applies_bundle(self, store: WorklistRepository):
        _FhirHandler.bundles = {
            "ServiceRequest": {
                "resourceType": "Bundle",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "ServiceRequest",
                            "subject": {"reference": "Patient/P9"},
                            "code": {"coding": [{"code": "ECHO"}], "text": "Echo"},
                            "identifier": [{"value": "ACC9"}],
                        }
                    }
                ],
            },
            "Patient": {
                "resourceType": "Bundle",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "P9",
                            "name": [{"family": "Sidorov"}],
                            "gender": "female",
                        }
                    }
                ],
            },
            "DiagnosticReport": {"resourceType": "Bundle", "entry": []},
        }
        httpd = HTTPServer(("127.0.0.1", 0), _FhirHandler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            # loopback http is the sanctioned local profile for the poll client
            from echo_personal_tool.application.transport_policy import Verdict, evaluate_dicomweb_url

            assert (
                evaluate_dicomweb_url(f"http://127.0.0.1:{httpd.server_port}/fhir", tls_verify=True).verdict
                is Verdict.ALLOW
            )
            client = FhirInboundClient.__new__(FhirInboundClient)
            # bypass policy construction for the loopback test server
            client._base = f"http://127.0.0.1:{httpd.server_port}/fhir"
            client._timeout_s = 5.0
            client._auth = None
            client._bearer = ""
            client._tls_ca_path = ""
            bundle = client.fetch_all(patient="P9")
        finally:
            httpd.shutdown()
        worklist = WorklistService(store=store)
        inbound = InteropInboundService(worklist=worklist)
        orders, patients, priors = inbound.poll_fhir(bundle)
        assert orders == 1 and patients == 1
        assert store.get_worklist_item("ACC9") is not None
        assert store.get_patient("P9") is not None


class TestMwlMpps:
    def test_c_find_and_mpps_over_loopback(self, store: WorklistRepository):
        pytest.importorskip("pynetdicom")
        from pydicom.dataset import Dataset
        from pynetdicom import AE
        from pynetdicom.sop_class import ModalityPerformedProcedureStep, ModalityWorklistInformationFind

        from echo_personal_tool.infrastructure.mwl_mpps_server import MwlMppsScp

        worklist = WorklistService(store=store)
        inbound = InteropInboundService(worklist=worklist)
        inbound.handle_hl7_message(ORM_NEW)
        port = _free_port()
        scp = MwlMppsScp(ae_title="SONOFORGE", host="127.0.0.1", port=port, worklist=worklist)
        scp.start()
        try:
            time.sleep(0.5)
            ae = AE(ae_title=b"TESTSCU")
            ae.add_requested_context(ModalityWorklistInformationFind)
            ae.add_requested_context(ModalityPerformedProcedureStep)
            assoc = ae.associate("127.0.0.1", port)
            assert assoc.is_established
            # MWL C-FIND for patient P1
            query = Dataset()
            query.PatientID = "P1"
            query.PatientName = ""
            query.AccessionNumber = ""
            query.ScheduledProcedureStepSequence = [Dataset()]
            responses = assoc.send_c_find(query, ModalityWorklistInformationFind)
            found = []
            for status, identifier in responses:
                if identifier:
                    found.append(identifier)
            assert any(str(ds.AccessionNumber) == "ACC42" for ds in found)
            # MPPS N-CREATE then N-SET COMPLETED
            mpps = Dataset()
            mpps.AccessionNumber = "ACC42"
            mpps.ScheduledProcedureStepID = "ACC42"
            mpps.ScheduledStationAETitle = "USLAB"
            mpps.ScheduledProcedureStepStartDate = "20261118"
            mpps.ScheduledProcedureStepStartTime = "130000"
            mpps.PerformedProcedureStepStatus = "IN PROGRESS"
            mpps.AffectedSOPInstanceUID = "1.2.3.4.5"
            status, _ = assoc.send_n_create(mpps, ModalityPerformedProcedureStep, instance_uid="1.2.3.4.5")
            assert status.Status == 0x0000
            mpps_set = Dataset()
            mpps_set.RequestedSOPInstanceUID = "1.2.3.4.5"
            mpps_set.PerformedProcedureStepStatus = "COMPLETED"
            status, _ = assoc.send_n_set(mpps_set, ModalityPerformedProcedureStep, instance_uid="1.2.3.4.5")
            assert status.Status == 0x0000
            assoc.release()
        finally:
            scp.stop()
        assert store.get_worklist_item("ACC42").status is WorklistStatus.COMPLETED  # type: ignore[attr-defined]
