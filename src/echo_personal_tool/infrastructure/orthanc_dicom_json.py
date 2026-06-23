"""Parse Orthanc QIDO-RS `application/dicom+json` responses."""

from __future__ import annotations

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo

TAG_PATIENT_NAME = "00100010"
TAG_PATIENT_ID = "00100020"
TAG_STUDY_DATE = "00080020"
TAG_SOP_INSTANCE_UID = "00080018"
TAG_MODALITY = "00080060"
TAG_STUDY_INSTANCE_UID = "0020000D"
TAG_SERIES_INSTANCE_UID = "0020000E"
TAG_STUDY_DESCRIPTION = "00081030"
TAG_SERIES_DESCRIPTION = "0008103E"


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
        )
        for item in payload
    ]


def parse_instances(
    payload: list[dict], study_uid: str, series_uid: str
) -> list[InstanceInfo]:
    return [
        InstanceInfo(
            sop_instance_uid=tag_value(item, TAG_SOP_INSTANCE_UID),
            series_uid=series_uid,
            study_uid=study_uid,
        )
        for item in payload
    ]
