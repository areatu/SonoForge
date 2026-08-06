"""Unit tests for LocalMediaDirectoryScanner."""

from __future__ import annotations

from pathlib import Path

from pydicom.uid import generate_uid

from echo_personal_tool.infrastructure.local_scanner import (
    LocalMediaDirectoryScanner,
    iter_study_roots,
)
from echo_personal_tool.infrastructure.media_metadata_mapper import (
    JPEG_SERIES_DESCRIPTION,
    MP4_SERIES_DESCRIPTION,
)
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom
from tests.fixtures.generate_synthetic_media import (
    write_synthetic_jpeg,
    write_synthetic_mp4,
    write_synthetic_png,
)


def test_iter_study_roots_single_study_folder(tmp_path: Path) -> None:
    write_synthetic_dicom(tmp_path / "a.dcm")
    assert iter_study_roots(tmp_path) == [tmp_path]


def test_iter_study_roots_container_with_child_studies(tmp_path: Path) -> None:
    study_a = tmp_path / "2024-01-15_study_a"
    study_b = tmp_path / "2024-01-16_study_b"
    write_synthetic_dicom(study_a / "a.dcm")
    write_synthetic_dicom(study_b / "b.dcm")

    roots = iter_study_roots(tmp_path)
    assert roots == [study_a, study_b]


def test_scan_mixed_dicom_mp4_jpeg_folder(tmp_path: Path) -> None:
    study_uid = generate_uid()
    write_synthetic_dicom(tmp_path / "apical.dcm", study_uid=study_uid, series_uid=generate_uid())
    write_synthetic_mp4(tmp_path / "cine.mp4", frame_count=4)
    write_synthetic_jpeg(tmp_path / "key.jpg")

    studies = LocalMediaDirectoryScanner().scan(tmp_path)

    assert len(studies) == 1
    assert len(studies[0].series) == 3
    formats = {instance.media_format for series in studies[0].series for instance in series.instances}
    assert formats == {"dicom", "mp4", "jpeg"}


def test_scan_mp4_only_folder(tmp_path: Path) -> None:
    write_synthetic_mp4(tmp_path / "clip.mp4", frame_count=3)

    studies = LocalMediaDirectoryScanner().scan(tmp_path)

    assert len(studies) == 1
    assert studies[0].study_uid.startswith("local:")
    assert len(studies[0].series) == 1
    assert studies[0].series[0].description == MP4_SERIES_DESCRIPTION
    assert studies[0].series[0].instances[0].number_of_frames == 3


def test_scan_jpeg_and_png_share_still_series(tmp_path: Path) -> None:
    write_synthetic_jpeg(tmp_path / "a.jpg")
    write_synthetic_png(tmp_path / "b.png")

    studies = LocalMediaDirectoryScanner().scan(tmp_path)

    assert len(studies) == 1
    assert len(studies[0].series) == 1
    assert studies[0].series[0].description == JPEG_SERIES_DESCRIPTION
    assert {i.media_format for i in studies[0].series[0].instances} == {"jpeg", "png"}


def test_scan_multi_study_container(tmp_path: Path) -> None:
    study_a = tmp_path / "study_a"
    study_b = tmp_path / "study_b"
    write_synthetic_dicom(study_a / "a.dcm", study_uid=generate_uid())
    write_synthetic_mp4(study_b / "b.mp4")

    studies = LocalMediaDirectoryScanner().scan(tmp_path)

    assert len(studies) == 2


def test_scan_dicom_instances_sorted_by_filename(tmp_path: Path) -> None:
    study_uid = generate_uid()
    series_uid = generate_uid()
    write_synthetic_dicom(
        tmp_path / "003.dcm",
        study_uid=study_uid,
        series_uid=series_uid,
    )
    write_synthetic_dicom(
        tmp_path / "001.dcm",
        study_uid=study_uid,
        series_uid=series_uid,
    )
    write_synthetic_dicom(
        tmp_path / "002.dcm",
        study_uid=study_uid,
        series_uid=series_uid,
    )

    studies = LocalMediaDirectoryScanner().scan(tmp_path)
    instances = studies[0].series[0].instances
    names = [inst.path.name for inst in instances if inst.path is not None]
    assert names == ["001.dcm", "002.dcm", "003.dcm"]


def test_local_scanner_builds_dicom_study_tree(tmp_path: Path) -> None:
    study_uid = generate_uid()
    write_synthetic_dicom(tmp_path / "a.dcm", study_uid=study_uid, series_uid=generate_uid())
    write_synthetic_dicom(
        tmp_path / "nested" / "b.dcm",
        study_uid=study_uid,
        series_uid=generate_uid(),
        series_description="PW",
    )

    studies = LocalMediaDirectoryScanner().scan(tmp_path)
    assert len(studies) == 1
    assert len(studies[0].series) == 2
    assert sum(len(s.instances) for s in studies[0].series) == 2
