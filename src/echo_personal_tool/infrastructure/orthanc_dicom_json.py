"""Parse Orthanc QIDO-RS `application/dicom+json` responses."""

from __future__ import annotations

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo
from echo_personal_tool.domain.services.dicom_tag_dictionary import (
    MODALITY,
    NUMBER_OF_SERIES_RELATED_INSTANCES,
    PATIENT_ID,
    PATIENT_NAME,
    SERIES_DESCRIPTION,
    SERIES_INSTANCE_UID,
    SOP_INSTANCE_UID,
    STUDY_DATE,
    STUDY_DESCRIPTION,
    STUDY_INSTANCE_UID,
)


def _tag_hex(tag_int: int) -> str:
    return f"{tag_int:08X}"


TAG_PATIENT_NAME = _tag_hex(PATIENT_NAME)
TAG_PATIENT_ID = _tag_hex(PATIENT_ID)
TAG_STUDY_DATE = _tag_hex(STUDY_DATE)
TAG_SOP_INSTANCE_UID = _tag_hex(SOP_INSTANCE_UID)
TAG_MODALITY = _tag_hex(MODALITY)
TAG_STUDY_INSTANCE_UID = _tag_hex(STUDY_INSTANCE_UID)
TAG_SERIES_INSTANCE_UID = _tag_hex(SERIES_INSTANCE_UID)
TAG_STUDY_DESCRIPTION = _tag_hex(STUDY_DESCRIPTION)
TAG_SERIES_DESCRIPTION = _tag_hex(SERIES_DESCRIPTION)
TAG_NUMBER_OF_SERIES_RELATED_INSTANCES = _tag_hex(NUMBER_OF_SERIES_RELATED_INSTANCES)

# ── Optional enrichment tags (patient context, counts, order) ──────
TAG_PATIENT_BIRTH_DATE = "00100030"  # PatientBirthDate
TAG_PATIENT_SEX = "00100040"  # PatientSex
TAG_STUDY_TIME = "00080030"  # StudyTime
TAG_ACCESSION_NUMBER = "00080050"  # AccessionNumber
TAG_INSTITUTION_NAME = "00080080"  # InstitutionName
TAG_MODALITIES_IN_STUDY = "00080061"  # ModalitiesInStudy
TAG_NUMBER_OF_STUDY_RELATED_SERIES = "00201206"  # NumberOfStudyRelatedSeries
TAG_NUMBER_OF_STUDY_RELATED_INSTANCES = "00201208"  # NumberOfStudyRelatedInstances
TAG_SERIES_NUMBER = "00200011"  # SeriesNumber
TAG_BODY_PART_EXAMINED = "00180015"  # BodyPartExamined


def tag_value(item: dict, tag: str, default: str = "") -> str:
    node = item.get(tag) or {}
    values = node.get("Value") or []
    if not values:
        return default
    first = values[0]
    if isinstance(first, dict):
        return str(first.get("Alphabetic", default))
    return str(first)


def _as_int(value: str) -> int | None:
    """Parse an integer tag value, returning None on non-numeric values.

    A malformed NumberOfSeriesRelatedInstances must not break the parsing
    of the whole series list.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_studies(payload: list[dict]) -> list[StudyInfo]:
    return [
        StudyInfo(
            study_uid=tag_value(item, TAG_STUDY_INSTANCE_UID),
            patient_name=tag_value(item, TAG_PATIENT_NAME),
            patient_id=tag_value(item, TAG_PATIENT_ID),
            study_date=tag_value(item, TAG_STUDY_DATE),
            study_description=tag_value(item, TAG_STUDY_DESCRIPTION),
            series_count=_as_int(tag_value(item, TAG_NUMBER_OF_STUDY_RELATED_SERIES)) or None,
            patient_birth_date=tag_value(item, TAG_PATIENT_BIRTH_DATE),
            patient_sex=tag_value(item, TAG_PATIENT_SEX),
            study_time=tag_value(item, TAG_STUDY_TIME),
            accession_number=tag_value(item, TAG_ACCESSION_NUMBER),
            institution_name=tag_value(item, TAG_INSTITUTION_NAME),
            modalities_in_study=_as_multi_value(tag_value(item, TAG_MODALITIES_IN_STUDY)),
            instances_count=_as_int(tag_value(item, TAG_NUMBER_OF_STUDY_RELATED_INSTANCES)) or None,
        )
        for item in payload
    ]


def _as_multi_value(raw: str) -> str:
    """Normalise a DICOM multi-value tag to a single display string.

    DICOMweb returns ``ModalitiesInStudy`` as a list of several values; Orthanc
    flattens it with the DICOM backslash separator.  Both become ``"US, XA"``.
    """
    text = (raw or "").strip().strip('"[]')
    if not text:
        return ""
    parts = [part.strip().strip('"') for part in text.replace("\\", ",").split(",")]
    unique: list[str] = []
    for part in parts:
        if part and part not in unique:
            unique.append(part)
    return ", ".join(unique)


def parse_series(payload: list[dict], study_uid: str) -> list[SeriesInfo]:
    return [
        SeriesInfo(
            series_uid=tag_value(item, TAG_SERIES_INSTANCE_UID),
            study_uid=study_uid,
            modality=tag_value(item, TAG_MODALITY),
            description=tag_value(item, TAG_SERIES_DESCRIPTION),
            instance_count=_as_int(tag_value(item, TAG_NUMBER_OF_SERIES_RELATED_INSTANCES)) or None,
            series_number=_as_int(tag_value(item, TAG_SERIES_NUMBER)),
            body_part=tag_value(item, TAG_BODY_PART_EXAMINED),
        )
        for item in payload
    ]


def parse_instances(payload: list[dict], study_uid: str, series_uid: str) -> list[InstanceInfo]:
    return [
        InstanceInfo(
            sop_instance_uid=tag_value(item, TAG_SOP_INSTANCE_UID),
            series_uid=series_uid,
            study_uid=study_uid,
        )
        for item in payload
    ]
