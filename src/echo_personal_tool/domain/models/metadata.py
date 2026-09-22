"""Domain metadata models (no pydicom / Qt dependencies)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class InstanceRef:
    """Lightweight reference to a DICOM file on disk."""

    path: Path
    sop_instance_uid: str
    series_uid: str
    study_uid: str


@dataclass(frozen=True)
class InstanceMetadata:
    sop_instance_uid: str
    series_uid: str
    modality: str
    number_of_frames: int
    pixel_spacing: tuple[float, float] | None
    frame_time_ms: float | None
    series_description: str
    path: Path | None = None
    media_format: str = "dicom"
    pixel_spacing_source: str | None = None
    frame_time_vector: tuple[float, ...] | None = None
    patient_height_m: float | None = None
    patient_weight_kg: float | None = None


@dataclass(frozen=True)
class PatientDemographics:
    """Header fields a study report shows about the patient.

    Values are already display-ready strings (``17.05.2024``), because they are
    meant to be edited in the report dialog before printing, not re-parsed.
    """

    name: str = ""
    patient_id: str = ""
    birth_date: str = ""
    #: Completed years at the study date; empty when either date is unknown.
    age: str = ""
    sex: str = ""
    study_date: str = ""
    institution: str = ""
    equipment: str = ""
    referring_physician: str = ""
    height_m: float | None = None
    weight_kg: float | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.name,
                self.patient_id,
                self.birth_date,
                self.age,
                self.sex,
                self.study_date,
                self.institution,
                self.equipment,
                self.referring_physician,
            )
        )


@dataclass(frozen=True)
class SeriesMetadata:
    series_uid: str
    study_uid: str
    modality: str
    description: str
    instances: tuple[InstanceMetadata, ...]


@dataclass(frozen=True)
class StudyMetadata:
    study_uid: str
    study_datetime: datetime
    series: tuple[SeriesMetadata, ...]
