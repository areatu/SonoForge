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
