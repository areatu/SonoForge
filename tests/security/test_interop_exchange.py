"""Security/integration tests for #625: MLLP exchange, FHIR HTTPS, Encapsulated PDF.

Loopback only: the MLLP peer and the FHIR server are real sockets/servers on
127.0.0.1 started inside the test, so the transport-policy loopback path is
exercised exactly as in production.  No external network is touched.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from echo_personal_tool.application.interop_export import (
    PROTOCOL_FHIR,
    PROTOCOL_HL7,
    InteropExportService,
)
from echo_personal_tool.domain.exceptions import InteropError
from echo_personal_tool.domain.services.interop_dicom_pdf import EncapsulatedPdfSpec, VerifyingObserver
from echo_personal_tool.domain.services.interop_hl7 import (
    MLLP_CR,
    MLLP_END,
    MLLP_START,
    build_ack,
)
from echo_personal_tool.domain.services.report_document import (
    PatientInfo,
    ReportDocument,
    ReportGroup,
    ReportValue,
)
from echo_personal_tool.infrastructure.dicom_encapsulated_pdf import (
    ENCAPSULATED_PDF_SOP_CLASS_UID,
    encapsulated_pdf_bytes,
    send_encapsulated_pdf,
)
from echo_personal_tool.infrastructure.fhir_https_client import FhirHttpsClient
from echo_personal_tool.infrastructure.hl7_mllp import Hl7MllpClient

pytestmark = pytest.mark.security

STUDY_UID = "1.2.840.113619.2.5.99"


def _document() -> ReportDocument:
    return ReportDocument(
        patient=PatientInfo(
            name="Иванов И.И.",
            patient_id="P-1",
            birth_date="1980-01-01",
            sex="M",
            study_date="2026-11-18",
            physician="Петров П.П.",
            institution="Клиника",
            conclusion="Без патологии",
        ),
        groups=(
            ReportGroup(
                title="Левый желудочек",
                key="lv",
                values=(ReportValue(label="КДР ЛЖ", value="52", unit="mm", norm="35–56", parameter_id="lv.lvedd"),),
            ),
        ),
        title="Протокол ЭхоКГ",
        profile_id="echo",
    )


class _MllpPeer(threading.Thread):
    """One-connection MLLP peer that ACKs whatever it receives."""

    def __init__(self, accept: bool = True) -> None:
        super().__init__(daemon=True)
        self._accept = accept
        self.received = b""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]

    def run(self) -> None:
        try:
            conn, _ = self._sock.accept()
            with conn:
                data = b""
                while MLLP_END + MLLP_CR not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                self.received = data.strip(MLLP_START).removesuffix(MLLP_END + MLLP_CR)
                control = "MSG"
                for line in self.received.decode("utf-8", "replace").split("\r"):
                    if line.startswith("MSH|"):
                        control = line.split("|")[9]
                ack = build_ack(control, accept=self._accept)
                conn.sendall(MLLP_START + ack.encode("utf-8") + MLLP_END + MLLP_CR)
        finally:
            self._sock.close()


class TestHl7Mllp:
    def test_send_oru_and_parse_ack_aa(self) -> None:
        peer = _MllpPeer(accept=True)
        peer.start()
        service = InteropExportService(session=None)
        payload = service.build_hl7(_document(), study_uid=STUDY_UID, physician="Петров П.П.")
        client = Hl7MllpClient(host="127.0.0.1", port=peer.port, timeout_s=10.0)
        ack = client.send_oru(payload)
        peer.join(timeout=10)
        assert ack.accepted and ack.code == "AA"
        assert b"ORU^R01" in peer.received
        assert b"8625-6" in peer.received  # LOINC of lv.lvedd

    def test_rejected_ack_is_reported(self) -> None:
        peer = _MllpPeer(accept=False)
        peer.start()
        service = InteropExportService(session=None)
        payload = service.build_hl7(_document(), study_uid=STUDY_UID, physician="Петров П.П.")
        client = Hl7MllpClient(host="127.0.0.1", port=peer.port, timeout_s=10.0)
        ack = client.send_oru(payload)
        peer.join(timeout=10)
        assert not ack.accepted and ack.code == "AE"

    def test_refuses_remote_plaintext_endpoint(self) -> None:
        from echo_personal_tool.application.transport_policy import TransportPolicyError

        with pytest.raises(TransportPolicyError):
            Hl7MllpClient(host="192.168.10.10", port=6000, use_tls=False)

    def test_connection_refused_is_safe_error(self) -> None:
        client = Hl7MllpClient(host="127.0.0.1", port=1, timeout_s=2.0)
        with pytest.raises(InteropError) as exc_info:
            client.send_oru(b"MSH|^~\\&|x")
        assert exc_info.value.code == "transport"


class _FhirHandler(BaseHTTPRequestHandler):
    received: bytes = b""
    status: int = 200

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        _FhirHandler.received = self.rfile.read(length)
        body = json.dumps({"resourceType": "Bundle", "type": "transaction-response"}).encode()
        self.send_response(_FhirHandler.status)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


class TestFhirHttps:
    def test_post_bundle_to_loopback_server(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), _FhirHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/fhir"
            client = FhirHttpsClient(base_url=url, timeout_s=10.0)
            service = InteropExportService(session=None)
            payload = service.build_fhir(_document(), study_uid=STUDY_UID, physician="Петров П.П.")
            result = client.post_bundle(payload)
            assert result.accepted and result.status_code == 200
            bundle = json.loads(_FhirHandler.received.decode("utf-8"))
            assert bundle["resourceType"] == "Bundle"
            assert any(e["resource"]["resourceType"] == "Observation" for e in bundle["entry"])
        finally:
            server.shutdown()
            server.server_close()

    def test_plaintext_remote_url_is_blocked(self) -> None:
        from echo_personal_tool.application.transport_policy import TransportPolicyError

        with pytest.raises(TransportPolicyError):
            FhirHttpsClient(base_url="http://10.20.30.40:8080/fhir")

    def test_server_error_is_not_accepted(self) -> None:
        _FhirHandler.status = 500
        server = HTTPServer(("127.0.0.1", 0), _FhirHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = FhirHttpsClient(base_url=f"http://127.0.0.1:{server.server_port}/fhir", timeout_s=10.0)
            result = client.post_bundle(b'{"resourceType":"Bundle"}')
            assert not result.accepted and result.status_code == 500
        finally:
            server.shutdown()
            server.server_close()
            _FhirHandler.status = 200


class TestEncapsulatedPdf:
    def _spec(self) -> EncapsulatedPdfSpec:
        return EncapsulatedPdfSpec(
            patient_name="Иванов И.И.",
            patient_id="P-1",
            birth_date="1980-01-01",
            sex="M",
            study_uid=STUDY_UID,
            series_uid="1.2.3.4.5",
            sop_instance_uid="1.2.3.4.6",
            study_date="2026-11-18",
            document_title="Протокол ЭхоКГ",
            verifying_observers=(
                VerifyingObserver(name="Петров П.П., врач УЗД", organization="Клиника", key_id="0123456789abcdef"),
            ),
            pdf_bytes=b"%PDF-1.4 signed-bytes",
        )

    def test_dataset_tags(self) -> None:
        import io

        import pydicom

        payload = encapsulated_pdf_bytes(self._spec())
        ds = pydicom.dcmread(io.BytesIO(payload))
        assert str(ds.SOPClassUID) == ENCAPSULATED_PDF_SOP_CLASS_UID
        assert ds.Modality == "DOC"
        assert ds.PatientName == "Иванов И.И."
        assert ds.MIMETypeOfEncapsulatedDocument == "application/pdf"
        assert bytes(ds.EncapsulatedDocument).rstrip(b"\x00") == b"%PDF-1.4 signed-bytes"  # OB pads to even length
        observer = ds.VerifyingObserverSequence[0]
        assert observer.VerifyingObserverName == "Петров П.П., врач УЗД"
        assert observer.VerifyingOrganization == "Клиника"
        assert str(observer.VerifyingObserverIdentificationCodeSequence[0].CodeValue) == "0123456789abcdef"

    def test_spec_validation(self) -> None:
        with pytest.raises(ValueError):
            EncapsulatedPdfSpec(pdf_bytes=b"%PDF-x").validate()  # missing uids/observer
        bad = EncapsulatedPdfSpec(
            study_uid="1",
            series_uid="2",
            sop_instance_uid="3",
            verifying_observers=(VerifyingObserver(name="x"),),
            pdf_bytes=b"not a pdf",
        )
        with pytest.raises(ValueError):
            bad.validate()

    def test_send_via_fake_clients(self) -> None:
        class _FakeUpload:
            def __init__(self) -> None:
                self.payloads: list[bytes] = []

            def upload_instance(self, dicom_bytes: bytes) -> bool:
                self.payloads.append(dicom_bytes)
                return True

        class _FakeStow:
            def __init__(self) -> None:
                self.files: list[bytes] = []

            def stow_instances(self, dicom_files: list[bytes]):
                self.files.extend(dicom_files)

                class _Result:
                    success = len(dicom_files)

                return _Result()

        upload = _FakeUpload()
        assert send_encapsulated_pdf(self._spec(), upload_client=upload)
        assert upload.payloads and upload.payloads[0].startswith(b"\0" * 128)
        stow = _FakeStow()
        assert send_encapsulated_pdf(self._spec(), stow_client=stow, use_stow=True)
        assert len(stow.files) == 1
        with pytest.raises(InteropError):
            send_encapsulated_pdf(self._spec(), upload_client=None, use_stow=False)


class TestAuditEvents:
    def test_interop_export_audits_phifree_events(self, tmp_path: Path) -> None:
        from echo_personal_tool.application.user_session import UserSessionService
        from echo_personal_tool.domain.models.audit import AuditAction
        from echo_personal_tool.domain.models.user import SecretKind

        session = UserSessionService(tmp_path / "users", scrypt_n=1 << 12, scope_paths=False)
        session.bootstrap_first_admin(
            username="petrov", display_name="Петров П.П.", secret="Admin#2026", secret_kind=SecretKind.PASSWORD
        )
        service = InteropExportService(session=session)
        service.export_hl7_file(_document(), tmp_path / "r.hl7", study_uid=STUDY_UID, physician="Петров П.П.")
        service.export_fhir_file(_document(), tmp_path / "r.fhir.json", study_uid=STUDY_UID, physician="Петров П.П.")
        actions = [entry.action for entry in session.recent_audit_entries(limit=20)]
        assert actions.count(AuditAction.INTEROP_EXPORTED.value) == 2
        entries = [e for e in session.recent_audit_entries(limit=20) if e.action == AuditAction.INTEROP_EXPORTED.value]
        protocols = {dict(e.details).get("protocol") for e in entries}
        assert protocols == {PROTOCOL_HL7, PROTOCOL_FHIR}
        # PHI-free: no patient name anywhere in the entry details
        for entry in entries:
            assert "Иванов" not in json.dumps(dict(entry.details))
