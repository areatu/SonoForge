"""Full inbound import of external reports: store + service (#619 follow-up).

Covers the persistent :class:`ImportedReportStore` and the
:class:`InteropInboundService` paths that turn an HL7 ORU^R01 message or a
FHIR DiagnosticReport document into a stored :class:`ImportedReport`.
"""

from __future__ import annotations

import base64
from pathlib import Path

from echo_personal_tool.application.interop_inbound import InteropInboundService
from echo_personal_tool.application.worklist_service import WorklistService
from echo_personal_tool.domain.models.imported_report import ImportedMeasurement, ImportedReport
from echo_personal_tool.domain.models.worklist import PatientDemographics
from echo_personal_tool.infrastructure.imported_report_store import MAX_REPORTS, ImportedReportStore
from echo_personal_tool.infrastructure.worklist_repository import WorklistRepository

_ORU_OBR = "|".join(
    ["OBR", "1", "ORD100", "ACC100", "ECHO^Echocardiography", "", "", "20261118130000", *[""] * 24, "Dr. Echo"]
)

ORU_MESSAGE = (
    "MSH|^~\\&|RIS|HOSP|SonoForge|US|20261118120000||ORU^R01|MSG100|P|2.5\r"
    "PID|1||P100^^^HOSP^MR||Ivanov^Ivan||19800101|M\r" + _ORU_OBR + "\r"
    "OBX|1|NM|8867-4^LVEF^LN||55|%|35-75|N||F||20261118130000\r"
    "OBX|2|TX|CONCL^Conclusion^99SONOFORGE||Normal study|||||F||20261118130000\r"
    + "OBX|3|ED|PDF^external.pdf^99SONOFORGE||application/pdf^PDF^Base64^"
    + base64.b64encode(b"%PDF-1.4 external").decode("ascii")
    + "||||F||20261118130000\r"
)


def _report(report_id: str = "R1", patient_id: str = "P100") -> ImportedReport:
    return ImportedReport(
        report_id=report_id,
        source="hl7",
        patient=PatientDemographics(patient_id=patient_id, name="Ivanov Ivan"),
        accession_number="ACC100",
        conclusion="Normal study",
        measurements=[ImportedMeasurement(code="8867-4", text="LVEF", value="55", unit="%")],
        pdf_bytes=b"%PDF-1.4 external",
        pdf_title="external.pdf",
    )


class TestImportedReportStore:
    def test_save_get_list_delete_roundtrip(self, tmp_path: Path) -> None:
        store = ImportedReportStore(tmp_path / "reports.json")
        store.save(_report("R1"))
        store.save(_report("R2", patient_id="P200"))

        loaded = store.get("R1")
        assert loaded is not None
        assert loaded.patient is not None and loaded.patient.name == "Ivanov Ivan"
        assert loaded.pdf_bytes == b"%PDF-1.4 external"
        assert loaded.measurements[0].value == "55"
        assert len(store.list_for_patient("P100")) == 1
        assert len(store.list_for_patient("P200")) == 1
        assert len(store.list_all()) == 2

        # Persists across instances.
        again = ImportedReportStore(tmp_path / "reports.json")
        assert again.get("R1") is not None

        assert store.delete("R1") is True
        assert store.get("R1") is None
        assert store.delete("R1") is False

    def test_replace_same_id_and_evict_oldest(self, tmp_path: Path) -> None:
        store = ImportedReportStore(tmp_path / "reports.json")
        store.save(_report("R1"))
        updated = _report("R1")
        updated.conclusion = "Amended"
        store.save(updated)
        assert len(store.list_all()) == 1
        assert store.get("R1").conclusion == "Amended"

        for index in range(MAX_REPORTS + 5):
            store.save(_report(f"bulk-{index}", patient_id="PX"))
        all_reports = store.list_all()
        assert len(all_reports) == MAX_REPORTS
        assert all_reports[0].report_id == "bulk-5"

    def test_corrupt_file_reads_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "reports.json"
        path.write_bytes(b"not json")
        assert ImportedReportStore(path).list_all() == []

    def test_symlink_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "real.json"
        target.write_bytes(b"{}")
        link = tmp_path / "reports.json"
        link.symlink_to(target)
        store = ImportedReportStore(link)
        assert store.list_all() == []
        try:
            store.save(_report())
            raise AssertionError("symlinked store must refuse writes")
        except RuntimeError:
            pass


class _AuditSession:
    def __init__(self) -> None:
        self.events: list[tuple[object, dict[str, str]]] = []

    def record_study_audit(self, action: object, *, study_key: str = "", details: dict[str, str] | None = None) -> None:
        self.events.append((action, details or {}))


def _service(tmp_path: Path, session: object | None = None) -> InteropInboundService:
    worklist = WorklistService(store=WorklistRepository(tmp_path / "wl.db"))
    return InteropInboundService(
        worklist=worklist,
        reports=ImportedReportStore(tmp_path / "reports.json"),
        session=session,
        now=lambda: "2026-11-18T12:00:00",
    )


class TestInteropInboundReportImport:
    def test_oru_message_is_imported_and_acked(self, tmp_path: Path) -> None:
        session = _AuditSession()
        inbound = _service(tmp_path, session)
        ack = inbound.handle_hl7_message(ORU_MESSAGE)
        assert "|AA|" in ack

        reports = inbound.imported_reports()
        assert len(reports) == 1
        report = reports[0]
        assert report.report_id == "MSG100"
        assert report.accession_number == "ACC100"
        assert report.physician == "Dr. Echo"
        assert report.conclusion == "Normal study"
        assert report.pdf_bytes == b"%PDF-1.4 external"
        assert report.received_at == "2026-11-18T12:00:00"
        assert [m.code for m in report.measurements] == ["8867-4"]
        assert report.patient is not None and report.patient.patient_id == "P100"
        assert inbound.imported_reports(patient_id="P100")
        assert inbound.imported_reports(patient_id="other") == []
        assert session.events and session.events[0][1].get("event") == "report.imported"

    def test_malformed_message_still_gets_ae(self, tmp_path: Path) -> None:
        inbound = _service(tmp_path)
        ack = inbound.handle_hl7_message("MSH|^~\\&|A|B|C|D|20261118||QRY^A19|X|P|2.5\r")
        assert "|AE|" in ack
        assert inbound.imported_reports() == []

    def test_fhir_poll_imports_diagnostic_report_documents(self, tmp_path: Path) -> None:
        inbound = _service(tmp_path)
        pdf = b"%PDF-1.4 fhir report"
        bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "P55",
                        "name": [{"family": "Sidorov", "given": ["Petr"]}],
                    }
                },
                {
                    "resource": {
                        "resourceType": "DiagnosticReport",
                        "id": "DR-55",
                        "status": "final",
                        "code": {"coding": [{"code": "ECHO-RPT"}], "text": "Echo report"},
                        "subject": {"reference": "Patient/P55"},
                        "conclusion": "No pathology.",
                        "presentedForm": [
                            {
                                "contentType": "application/pdf",
                                "data": base64.b64encode(pdf).decode("ascii"),
                                "title": "r.pdf",
                            }
                        ],
                        "contained": [
                            {
                                "resourceType": "Observation",
                                "code": {"coding": [{"code": "8867-4"}], "text": "LVEF"},
                                "valueQuantity": {"value": 60, "code": "%"},
                            }
                        ],
                    }
                },
            ],
        }
        orders, patients, priors = inbound.poll_fhir(bundle)
        # The contained Observation still counts as a prior result *and* as a report measurement.
        assert (orders, patients, priors) == (0, 1, 1)
        reports = inbound.imported_reports()
        assert len(reports) == 1
        assert reports[0].source == "fhir"
        assert reports[0].report_id == "DR-55"
        assert reports[0].pdf_bytes == pdf
        assert reports[0].measurements[0].code == "8867-4"

    def test_fhir_poll_without_document_keeps_worklist_only(self, tmp_path: Path) -> None:
        inbound = _service(tmp_path)
        bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "DiagnosticReport",
                        "id": "DR-1",
                        "status": "final",
                        "contained": [
                            {
                                "resourceType": "Observation",
                                "code": {"coding": [{"code": "8867-4"}]},
                                "valueQuantity": {"value": 55, "code": "%"},
                            }
                        ],
                    }
                }
            ],
        }
        _orders, _patients, priors = inbound.poll_fhir(bundle)
        assert priors == 1
        assert inbound.imported_reports() == []
