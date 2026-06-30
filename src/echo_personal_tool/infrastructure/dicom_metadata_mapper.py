"""Map pydicom.Dataset to domain metadata dataclasses."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.services.pixel_spacing_resolver import resolve_pixel_spacing


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


def map_instance_metadata(dataset: Dataset, path: Path | None = None) -> InstanceMetadata:
    """Convert a DICOM dataset (header or full) to InstanceMetadata."""
    number_of_frames = int(dataset.get("NumberOfFrames", 1) or 1)
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


def parse_study_datetime(dataset: Dataset) -> datetime:
    return _parse_study_datetime(
        str(dataset.get("StudyDate", "") or ""),
        str(dataset.get("StudyTime", "") or ""),
    )
