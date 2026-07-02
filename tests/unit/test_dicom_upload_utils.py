"""Tests for DICOM byte collection helper."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from echo_personal_tool.application.dicom_upload_utils import collect_dicom_bytes
from echo_personal_tool.domain.models import InstanceMetadata, SeriesMetadata, StudyMetadata


def _study_with_file(path: Path, *, media_format: str = "dicom") -> StudyMetadata:
    inst = InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2.3.4",
        modality="US",
        number_of_frames=1,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="Test",
        path=path,
        media_format=media_format,
    )
    series = SeriesMetadata(
        series_uid="1.2.3.4",
        study_uid="1.2.3.5",
        modality="US",
        description="S",
        instances=(inst,),
    )
    return StudyMetadata(
        study_uid="1.2.3.5",
        study_datetime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        series=(series,),
    )


def test_collect_dicom_bytes_reads_files(tmp_path: Path) -> None:
    dcm = tmp_path / "a.dcm"
    dcm.write_bytes(b"DICM-test")
    payloads = collect_dicom_bytes([_study_with_file(dcm)])
    assert payloads == [b"DICM-test"]


def test_collect_dicom_bytes_skips_mp4(tmp_path: Path) -> None:
    mp4 = tmp_path / "a.mp4"
    mp4.write_bytes(b"mp4")
    payloads = collect_dicom_bytes([_study_with_file(mp4, media_format="mp4")])
    assert payloads == []


def test_collect_dicom_bytes_deduplicates(tmp_path: Path) -> None:
    dcm = tmp_path / "a.dcm"
    dcm.write_bytes(b"x")
    inst = _study_with_file(dcm).series[0].instances[0]
    series = SeriesMetadata(
        series_uid="1.2.3.4",
        study_uid="1.2.3.5",
        modality="US",
        description="S",
        instances=(inst, inst),
    )
    study = StudyMetadata(
        study_uid="1.2.3.5",
        study_datetime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        series=(series,),
    )
    assert len(collect_dicom_bytes([study])) == 1
