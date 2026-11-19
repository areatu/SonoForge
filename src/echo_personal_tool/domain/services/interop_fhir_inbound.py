"""Pure FHIR R4 inbound parsers: ServiceRequest / Patient / DiagnosticReport /
Observation (#626). Mirrors the outbound shapes built by ``interop_fhir``.
"""

from __future__ import annotations

from typing import Any

from echo_personal_tool.domain.models.worklist import (
    OrderEvent,
    PatientDemographics,
    PriorResult,
)


class FhirParseError(ValueError):
    """Raised when an inbound FHIR resource cannot be parsed."""


def _coding_code(resource: dict[str, Any], path: tuple[str, ...]) -> str:
    node: Any = resource
    for key in path:
        if not isinstance(node, dict):
            return ""
        node = node.get(key)
    if not isinstance(node, dict):
        return ""
    codings = node.get("coding")
    if isinstance(codings, list) and codings and isinstance(codings[0], dict):
        return str(codings[0].get("code", ""))
    return ""


def _ref_id(reference: Any) -> str:
    if isinstance(reference, dict):
        ref = str(reference.get("reference", ""))
        return ref.rsplit("/", 1)[-1] if ref else ""
    return ""


def parse_patient(resource: dict[str, Any]) -> PatientDemographics:
    """FHIR Patient -> :class:`PatientDemographics`."""
    if resource.get("resourceType") != "Patient":
        raise FhirParseError("not_a_patient")
    names = resource.get("name") or []
    name = ""
    if names and isinstance(names[0], dict):
        parts = [names[0].get("family", ""), *names[0].get("given", [])]
        name = " ".join(str(p) for p in parts if p)
    identifiers = resource.get("identifier") or []
    mrn = ""
    for ident in identifiers:
        if isinstance(ident, dict) and ident.get("value"):
            mrn = str(ident["value"])
            break
    return PatientDemographics(
        patient_id=str(resource.get("id", "")),
        name=name,
        birth_date=str(resource.get("birthDate", "")),
        sex=str(resource.get("gender", "")).upper()[:1] if resource.get("gender") else "",
        mrn=mrn,
    )


def parse_service_request(resource: dict[str, Any]) -> OrderEvent:
    """FHIR ServiceRequest -> :class:`OrderEvent` (order control NW)."""
    if resource.get("resourceType") != "ServiceRequest":
        raise FhirParseError("not_a_service_request")
    patient_ref = resource.get("subject") or {}
    code = resource.get("code") or {}
    codings = code.get("coding") or []
    procedure_code = str(codings[0].get("code", "")) if codings and isinstance(codings[0], dict) else ""
    procedure_description = str(code.get("text", ""))
    occurrence = str(resource.get("occurrenceDateTime", ""))
    identifiers = resource.get("identifier") or []
    accession = ""
    for ident in identifiers:
        if isinstance(ident, dict):
            typ = ident.get("type") or {}
            if "Accession" in str(typ.get("text", "") if isinstance(typ, dict) else ""):
                accession = str(ident.get("value", ""))
                break
    if not accession and identifiers and isinstance(identifiers[0], dict):
        accession = str(identifiers[0].get("value", ""))
    return OrderEvent(
        message_type="ServiceRequest",
        order_control="NW",
        accession_number=accession,
        patient=PatientDemographics(patient_id=_ref_id(patient_ref)) if patient_ref else None,
        procedure_code=procedure_code,
        procedure_description=procedure_description,
        scheduled_datetime=occurrence,
        indications=str(resource.get("reasonCode", [{}])[0].get("text", "")) if resource.get("reasonCode") else "",
        source="fhir",
    )


def parse_observation(resource: dict[str, Any]) -> PriorResult:
    """FHIR Observation -> :class:`PriorResult` (LOINC code + UCUM unit)."""
    if resource.get("resourceType") != "Observation":
        raise FhirParseError("not_an_observation")
    quantity = resource.get("valueQuantity") or {}
    return PriorResult(
        patient_id=_ref_id(resource.get("subject")),
        loinc=_coding_code(resource, ("code",)),
        value=str(quantity.get("value", "")),
        unit=str(quantity.get("code", "")),
        effective_datetime=str(resource.get("effectiveDateTime", "")),
    )


def parse_diagnostic_report(resource: dict[str, Any]) -> list[PriorResult]:
    """FHIR DiagnosticReport -> its Observations (via contained/result refs)."""
    if resource.get("resourceType") != "DiagnosticReport":
        raise FhirParseError("not_a_diagnostic_report")
    patient_id = _ref_id(resource.get("subject"))
    report_id = str(resource.get("id", ""))
    results: list[PriorResult] = []
    for contained in resource.get("contained") or []:
        if isinstance(contained, dict) and contained.get("resourceType") == "Observation":
            obs = parse_observation(contained)
            results.append(
                PriorResult(
                    patient_id=obs.patient_id or patient_id,
                    loinc=obs.loinc,
                    value=obs.value,
                    unit=obs.unit,
                    effective_datetime=obs.effective_datetime,
                    report_id=report_id,
                )
            )
    return results


def parse_bundle(bundle: dict[str, Any]) -> tuple[list[OrderEvent], list[PatientDemographics], list[PriorResult]]:
    """Split a FHIR R4 Bundle into orders, patients and prior results."""
    if bundle.get("resourceType") != "Bundle":
        raise FhirParseError("not_a_bundle")
    orders: list[OrderEvent] = []
    patients: list[PatientDemographics] = []
    priors: list[PriorResult] = []
    for entry in bundle.get("entry") or []:
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(resource, dict):
            continue
        kind = resource.get("resourceType")
        if kind == "ServiceRequest":
            orders.append(parse_service_request(resource))
        elif kind == "Patient":
            patients.append(parse_patient(resource))
        elif kind == "Observation":
            priors.append(parse_observation(resource))
        elif kind == "DiagnosticReport":
            priors.extend(parse_diagnostic_report(resource))
    return orders, patients, priors
