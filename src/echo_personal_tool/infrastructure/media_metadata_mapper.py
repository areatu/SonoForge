"""Map non-DICOM media files to domain InstanceMetadata."""

from __future__ import annotations

import hashlib
from pathlib import Path

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.infrastructure.media_formats import MediaFormat
from echo_personal_tool.infrastructure.video_reader import VideoReader

MP4_SERIES_DESCRIPTION = "Cine (MP4)"
JPEG_SERIES_DESCRIPTION = "Still (JPEG)"


def synthetic_instance_uid(study_folder: Path, filename: str) -> str:
    """Stable UID for MP4/JPEG instances within a study folder."""
    key = f"{study_folder.resolve()}:{filename}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return f"2.25.{digest}"


def synthetic_study_uid(study_folder: Path) -> str:
    """Stable study UID when no DICOM metadata is available."""
    digest = hashlib.sha256(str(study_folder.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"local:{digest}"


def synthetic_series_uid(study_folder: Path, kind: str) -> str:
    digest = hashlib.sha256(f"{study_folder.resolve()}:{kind}".encode()).hexdigest()[:32]
    return f"2.25.{digest}"


def map_mp4_instance(
    path: Path,
    *,
    study_folder: Path,
    study_uid: str,
    series_uid: str,
) -> InstanceMetadata:
    with VideoReader() as reader:
        reader.open(path)
        frame_count = reader.frame_count
        fps = reader.fps
    frame_time_ms = 1000.0 / fps if fps > 0 else None
    return InstanceMetadata(
        sop_instance_uid=synthetic_instance_uid(study_folder, path.name),
        series_uid=series_uid,
        modality="US",
        number_of_frames=frame_count,
        pixel_spacing=None,
        frame_time_ms=frame_time_ms,
        series_description=MP4_SERIES_DESCRIPTION,
        path=path,
        media_format="mp4",
    )


def map_image_instance(
    path: Path,
    *,
    study_folder: Path,
    study_uid: str,
    series_uid: str,
    media_format: MediaFormat,
) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=synthetic_instance_uid(study_folder, path.name),
        series_uid=series_uid,
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=None,
        series_description=JPEG_SERIES_DESCRIPTION,
        path=path,
        media_format=media_format,
    )
