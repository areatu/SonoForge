"""Map pynetdicom C-FIND Dataset responses to domain models."""

from __future__ import annotations

from pydicom.dataset import Dataset

from echo_personal_tool.domain.models.orthanc import InstanceInfo, SeriesInfo, StudyInfo


def _get_str(ds: Dataset, tag: str, default: str = "") -> str:
    """Extract a string value from a DICOM Dataset tag."""
    if hasattr(ds, tag):
        val = getattr(ds, tag)
        if val is not None:
            return str(val).strip()
    return default


def _get_int(ds: Dataset, tag: str) -> int | None:
    """Extract an integer value from a DICOM Dataset tag."""
    if hasattr(ds, tag):
        val = getattr(ds, tag)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                return None
    return None


def map_study(ds: Dataset) -> StudyInfo:
    """Map a C-FIND STUDY-level Dataset to StudyInfo."""
    return StudyInfo(
        study_uid=_get_str(ds, "StudyInstanceUID"),
        patient_name=_get_str(ds, "PatientName"),
        patient_id=_get_str(ds, "PatientID"),
        study_date=_get_str(ds, "StudyDate"),
        study_description=_get_str(ds, "StudyDescription"),
        series_count=_get_int(ds, "NumberOfStudyRelatedSeries"),
    )


def map_series(ds: Dataset, study_uid: str) -> SeriesInfo:
    """Map a C-FIND SERIES-level Dataset to SeriesInfo."""
    return SeriesInfo(
        series_uid=_get_str(ds, "SeriesInstanceUID"),
        study_uid=study_uid,
        modality=_get_str(ds, "Modality"),
        description=_get_str(ds, "SeriesDescription"),
        instance_count=_get_int(ds, "NumberOfSeriesRelatedInstances"),
    )


def map_instance(ds: Dataset, study_uid: str, series_uid: str) -> InstanceInfo:
    """Map a C-FIND IMAGE-level Dataset to InstanceInfo."""
    return InstanceInfo(
        sop_instance_uid=_get_str(ds, "SOPInstanceUID"),
        series_uid=series_uid,
        study_uid=study_uid,
    )
