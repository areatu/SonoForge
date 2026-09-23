"""Map pydicom.Dataset to domain metadata dataclasses."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset

from echo_personal_tool.domain.models import InstanceMetadata, PatientDemographics
from echo_personal_tool.domain.services.pixel_spacing_resolver import resolve_pixel_spacing
from echo_personal_tool.infrastructure.dicom_frame_count import infer_dicom_frame_count


def _parse_study_datetime(study_date: str | None, study_time: str | None) -> datetime:
    date_part = (study_date or "19700101").strip()
    time_part = (study_time or "000000").split(".")[0].strip()
    time_part = time_part.ljust(6, "0")[:6]
    return datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S")


def _pixel_spacing(dataset: Dataset) -> tuple[tuple[float, float] | None, str | None]:
    resolution = resolve_pixel_spacing(dataset)
    if resolution is None:
        return None, None
    return resolution.spacing, resolution.source


def _frame_time_ms(dataset: Dataset) -> float | None:
    frame_time = dataset.get("FrameTime")
    if frame_time is not None:
        return float(frame_time)
    cine_rate = dataset.get("CineRate")
    if cine_rate:
        rate = float(cine_rate)
        if rate > 0:
            return 1000.0 / rate
    return None


def _frame_time_vector(dataset: Dataset) -> tuple[float, ...] | None:
    """Parse FrameTimeVector (0018,1065) for per-frame timing."""
    if not hasattr(dataset, "FrameTimeVector"):
        return None
    raw = dataset.FrameTimeVector
    try:
        return tuple(float(x) for x in raw)
    except (TypeError, ValueError):
        return None


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def map_instance_metadata(
    dataset: Dataset, path: Path | None = None, *, pixel_data: bytes | None = None
) -> InstanceMetadata:
    """Convert a DICOM dataset (header or full) to InstanceMetadata."""
    number_of_frames = infer_dicom_frame_count(dataset, pixel_data=pixel_data)
    series_description = str(dataset.get("SeriesDescription", "") or "").strip()
    spacing, spacing_source = _pixel_spacing(dataset)
    return InstanceMetadata(
        sop_instance_uid=str(dataset.get("SOPInstanceUID", "") or ""),
        series_uid=str(dataset.get("SeriesInstanceUID", "") or ""),
        modality=str(dataset.get("Modality", "OT") or "OT"),
        number_of_frames=number_of_frames,
        pixel_spacing=spacing,
        pixel_spacing_source=spacing_source,
        frame_time_ms=_frame_time_ms(dataset),
        frame_time_vector=_frame_time_vector(dataset),
        series_description=series_description,
        path=path,
        media_format="dicom",
        patient_height_m=_safe_float(dataset.get("PatientSize")),
        patient_weight_kg=_safe_float(dataset.get("PatientWeight")),
    )


def read_header_metadata(path: Path) -> InstanceMetadata:
    """Read DICOM metadata without loading pixel data."""
    dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    return map_instance_metadata(dataset, path=path)


def _patient_name_text(value) -> str:
    """Flatten a pydicom PersonName (``Last^First^Middle``) to one line."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    parts = [part.strip() for part in text.split("^") if part.strip()]
    if len(parts) >= 2:
        # DICOM order is family^given^middle; reports read given name first.
        return " ".join([parts[1], *parts[2:], parts[0]])
    return text


def _dicom_date_text(value) -> str:
    """``20240517`` → ``17.05.2024``; anything unparseable is returned as is."""
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return text
    return f"{text[6:8]}.{text[4:6]}.{text[0:4]}"


def _age_years(birth_date: str | None, study_date: str | None) -> str:
    """Completed years between two DICOM dates (``YYYYMMDD``); "" if unknown."""
    birth = str(birth_date or "").strip()
    study = str(study_date or "").strip() or datetime.now().strftime("%Y%m%d")
    try:
        born = datetime.strptime(birth[:8], "%Y%m%d")
        examined = datetime.strptime(study[:8], "%Y%m%d")
    except ValueError:
        return ""
    age = examined.year - born.year - ((examined.month, examined.day) < (born.month, born.day))
    return str(age) if 0 <= age < 130 else ""


def map_patient_demographics(dataset: Dataset) -> PatientDemographics:
    """Read the header fields a study report shows about the patient."""
    birth_date = str(dataset.get("PatientBirthDate", "") or "")
    study_date = str(dataset.get("StudyDate", "") or "")
    return PatientDemographics(
        name=_patient_name_text(dataset.get("PatientName")),
        patient_id=str(dataset.get("PatientID", "") or "").strip(),
        birth_date=_dicom_date_text(birth_date),
        age=_age_years(birth_date, study_date),
        sex=str(dataset.get("PatientSex", "") or "").strip(),
        study_date=_dicom_date_text(study_date),
        institution=str(dataset.get("InstitutionName", "") or "").strip(),
        equipment=" ".join(
            part
            for part in (
                str(dataset.get("Manufacturer", "") or "").strip(),
                str(dataset.get("ManufacturerModelName", "") or "").strip(),
            )
            if part
        ),
        referring_physician=_patient_name_text(dataset.get("ReferringPhysicianName")),
        height_m=_safe_float(dataset.get("PatientSize")),
        weight_kg=_safe_float(dataset.get("PatientWeight")),
    )


def read_patient_demographics(path: Path) -> PatientDemographics:
    """Read patient demographics from a DICOM header (no pixel data)."""
    dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    return map_patient_demographics(dataset)


def parse_study_datetime(dataset: Dataset) -> datetime:
    return _parse_study_datetime(
        str(dataset.get("StudyDate", "") or ""),
        str(dataset.get("StudyTime", "") or ""),
    )
