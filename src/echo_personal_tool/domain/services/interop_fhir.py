"""FHIR R4 Bundle builder for study results and the signed report (#625).

Pure domain module (standard library only): renders a ``Bundle``
(``collection`` for file export, ``transaction`` for send) containing
``Patient``, ``Practitioner`` (the signer), ``ImagingStudy``,
``Observation`` per measured value (LOINC code, UCUM ``valueQuantity``,
reference range, interpretation, status), ``DiagnosticReport`` with the
signed PDF as ``presentedForm`` and a ``Provenance`` whose ``signature``
carries the Ed25519 signature over the canonical document hash.

Only R4 core resources are used; no profiles are claimed.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, cast

from echo_personal_tool.domain.services.interop_hl7 import (
    InteropObservation,
    InteropReport,
)
from echo_personal_tool.domain.terminology import (
    LOCAL_CODE_SYSTEM_URI,
    UCUM_SYSTEM,
    code_for,
)
from echo_personal_tool.domain.terminology.units import ConversionError, to_canonical_ucum

_UTC = timezone.utc  # noqa: UP017 - aligned with ruff target py310

FHIR_VERSION = "4.0.1"


class FhirBuildError(ValueError):
    """The interop DTO cannot be rendered as FHIR (safe code, no PHI)."""


def _iso_now() -> str:
    return datetime.now(_UTC).isoformat()


def _iso(value: str, *, fallback: str | None = None) -> str:
    """Normalise an ISO-8601 string for FHIR (instant/dateTime); fallback when empty/invalid."""
    text = (value or "").strip()
    if text:
        try:
            return datetime.fromisoformat(text).astimezone(_UTC).isoformat()
        except ValueError:
            pass
    if fallback is not None:
        return fallback
    return _iso_now()


def _codeable(code_text: str, codings: tuple[tuple[str, str, str], ...]) -> dict:
    """FHIR CodeableConcept from ``(system_name, code, system_uri)`` triples."""
    return {
        "coding": [{"system": uri, "code": code, "display": code_text} for _system, code, uri in codings],
        "text": code_text,
    }


def _observation_resource(obs: InteropObservation, *, study_ref: str, performer_ref: str) -> dict:
    code = code_for(obs.measurement_id)
    try:
        canonical_value, ucum = to_canonical_ucum(obs.value, obs.unit, obs.quantity)
        numeric = float(canonical_value.replace(",", "."))
    except (ValueError, ConversionError):  # non-numeric values fall back to valueString
        numeric = None
    resource: dict = {
        "resourceType": "Observation",
        "id": f"obs-{obs.measurement_id}".replace(".", "-"),
        "status": "final" if (obs.status or "F") == "F" else ("preliminary" if obs.status == "P" else "corrected"),
        "code": _codeable(obs.label, code.coding_systems()),
        "subject": {"reference": "urn:uuid:patient"},
        "effectiveDateTime": _iso_now(),
        "performer": [{"reference": performer_ref}],
        "focus": [{"reference": study_ref}],
    }
    if numeric is not None:
        resource["valueQuantity"] = {
            "value": numeric,
            "unit": ucum,
            "system": UCUM_SYSTEM,
            "code": ucum,
        }
    else:
        resource["valueString"] = obs.value
    if obs.norm:
        resource["referenceRange"] = [{"text": obs.norm}]
    resource["interpretation"] = [
        {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                    "code": "A" if obs.pathological else "N",
                }
            ]
        }
    ]
    return resource


def build_fhir_bundle(
    report: InteropReport,
    *,
    bundle_type: str = "collection",
    signature: dict | None = None,
    report_hash: str = "",
) -> dict:
    """Render the FHIR R4 Bundle for *report*.

    ``signature`` is an optional FHIR ``Provenance.signature`` entry
    (``sigFormat``/``when``/``who``/``data``) built from the local Ed25519
    receipt; ``report_hash`` is the canonical document SHA-256 the signature
    covers, embedded as a Provenance extension-free annotation.
    """
    if bundle_type not in ("collection", "transaction"):
        raise FhirBuildError("unsupported_bundle_type")
    patient = report.patient
    entries: list[dict] = []

    entries.append(
        {
            "fullUrl": "urn:uuid:patient",
            "resource": {
                "resourceType": "Patient",
                "id": "pat",
                "identifier": [{"system": "urn:sonoforge:local", "value": patient.patient_id}]
                if patient.patient_id
                else [],
                "name": [{"text": patient.name}] if patient.name else [],
                "birthDate": patient.birth_date or None,
                "gender": {"M": "male", "F": "female"}.get((patient.sex or "").strip().upper(), "unknown"),
            },
        }
    )
    entries.append(
        {
            "fullUrl": "urn:uuid:practitioner",
            "resource": {
                "resourceType": "Practitioner",
                "id": "practitioner",
                "name": [{"text": report.physician}] if report.physician else [],
            },
        }
    )
    study_ref = "urn:uuid:imagingstudy"
    entries.append(
        {
            "fullUrl": study_ref,
            "resource": {
                "resourceType": "ImagingStudy",
                "id": "imagingstudy",
                "status": "available",
                "subject": {"reference": "urn:uuid:patient"},
                "started": _iso(patient.study_date) if patient.study_date else None,
                "identifier": [{"system": "urn:dicom:uid", "value": report.study_uid}] if report.study_uid else [],
            },
        }
    )
    for obs in report.observations:
        entries.append(
            {
                "fullUrl": f"urn:uuid:{obs.measurement_id}".replace(".", "-"),
                "resource": _observation_resource(obs, study_ref=study_ref, performer_ref="urn:uuid:practitioner"),
            }
        )

    presented_form = []
    if report.pdf_bytes:
        presented_form.append(
            {
                "contentType": "application/pdf",
                "title": report.pdf_title,
                "data": base64.b64encode(report.pdf_bytes).decode("ascii"),
            }
        )
    diagnostic_report: dict = {
        "resourceType": "DiagnosticReport",
        "id": "report",
        "status": "final" if report.status == "F" else ("preliminary" if report.status == "P" else "corrected"),
        "code": _codeable(
            "Echocardiography report",
            (("99SONOFORGE", "ECHO-RPT", LOCAL_CODE_SYSTEM_URI),),
        ),
        "subject": {"reference": "urn:uuid:patient"},
        "study": {"reference": study_ref},
        "effectiveDateTime": _iso(patient.study_date),
        "issued": _iso(report.observation_datetime),
        "performer": [{"reference": "urn:uuid:practitioner"}],
        "conclusion": report.conclusion or None,
        "presentedForm": presented_form or None,
    }
    entries.append({"fullUrl": "urn:uuid:diagnosticreport", "resource": diagnostic_report})

    provenance: dict = {
        "resourceType": "Provenance",
        "id": "provenance",
        "target": [{"reference": "urn:uuid:diagnosticreport"}],
        "recorded": _iso(report.observation_datetime),
        "agent": [{"who": {"reference": "urn:uuid:practitioner"}}],
    }
    if report_hash:
        provenance["note"] = [{"text": f"canonical document sha256: {report_hash}"}]
    if signature is not None:
        provenance["signature"] = [signature]
    entries.append({"fullUrl": "urn:uuid:provenance", "resource": provenance})

    # Drop None values to keep the JSON clean.
    def _clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: _clean(item) for key, item in value.items() if item is not None}
        if isinstance(value, list):
            return [_clean(item) for item in value]
        return value

    cleaned = _clean(
        {
            "resourceType": "Bundle",
            "type": bundle_type,
            "id": "sonoforge-interop",
            "meta": {"versionId": "1", "lastUpdated": _iso_now()},
            "entry": entries,
        }
    )
    return cast("dict[str, Any]", cleaned)


def fhir_signature_entry(*, signed_at: str, signer_reference: str, signature_b64: str, key_id: str) -> dict:
    """One FHIR R4 ``Provenance.signature`` (Signature datatype) for the local Ed25519 key."""
    return {
        "type": [
            {
                "system": "urn:iso:astm:E1762-95:2013",
                "code": "1.2.840.10065.1.12.1.1",  # digital signature, non-repudiation
                "display": "Digital Signature",
            }
        ],
        "when": _iso(signed_at),
        "who": {"reference": signer_reference},
        "sigFormat": "application/ed25519+base64",
        "data": signature_b64,
        "extension": [
            {"url": "https://sonoforge.local/fhir/signing-key-id", "valueString": key_id},
            {"url": "https://sonoforge.local/fhir/signature-scope", "valueString": "local-app-ep-not-qes"},
        ],
    }


def bundle_to_json(bundle: dict) -> bytes:
    """Serialize a bundle deterministically (sorted keys, UTF-8)."""
    return json.dumps(bundle, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
