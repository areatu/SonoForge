"""Pure HL7 CDA R2 (XML) document builder for the study report (#626).

Builds a ClinicalDocument with a structured body: one section per report
group, one observation per measured value coded with LOINC/UCUM from the
Stage-3 terminology dictionary. Pure ElementTree — no I/O.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from echo_personal_tool.domain.services.interop_hl7 import InteropObservation, InteropReport
from echo_personal_tool.domain.terminology.codes import LOINC_SYSTEM_URI, code_for
from echo_personal_tool.domain.terminology.units import ConversionError, to_canonical_ucum

CDA_NS = "urn:hl7-org:v3"


def _sub(parent: ET.Element, tag: str, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, f"{{{CDA_NS}}}{tag}")
    for key, value in attrs.items():
        el.set(key, value)
    return el


def _observation_xml(parent: ET.Element, obs: InteropObservation) -> None:
    code = code_for(obs.measurement_id)
    loinc = code.loinc or obs.measurement_id
    try:
        value, ucum = to_canonical_ucum(obs.value, obs.unit, obs.quantity) if obs.unit else (obs.value, "")
    except (ConversionError, ValueError):
        value, ucum = obs.value, obs.unit
    observation = _sub(parent, "observation", classCode="OBS", moodCode="EVN")
    _sub(observation, "code", code=loinc, codeSystem=LOINC_SYSTEM_URI, displayName=code.text or obs.label)
    _sub(observation, "statusCode", code="completed")
    value_el = _sub(observation, "value", xsi_type="PQ", value=value)
    if ucum:
        value_el.set("unit", ucum)
    if obs.norm:
        _sub(observation, "text").text = f"Reference range: {obs.norm}"


def build_cda_r2(report: InteropReport, *, title: str = "Echocardiography Study Report") -> str:
    """Render one report as a CDA R2 ClinicalDocument string."""
    ET.register_namespace("", CDA_NS)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root = ET.Element(f"{{{CDA_NS}}}ClinicalDocument")
    _sub(root, "realmCode", code="RU")
    _sub(root, "typeId", rootNamespace="2.16.840.1.113883.1.3", extension="POCD_HD000040")
    _sub(root, "templateId", root="2.16.840.1.113883.10.20.22.1.2", extension="2015-08-01")
    _sub(root, "id", root="1.2.840.10008.5.1.4.1.1.2.1", extension=report.study_uid or "local")
    _sub(root, "code", code="18748-4", codeSystem=LOINC_SYSTEM_URI, displayName="Diagnostic imaging report")
    _sub(
        root,
        "title",
    ).text = title
    _sub(root, "effectiveTime", value=report.observation_datetime.replace("-", "").replace(":", "")[:14] or "")
    _sub(root, "confidentialityCode", code="N", codeSystem="2.16.840.1.113883.5.25")
    record_target = _sub(root, "recordTarget")
    patient_role = _sub(record_target, "patientRole")
    _sub(patient_role, "id", root="1.2.840.10008.5.1.4.1.1.2.1", extension=report.patient.patient_id)
    patient = _sub(patient_role, "patient")
    name_el = _sub(patient, "name")
    parts = report.patient.name.split(" ", 1)
    _sub(name_el, "family").text = parts[0] if parts else ""
    if len(parts) > 1:
        _sub(name_el, "given").text = parts[1]
    _sub(patient, "administrativeGenderCode", code={"M": "M", "F": "F"}.get(report.patient.sex, "UN"))
    _sub(patient, "birthTime", value=report.patient.birth_date.replace("-", ""))
    author = _sub(root, "author")
    _sub(author, "assignedAuthor", classCode="ASSIGNED").append(
        ET.Element(f"{{{CDA_NS}}}id", root="1.2.840.10008.5.1.4.1.1.2.1")
    )
    component = _sub(root, "component")
    structured_body = _sub(component, "structuredBody")
    section = _sub(structured_body, "component")
    sec = _sub(section, "section")
    _sub(sec, "code", code="10210-3", codeSystem=LOINC_SYSTEM_URI, displayName="Echocardiography")
    _sub(sec, "title").text = "Measurements"
    text = _sub(sec, "text")
    for obs in report.observations:
        _sub(text, "paragraph").text = f"{obs.label}: {obs.value} {obs.unit}".strip()
    entry = _sub(sec, "entry")
    for obs in report.observations:
        _observation_xml(entry, obs)
    if report.conclusion:
        conclusion_section = _sub(structured_body, "component")
        csec = _sub(conclusion_section, "section")
        _sub(csec, "code", code="51848-0", codeSystem=LOINC_SYSTEM_URI, displayName="Evaluation summary")
        _sub(csec, "title").text = "Conclusion"
        _sub(csec, "text").text = report.conclusion
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
