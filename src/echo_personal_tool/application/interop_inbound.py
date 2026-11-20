"""Inbound interop application facade (#626, full report import).

The MLLP listener (infrastructure) hands each decoded message to
:meth:`InteropInboundService.handle_hl7_message`, which parses it with the pure
domain parsers, applies orders/demographics to the worklist through
:class:`WorklistService` and stores ORU^R01 result reports in the imported
report store, then returns the synchronous ACK text. FHIR inbound polling goes
through :meth:`poll_fhir` (worklist plus DiagnosticReport documents). Listener
bind addresses are judged by :func:`transport_policy.evaluate_listener_bind`
before any socket is opened.
"""

from __future__ import annotations

from typing import Any

from echo_personal_tool.application.transport_policy import (
    evaluate_dicomweb_url,
    evaluate_listener_bind,
)
from echo_personal_tool.application.worklist_service import WorklistService
from echo_personal_tool.domain.models.imported_report import ImportedReport
from echo_personal_tool.domain.models.worklist import DemographicsEvent, OrderEvent
from echo_personal_tool.domain.services import interop_fhir_inbound, interop_inbound_hl7
from echo_personal_tool.domain.services.interop_hl7 import DEFAULT_HL7_VERSION, FIELD_SEP, SUPPORTED_HL7_VERSIONS
from echo_personal_tool.domain.services.interop_inbound_hl7 import Hl7ParseError


def make_fhir_inbound_client(**kwargs: Any) -> Any:
    """Build the infrastructure FHIR poll client with the transport policy injected.

    The client module never imports the application layer, so the DICOMweb URL
    judgement (:func:`evaluate_dicomweb_url`) is passed in as ``url_guard``.
    """
    from echo_personal_tool.infrastructure.fhir_inbound_client import FhirInboundClient

    def url_guard(url: str, tls_verify: bool, tls_ca_path: str) -> object:
        return evaluate_dicomweb_url(url, tls_verify=tls_verify, tls_ca_path=tls_ca_path, exceptions=())

    kwargs.setdefault("url_guard", url_guard)
    return FhirInboundClient(**kwargs)


class InteropInboundService:
    """Inbound HL7 v2 / FHIR intake for the worklist and imported reports."""

    def __init__(
        self,
        *,
        worklist: WorklistService,
        reports: Any = None,
        session: Any = None,
        now: Any = None,
        version: str = DEFAULT_HL7_VERSION,
    ) -> None:
        self._worklist = worklist
        self._reports = reports
        self._session = session
        self._now = now
        if version not in SUPPORTED_HL7_VERSIONS:
            raise ValueError("unsupported_version")
        self._version = version

    # ── imported report storage ──────────────────────────────────────

    def _import_report(self, report: ImportedReport) -> bool:
        """Store an imported report and audit it; False when no store is wired."""
        if self._reports is None:
            return False
        if self._now is not None:
            report.received_at = self._now()
        self._reports.save(report)
        if self._session is not None:
            from echo_personal_tool.domain.models.audit import AuditAction

            self._session.record_study_audit(
                AuditAction.INTEROP_RECEIVED,
                study_key=report.accession_number[:64],
                details={
                    "protocol": report.source,
                    "event": "report.imported",
                    "report_id": report.report_id[:64],
                    "measurements": str(len(report.measurements)),
                    "has_pdf": str(report.pdf_bytes is not None),
                },
            )
        return True

    def imported_reports(self, *, patient_id: str = "") -> list[ImportedReport]:
        """List stored imported reports, optionally filtered by patient."""
        if self._reports is None:
            return []
        if patient_id:
            return list(self._reports.list_for_patient(patient_id))
        return list(self._reports.list_all())

    # ── HL7 v2 listener callback ─────────────────────────────────────

    def handle_hl7_message(self, message: str) -> str:
        """Parse one inbound HL7 message, apply it, return the ACK text (AA/AE)."""
        try:
            event = interop_inbound_hl7.parse_inbound(message)
        except Hl7ParseError as exc:
            return self._ack(message, accept=False, error=str(exc.code if hasattr(exc, "code") else exc))
        if isinstance(event, ImportedReport):
            self._import_report(event)
        elif isinstance(event, OrderEvent):
            self._worklist.apply_order(event)
        elif isinstance(event, DemographicsEvent):
            self._worklist.apply_demographics(event)
        return self._ack(message, accept=True)

    def _ack(self, inbound: str, *, accept: bool, error: str = "") -> str:
        """Synchronous ACK echoing the inbound MSH (sending app <-> receiving app)."""
        control_id = ""
        sending_app = "SONOFORGE"
        sending_facility = "LOCAL"
        receiving_app = "RIS"
        receiving_facility = "HOSP"
        for fields in interop_inbound_hl7.split_segments(inbound):
            if fields and fields[0] == "MSH":
                receiving_app = interop_inbound_hl7._field(fields, 3) or receiving_app
                receiving_facility = interop_inbound_hl7._field(fields, 4) or receiving_facility
                sending_app = interop_inbound_hl7._field(fields, 5) or sending_app
                sending_facility = interop_inbound_hl7._field(fields, 6) or sending_facility
                control_id = interop_inbound_hl7._field(fields, 10)
                break
        code = "AA" if accept else "AE"
        msh = FIELD_SEP.join(
            [
                f"MSH{FIELD_SEP}^~\\&",
                sending_app,
                sending_facility,
                receiving_app,
                receiving_facility,
                "",
                "",
                "ACK",
                control_id,
                "P",
                self._version,
            ]
        )
        msa_fields = ["MSA", code, control_id]
        if not accept and error:
            msa_fields.append("")
            msa_fields.append("")
            msa_fields.append(error[:80])
        msa = FIELD_SEP.join(msa_fields)
        return "\r".join([msh, msa]) + "\r"

    # ── FHIR inbound poll ────────────────────────────────────────────

    def poll_fhir(self, bundle: dict[str, Any]) -> tuple[int, int, int]:
        """Apply a polled FHIR Bundle; returns (orders, patients, priors) counts.

        DiagnosticReport entries that carry a document (presentedForm PDF or a
        conclusion) are additionally imported as full reports.
        """
        orders, patients, priors = interop_fhir_inbound.parse_bundle(bundle)
        for order in orders:
            self._worklist.apply_order(order)
        for patient in patients:
            self._worklist.apply_demographics(DemographicsEvent(event="A04", patient=patient, source="fhir"))
        for entry in bundle.get("entry") or []:
            resource = entry.get("resource") if isinstance(entry, dict) else None
            if not isinstance(resource, dict) or resource.get("resourceType") != "DiagnosticReport":
                continue
            has_document = bool(resource.get("presentedForm")) or bool(str(resource.get("conclusion", "")).strip())
            if has_document:
                self._import_report(interop_fhir_inbound.parse_diagnostic_report_document(resource))
        return len(orders), len(patients), len(priors)

    # ── listener policy ──────────────────────────────────────────────

    @staticmethod
    def judge_listener_bind(
        host: str, port: int, *, use_tls: bool, tls_verify: bool = True, allowed_hosts: Any = ()
    ) -> Any:
        """Delegate to transport policy; raises TransportPolicyError when blocked."""
        from echo_personal_tool.application.transport_policy import TransportPolicyError

        decision = evaluate_listener_bind(
            host, port, use_tls=use_tls, tls_verify=tls_verify, allowed_hosts=allowed_hosts
        )
        if decision.verdict.name != "ALLOW":
            raise TransportPolicyError(decision)
        return decision
