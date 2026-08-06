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


def tag_value(item: dict, tag: str, default: str = "") -> str:
    node = item.get(tag) or {}
    values = node.get("Value") or []
    if not values:
        return default
    first = values[0]
    if isinstance(first, dict):
        return str(first.get("Alphabetic", default))
    return str(first)


def parse_studies(payload: list[dict]) -> list[StudyInfo]:
    return [
        StudyInfo(
            study_uid=tag_value(item, TAG_STUDY_INSTANCE_UID),
            patient_name=tag_value(item, TAG_PATIENT_NAME),
            patient_id=tag_value(item, TAG_PATIENT_ID),
            study_date=tag_value(item, TAG_STUDY_DATE),
            study_description=tag_value(item, TAG_STUDY_DESCRIPTION),
        )
        for item in payload
    ]


def parse_series(payload: list[dict], study_uid: str) -> list[SeriesInfo]:
    return [
        SeriesInfo(
            series_uid=tag_value(item, TAG_SERIES_INSTANCE_UID),
            study_uid=study_uid,
            modality=tag_value(item, TAG_MODALITY),
            description=tag_value(item, TAG_SERIES_DESCRIPTION),
            instance_count=(int(c) if (c := tag_value(item, TAG_NUMBER_OF_SERIES_RELATED_INSTANCES)) else None),
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
