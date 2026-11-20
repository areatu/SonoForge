"""Imported external reports and measurements (#619 follow-up: full inbound).

Pure data: no Qt, no I/O.  An :class:`ImportedReport` is a normalized incoming
report document — parsed from an HL7 v2 ORU^R01 message (OBX|NM measurements,
OBX|TX conclusion, OBX|ED embedded PDF) or from a FHIR R4 DiagnosticReport
(presentedForm PDF + contained Observations).  Unlike the worklist events of
``models.worklist``, these carry the *content* of an external study/report,
not just its scheduling.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field

from echo_personal_tool.domain.models.worklist import PatientDemographics


@dataclass
class ImportedMeasurement:
    """One numeric/text result inside an imported report."""

    code: str  # LOINC or local measurement identifier (OBX-3 / Observation.code)
    text: str = ""  # human-readable label
    value: str = ""
    unit: str = ""  # UCUM
    norm: str = ""  # reference range text
    flag: str = ""  # HL7 OBX-8 abnormal flag (N/H/L) or FHIR interpretation
    status: str = ""  # HL7 OBX-11 result status (P/F/C)
    datetime: str = ""  # ISO-8601 observation time

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "text": self.text,
            "value": self.value,
            "unit": self.unit,
            "norm": self.norm,
            "flag": self.flag,
            "status": self.status,
            "datetime": self.datetime,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> ImportedMeasurement:
        return cls(
            code=str(data.get("code", "")),
            text=str(data.get("text", "")),
            value=str(data.get("value", "")),
            unit=str(data.get("unit", "")),
            norm=str(data.get("norm", "")),
            flag=str(data.get("flag", "")),
            status=str(data.get("status", "")),
            datetime=str(data.get("datetime", "")),
        )


@dataclass
class ImportedReport:
    """A full external report imported over HL7 v2 or FHIR."""

    report_id: str
    source: str  # "hl7" | "fhir"
    patient: PatientDemographics | None = None
    accession_number: str = ""
    procedure_code: str = ""
    procedure_description: str = ""
    physician: str = ""
    conclusion: str = ""
    status: str = "F"
    observed_at: str = ""  # ISO-8601
    received_at: str = ""  # ISO-8601, set by the application layer
    measurements: list[ImportedMeasurement] = field(default_factory=list)
    pdf_bytes: bytes | None = None
    pdf_title: str = ""

    @property
    def patient_id(self) -> str:
        return self.patient.patient_id if self.patient is not None else ""

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "source": self.source,
            "patient": self.patient.to_dict() if self.patient is not None else None,
            "accession_number": self.accession_number,
            "procedure_code": self.procedure_code,
            "procedure_description": self.procedure_description,
            "physician": self.physician,
            "conclusion": self.conclusion,
            "status": self.status,
            "observed_at": self.observed_at,
            "received_at": self.received_at,
            "measurements": [m.to_dict() for m in self.measurements],
            "pdf": base64.b64encode(self.pdf_bytes).decode("ascii") if self.pdf_bytes is not None else None,
            "pdf_title": self.pdf_title,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ImportedReport:
        patient_data = data.get("patient")
        patient = PatientDemographics.from_dict(patient_data) if isinstance(patient_data, dict) else None
        pdf_text = data.get("pdf")
        pdf_bytes: bytes | None = None
        if isinstance(pdf_text, str) and pdf_text:
            try:
                pdf_bytes = base64.b64decode(pdf_text.encode("ascii"), validate=True)
            except (ValueError, binascii.Error):
                pdf_bytes = None
        measurements_raw = data.get("measurements")
        measurements = (
            [ImportedMeasurement.from_dict(m) for m in measurements_raw if isinstance(m, dict)]
            if isinstance(measurements_raw, list)
            else []
        )
        return cls(
            report_id=str(data.get("report_id", "")),
            source=str(data.get("source", "")),
            patient=patient,
            accession_number=str(data.get("accession_number", "")),
            procedure_code=str(data.get("procedure_code", "")),
            procedure_description=str(data.get("procedure_description", "")),
            physician=str(data.get("physician", "")),
            conclusion=str(data.get("conclusion", "")),
            status=str(data.get("status", "F")),
            observed_at=str(data.get("observed_at", "")),
            received_at=str(data.get("received_at", "")),
            measurements=measurements,
            pdf_bytes=pdf_bytes,
            pdf_title=str(data.get("pdf_title", "")),
        )
