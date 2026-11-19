"""Worklist and patient-index domain models for inbound interop (#626).

Pure data: no Qt, no I/O, no pydicom. Inbound HL7 v2 (ORM/ADT) and FHIR R4
sources are normalized into these models by the application layer, and the
MWL/MPPS servers read them back out for DICOM peers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class WorklistStatus(str, Enum):
    """Scheduled procedure lifecycle as seen by MWL/MPPS."""

    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISCONTINUED = "DISCONTINUED"


class OrderControl(str, Enum):
    """HL7 v2 Table 0119 order control codes handled on intake."""

    NEW = "NW"
    CANCEL = "CA"
    REPLACE = "XO"


class AdtEvent(str, Enum):
    """HL7 v2 ADT trigger events handled on intake."""

    ADMIT = "A01"
    REGISTER = "A04"
    UPDATE = "A08"
    MERGE = "A40"
    DEMOGRAPHICS = "A31"


@dataclass(frozen=True)
class PatientDemographics:
    """Normalized patient identity/demographics (PID in HL7, Patient in FHIR)."""

    patient_id: str
    name: str = ""
    birth_date: str = ""  # ISO YYYY-MM-DD
    sex: str = ""  # M | F | O
    mrn: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "patient_id": self.patient_id,
            "name": self.name,
            "birth_date": self.birth_date,
            "sex": self.sex,
            "mrn": self.mrn,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> PatientDemographics:
        return cls(
            patient_id=data.get("patient_id", ""),
            name=data.get("name", ""),
            birth_date=data.get("birth_date", ""),
            sex=data.get("sex", ""),
            mrn=data.get("mrn", ""),
        )


@dataclass(frozen=True)
class PatientMerge:
    """An ADT^A40 MRG: ``source_id`` is merged into ``target_id``."""

    source_id: str
    target_id: str


@dataclass(frozen=True)
class OrderEvent:
    """One parsed ORM^O01 / OMG^O19 order (or a FHIR ServiceRequest)."""

    message_type: str  # e.g. "ORM^O01"
    order_control: str  # NW | XO | CA
    accession_number: str = ""
    placer_order_number: str = ""
    patient: PatientDemographics | None = None
    procedure_code: str = ""
    procedure_description: str = ""
    scheduled_datetime: str = ""  # ISO
    scheduled_station_ae: str = ""
    referring_physician: str = ""
    indications: str = ""
    study_instance_uid: str = ""
    source: str = "hl7"  # hl7 | fhir

    @property
    def control(self) -> OrderControl | None:
        try:
            return OrderControl(self.order_control)
        except ValueError:
            return None


@dataclass(frozen=True)
class DemographicsEvent:
    """One parsed ADT^A01/A04/A08/A31/A40 message."""

    event: str  # A01 | A04 | A08 | A31 | A40
    patient: PatientDemographics | None = None
    merge: PatientMerge | None = None
    source: str = "hl7"


@dataclass
class WorklistItem:
    """One scheduled procedure (a worklist entry / MWL item)."""

    accession_number: str
    patient_id: str
    patient_name: str = ""
    birth_date: str = ""
    sex: str = ""
    procedure_code: str = ""
    procedure_description: str = ""
    scheduled_datetime: str = ""
    scheduled_station_ae: str = ""
    referring_physician: str = ""
    indications: str = ""
    study_instance_uid: str = ""
    status: WorklistStatus = WorklistStatus.SCHEDULED
    source: str = "hl7"
    updated_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "accession_number": self.accession_number,
            "patient_id": self.patient_id,
            "patient_name": self.patient_name,
            "birth_date": self.birth_date,
            "sex": self.sex,
            "procedure_code": self.procedure_code,
            "procedure_description": self.procedure_description,
            "scheduled_datetime": self.scheduled_datetime,
            "scheduled_station_ae": self.scheduled_station_ae,
            "referring_physician": self.referring_physician,
            "indications": self.indications,
            "study_instance_uid": self.study_instance_uid,
            "status": self.status.value,
            "source": self.source,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> WorklistItem:
        try:
            status = WorklistStatus(data.get("status", WorklistStatus.SCHEDULED.value))
        except ValueError:
            status = WorklistStatus.SCHEDULED
        return cls(
            accession_number=data.get("accession_number", ""),
            patient_id=data.get("patient_id", ""),
            patient_name=data.get("patient_name", ""),
            birth_date=data.get("birth_date", ""),
            sex=data.get("sex", ""),
            procedure_code=data.get("procedure_code", ""),
            procedure_description=data.get("procedure_description", ""),
            scheduled_datetime=data.get("scheduled_datetime", ""),
            scheduled_station_ae=data.get("scheduled_station_ae", ""),
            referring_physician=data.get("referring_physician", ""),
            indications=data.get("indications", ""),
            study_instance_uid=data.get("study_instance_uid", ""),
            status=status,
            source=data.get("source", "hl7"),
            updated_at=data.get("updated_at", ""),
        )


@dataclass(frozen=True)
class MppsUpdate:
    """MPPS N-CREATE/N-SET: lifecycle change of a scheduled procedure."""

    accession_number: str
    status: WorklistStatus  # IN_PROGRESS | COMPLETED | DISCONTINUED
    sop_instance_uid: str = ""
    performed_series: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PriorResult:
    """A previous DiagnosticReport/Observation pulled over FHIR inbound."""

    patient_id: str
    loinc: str = ""
    value: str = ""
    unit: str = ""
    effective_datetime: str = ""
    report_id: str = ""
