"""Orthanc DICOMweb query result models (no HTTP / Qt dependencies)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StudyInfo:
    """One row of the server study list.

    Only the first five fields are guaranteed: they are the minimum a QIDO-RS
    answer can carry.  The rest is filled in when the server exposes the
    corresponding DICOM tags (see ``_STUDY_INCLUDE_FIELDS`` in the Orthanc
    client) and stay empty otherwise, so the UI degrades gracefully instead of
    inventing data.
    """

    study_uid: str
    patient_name: str
    patient_id: str
    study_date: str
    study_description: str
    series_count: int | None = None
    # ── Optional enrichment (patient / study context) ──────────────
    patient_birth_date: str = ""
    patient_sex: str = ""
    study_time: str = ""
    accession_number: str = ""
    institution_name: str = ""
    modalities_in_study: str = ""
    instances_count: int | None = None


@dataclass(frozen=True)
class SeriesInfo:
    series_uid: str
    study_uid: str
    modality: str
    description: str
    instance_count: int | None = None
    series_number: int | None = None
    body_part: str = ""


@dataclass(frozen=True)
class StudyStatistics:
    """Sizes/status reported by the Orthanc ``/statistics`` route.

    Pure DICOMweb servers do not have this endpoint, so every field is
    optional and the UI simply omits what it cannot know.
    """

    instances: int | None = None
    series: int | None = None
    size_mb: float | None = None
    is_stable: bool | None = None
    last_update: str = ""


@dataclass(frozen=True)
class InstanceInfo:
    sop_instance_uid: str
    series_uid: str
    study_uid: str


@dataclass(frozen=True)
class StowResult:
    """Result of STOW-RS or batch C-STORE upload."""

    success_count: int
    failed_uids: list[str] = field(default_factory=list)
    error_message: str = ""
