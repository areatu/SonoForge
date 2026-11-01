"""Map pydicom.Dataset to domain metadata dataclasses."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pydicom
from pydicom.dataset import Dataset

from echo_personal_tool.domain.models import InstanceMetadata, PatientDemographics
from echo_personal_tool.domain.services.pixel_spacing_resolver import resolve_pixel_spacing
from echo_personal_tool.domain.services.ultrasound_region_physics import (
    COLOR_FLOW_DATA_TYPE,
    DOPPLER_DATA_TYPES,
    SPATIAL_M_MODE,
    SPATIAL_SPECTRAL,
)
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


def _clip_mode(dataset: Dataset, series_description: str) -> str:
    """Classify an ultrasound clip for the gallery's 2D/Doppler/M-mode groups.

    Ultrasound region tags are authoritative when present. Some scanners omit
    them or only provide a series label, so the description and ImageType are a
    conservative fallback; unrecognized clips stay in the familiar 2D group.
    """
    regions = dataset.get("SequenceOfUltrasoundRegions") or ()
    spatial_formats: set[int] = set()
    data_types: set[int] = set()
    for region in regions:
        try:
            spatial_formats.add(int(region.get("RegionSpatialFormat", 0) or 0))
            data_types.add(int(region.get("RegionDataType", 0) or 0))
        except (TypeError, ValueError):
            continue

    if SPATIAL_M_MODE in spatial_formats:
        return "m_mode"
    if SPATIAL_SPECTRAL in spatial_formats or data_types.intersection({COLOR_FLOW_DATA_TYPE, *DOPPLER_DATA_TYPES}):
        return "doppler"

    image_type = dataset.get("ImageType") or ()
    image_type_text = image_type if isinstance(image_type, str) else " ".join(map(str, image_type))
    description = f"{series_description} {image_type_text}".casefold()
    if any(marker in description for marker in ("m-mode", "m mode", "mmode", "м-реж", "м режим")):
        return "m_mode"
    if any(marker in description for marker in ("doppler", "допплер", "доплер", "spectral", "спектр", "color flow")):
        return "doppler"
    if re.search(r"(?<![a-z0-9])(pw|cw|tdi)(?![a-z0-9])", description, flags=re.IGNORECASE):
        return "doppler"
    return "2d"


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_float(value: Any) -> float | None:
    number = _safe_float(value)
    return number if number is not None and number > 0 else None


def _file_mtime(path: Path | None) -> datetime | None:
    if path is None:
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def _parse_dicom_datetime(date_value: Any, time_value: Any) -> datetime | None:
    date_text = str(date_value or "").strip()
    if len(date_text) < 8 or not date_text[:8].isdigit():
        return None
    time_digits = "".join(ch for ch in str(time_value or "").split(".")[0] if ch.isdigit())
    time_digits = time_digits.ljust(6, "0")[:6] if time_digits else "000000"
    try:
        return datetime.strptime(date_text[:8] + time_digits, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _instance_created_at(dataset: Dataset, path: Path | None) -> datetime | None:
    """Moment the instance was acquired/created (earliest-first ordering).

    Echo measurements are stored under hashed filenames (Orthanc cache), so the
    filename carries no clinical sequence.  Prefer the DICOM timestamps and only
    fall back to the file mtime.
    """
    acquisition_dt = str(dataset.get("AcquisitionDateTime", "") or "").strip()
    if acquisition_dt:
        parsed = _parse_dicom_datetime(acquisition_dt[:8], acquisition_dt[8:])
        if parsed is not None:
            return parsed
    for date_tag, time_tag in (
        ("AcquisitionDate", "AcquisitionTime"),
        ("ContentDate", "ContentTime"),
        ("InstanceCreationDate", "InstanceCreationTime"),
    ):
        parsed = _parse_dicom_datetime(dataset.get(date_tag), dataset.get(time_tag))
        if parsed is not None:
            return parsed
    return _file_mtime(path)


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
        body_part=str(dataset.get("BodyPartExamined", "") or "").strip(),
        study_description=str(dataset.get("StudyDescription", "") or "").strip(),
        patient_surname=patient_family_name(dataset.get("PatientName")),
        path=path,
        clip_mode=_clip_mode(dataset, series_description),
        media_format="dicom",
        patient_height_m=_safe_float(dataset.get("PatientSize")),
        patient_weight_kg=_safe_float(dataset.get("PatientWeight")),
        heart_rate_bpm=_positive_float(dataset.get("HeartRate")),
        created_at=_instance_created_at(dataset, path),
    )


def read_header_metadata(path: Path) -> InstanceMetadata:
    """Read DICOM metadata without loading pixel data."""
    dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    return map_instance_metadata(dataset, path=path)


def patient_family_name(value: object) -> str:
    """Read only the family component, without guessing from a formatted full name."""
    representations = str(value or "").split("=")
    name = next((part for part in representations if part.strip()), "")
    family = name.split("^", 1)[0]
    return " ".join("".join(char for char in family if char.isprintable()).split())[:128]


def _patient_name_text(value: Any) -> str:
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


def _dicom_date_text(value: Any) -> str:
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
