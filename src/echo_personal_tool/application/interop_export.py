"""Application facade for outbound interop exchange (#625).

Builds HL7 v2 ``ORU^R01``, FHIR R4 Bundle and DICOM Encapsulated PDF from the
same :class:`ReportDocument` the sheet shows, using the unified terminology
dictionary.  File export (``.hl7`` / ``.fhir.json``) needs no endpoint; sending
goes through the ports (MLLP client, FHIR HTTPS client, existing DICOM upload)
after :mod:`transport_policy` judged the endpoint.  Every operation writes a
PHI-free ``interop.exported`` audit event (protocol + outcome only).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from echo_personal_tool.domain.models.audit import AuditAction
from echo_personal_tool.domain.models.report_signature import (
    SignatureReceipt,
    canonical_document_sha256,
)
from echo_personal_tool.domain.services.interop_dicom_pdf import (
    EncapsulatedPdfSpec,
    VerifyingObserver,
)
from echo_personal_tool.domain.services.interop_fhir import (
    build_fhir_bundle,
    bundle_to_json,
    fhir_signature_entry,
)
from echo_personal_tool.domain.services.interop_hl7 import (
    DEFAULT_HL7_VERSION,
    InteropObservation,
    InteropPatient,
    InteropReport,
    build_oru_r01,
    encode_message,
)
from echo_personal_tool.domain.services.report_document import ReportDocument
from echo_personal_tool.infrastructure.measurement_codec import study_key

if TYPE_CHECKING:
    from echo_personal_tool.application.user_session import UserSessionService

#: Protocol identifiers used in audit details and status lines.
PROTOCOL_HL7 = "hl7v2-oru-r01"
PROTOCOL_FHIR = "fhir-r4-bundle"
PROTOCOL_DICOM_PDF = "dicom-encapsulated-pdf"

HL7_SUFFIX = ".hl7"
FHIR_SUFFIX = ".fhir.json"


@dataclass(frozen=True)
class InteropExportResult:
    """Outcome of one export/send (no PHI, no credentials)."""

    protocol: str
    outcome: str  # "exported" | "sent" | "failed"
    path: Path | None = None
    detail: str = ""


def _quantity_of(value: Any) -> str:
    """Physical quantity of a ReportValue via its parameter id in the catalog."""
    from echo_personal_tool.domain.measurement_catalog import MEASUREMENTS

    spec = MEASUREMENTS.get(getattr(value, "parameter_id", "") or "")
    return spec.quantity.value if spec is not None else "ratio"


def _interop_report(
    document: ReportDocument,
    *,
    study_uid: str,
    physician: str,
    receipt: SignatureReceipt | None = None,
    pdf_bytes: bytes | None = None,
    status: str = "F",
    now: datetime | None = None,
) -> InteropReport:
    patient = document.patient
    observations = tuple(
        InteropObservation(
            measurement_id=value.parameter_id or value.key or value.label,
            label=value.label,
            value=value.value,
            unit=value.unit,
            quantity=_quantity_of(value),
            norm=value.norm,
            pathological=bool(value.pathological),
            status=status,
        )
        for group in document.groups
        for value in group.values
        if value.value.strip()
    )
    current = now or datetime.now(timezone.utc)
    return InteropReport(
        patient=InteropPatient(
            patient_id=patient.patient_id,
            name=patient.name,
            birth_date=patient.birth_date,
            sex=patient.sex,
            study_date=patient.study_date,
            institution=patient.institution,
        ),
        study_uid=study_uid,
        observation_datetime=current.isoformat(),
        physician=physician or patient.physician,
        conclusion=patient.conclusion,
        observations=observations,
        pdf_bytes=pdf_bytes,
        status=status,
    )


class InteropExportService:
    """Build and send interop payloads for the active session."""

    def __init__(self, *, session: UserSessionService | None, now: Callable[[], datetime] | None = None) -> None:
        self._session = session
        self._now = now

    # ── HL7 v2 ───────────────────────────────────────────────────────

    def build_hl7(
        self,
        document: ReportDocument,
        *,
        study_uid: str,
        physician: str = "",
        receipt: SignatureReceipt | None = None,
        pdf_bytes: bytes | None = None,
        version: str = DEFAULT_HL7_VERSION,
        encoding: str = "utf-8",
        status: str = "F",
    ) -> bytes:
        """Render the ORU^R01 message bytes (signed PDF embedded when given)."""
        report = _interop_report(
            document,
            study_uid=study_uid,
            physician=physician,
            receipt=receipt,
            pdf_bytes=pdf_bytes,
            status=status,
            now=self._now() if self._now else None,
        )
        text = build_oru_r01(report, version=version)
        return encode_message(text, encoding=encoding)

    def export_hl7_file(self, document: ReportDocument, path: Path, **kwargs: Any) -> InteropExportResult:
        """Write the ``.hl7`` file atomically and audit the export."""
        payload = self.build_hl7(document, **kwargs)
        target = Path(path)
        tmp = target.with_suffix(target.suffix + ".tmp")
        # The .hl7 payload intentionally carries the signed report (OBX|ED) — that is the export feature.
        # codeql[py/cleartext-storage-sensitive-data]
        tmp.write_bytes(payload)
        tmp.replace(target)
        self._audit(PROTOCOL_HL7, "exported", study_uid=kwargs.get("study_uid", ""))
        return InteropExportResult(protocol=PROTOCOL_HL7, outcome="exported", path=target)

    def send_hl7(self, document: ReportDocument, *, client: Any, **kwargs: Any) -> Any:
        """Send via an :class:`Hl7MllpPort` adapter; returns the parsed ACK."""
        payload = self.build_hl7(document, **kwargs)
        ack = client.send_oru(payload, encoding=kwargs.get("encoding", "utf-8"))
        self._audit(
            PROTOCOL_HL7, "sent" if ack.accepted else "failed", study_uid=kwargs.get("study_uid", ""), status=ack.code
        )
        return ack

    # ── FHIR R4 ──────────────────────────────────────────────────────

    def build_fhir(
        self,
        document: ReportDocument,
        *,
        study_uid: str,
        physician: str = "",
        receipt: SignatureReceipt | None = None,
        pdf_bytes: bytes | None = None,
        bundle_type: str = "collection",
        status: str = "F",
    ) -> bytes:
        """Render the FHIR R4 Bundle JSON bytes."""
        report = _interop_report(
            document,
            study_uid=study_uid,
            physician=physician,
            receipt=receipt,
            pdf_bytes=pdf_bytes,
            status=status,
            now=self._now() if self._now else None,
        )
        signature = None
        if receipt is not None:
            signature = fhir_signature_entry(
                signed_at=receipt.signed_at,
                signer_reference="urn:uuid:practitioner",
                signature_b64=receipt.signature_b64,
                key_id=receipt.key_id,
            )
        bundle = build_fhir_bundle(
            report,
            bundle_type=bundle_type,
            signature=signature,
            report_hash=canonical_document_sha256(document),
        )
        return bundle_to_json(bundle)

    def export_fhir_file(self, document: ReportDocument, path: Path, **kwargs: Any) -> InteropExportResult:
        """Write the ``.fhir.json`` file atomically and audit the export."""
        payload = self.build_fhir(document, **kwargs)
        target = Path(path)
        tmp = target.with_suffix(target.suffix + ".tmp")
        # The .fhir.json payload intentionally carries the signed report (Provenance signature).
        # codeql[py/cleartext-storage-sensitive-data]
        tmp.write_bytes(payload)
        tmp.replace(target)
        self._audit(PROTOCOL_FHIR, "exported", study_uid=kwargs.get("study_uid", ""))
        return InteropExportResult(protocol=PROTOCOL_FHIR, outcome="exported", path=target)

    def send_fhir(self, document: ReportDocument, *, client: Any, **kwargs: Any) -> Any:
        """POST the Bundle via a :class:`FhirHttpPort` adapter."""
        payload = self.build_fhir(document, bundle_type="transaction", **kwargs)
        result = client.post_bundle(payload)
        self._audit(
            PROTOCOL_FHIR,
            "sent" if result.accepted else "failed",
            study_uid=kwargs.get("study_uid", ""),
            status=str(result.status_code),
        )
        return result

    # ── DICOM Encapsulated PDF ───────────────────────────────────────

    def build_encapsulated_pdf_spec(
        self,
        document: ReportDocument,
        *,
        study_uid: str,
        pdf_bytes: bytes,
        receipt: SignatureReceipt | None = None,
        sop_uid: str = "",
        series_uid: str = "",
    ) -> EncapsulatedPdfSpec:
        """Build the encapsulated-PDF spec from the document and signed PDF."""
        from echo_personal_tool.infrastructure.dicom_encapsulated_pdf import new_series_uid, new_sop_uid

        patient = document.patient
        observers: tuple[VerifyingObserver, ...] = ()
        if receipt is not None:
            label = receipt.signer_display_name + (f", {receipt.signer_title}" if receipt.signer_title else "")
            observers = (VerifyingObserver(name=label, organization=patient.institution, key_id=receipt.key_id),)
        return EncapsulatedPdfSpec(
            patient_name=patient.name,
            patient_id=patient.patient_id,
            birth_date=patient.birth_date,
            sex=patient.sex,
            study_uid=study_uid,
            series_uid=series_uid or new_series_uid(),
            sop_instance_uid=sop_uid or new_sop_uid(),
            study_date=patient.study_date,
            document_title=document.title or "Signed report",
            verifying_observers=observers or (VerifyingObserver(name=patient.physician or "SonoForge"),),
            pdf_bytes=pdf_bytes,
        )

    def send_encapsulated_pdf(
        self, spec: EncapsulatedPdfSpec, *, upload_client: Any = None, stow_client: Any = None, use_stow: bool = False
    ) -> bool:
        """Send the encapsulated PDF to PACS via STOW-RS or C-STORE."""
        from echo_personal_tool.infrastructure.dicom_encapsulated_pdf import send_encapsulated_pdf

        ok = send_encapsulated_pdf(spec, upload_client=upload_client, stow_client=stow_client, use_stow=use_stow)
        self._audit(PROTOCOL_DICOM_PDF, "sent" if ok else "failed", study_uid=spec.study_uid)
        return ok

    # ── audit ────────────────────────────────────────────────────────

    def _audit(self, protocol: str, outcome: str, *, study_uid: str = "", status: str = "") -> None:
        if self._session is None:
            return
        details: dict[str, str] = {"protocol": protocol, "outcome": outcome}
        if status:
            details["status"] = status
        self._session.record_study_audit(
            AuditAction.INTEROP_EXPORTED,
            study_key=study_key(study_uid) if study_uid else "",
            details=details,
        )
