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


def test_iter_study_roots_walks_deep_nested_folder_tree(tmp_path: Path) -> None:
    first_series = tmp_path / "patient" / "date" / "study" / "series-1"
    second_series = tmp_path / "patient" / "date" / "study" / "series-2"
    write_synthetic_dicom(first_series / "a.dcm")
    write_synthetic_dicom(second_series / "b.dcm")

    roots = iter_study_roots(tmp_path)

    assert roots == [first_series, second_series]


def test_scan_mixed_dicom_mp4_jpeg_folder(tmp_path: Path) -> None:
    study_uid = generate_uid()
    write_synthetic_dicom(tmp_path / "apical.dcm", study_uid=study_uid, series_uid=generate_uid())
    write_synthetic_mp4(tmp_path / "cine.mp4", frame_count=4)
    write_synthetic_jpeg(tmp_path / "key.jpg")

    from echo_personal_tool.infrastructure.media_metadata_mapper import synthetic_study_uid

    studies = LocalMediaDirectoryScanner().scan(tmp_path)

    assert len(studies) == 2  # untagged media must not inherit the first DICOM patient's UID
    assert {study.study_uid for study in studies} == {study_uid, synthetic_study_uid(tmp_path)}
    formats = {instance.media_format for study in studies for series in study.series for instance in series.instances}
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


def test_scan_merges_series_from_deep_nested_folders_by_study_uid(tmp_path: Path) -> None:
    uid_a, uid_b = generate_uid(), generate_uid()
    series_a, series_a_two, series_b = generate_uid(), generate_uid(), generate_uid()
    duplicate_sop = generate_uid()
    root = tmp_path / "patient" / "2026"
    a_series_one = root / "study-a" / "series-1"
    a_series_duplicate = root / "study-a" / "series-duplicate"
    a_series_two = root / "study-a" / "series-2"
    b_series = root / "study-b" / "series-1"
    write_synthetic_dicom(
        a_series_one / "a1.dcm",
        study_uid=uid_a,
        series_uid=series_a,
        sop_uid=duplicate_sop,
    )
    write_synthetic_dicom(
        a_series_duplicate / "a1-copy.dcm",
        study_uid=uid_a,
        series_uid=series_a,
        sop_uid=duplicate_sop,
    )
    write_synthetic_dicom(a_series_duplicate / "a2.dcm", study_uid=uid_a, series_uid=series_a)
    write_synthetic_dicom(a_series_two / "a3.dcm", study_uid=uid_a, series_uid=series_a_two)
    write_synthetic_dicom(b_series / "b1.dcm", study_uid=uid_b, series_uid=series_b)

    studies = LocalMediaDirectoryScanner().scan(tmp_path)

    assert {study.study_uid for study in studies} == {uid_a, uid_b}
    by_uid = {study.study_uid: study for study in studies}
    assert len(by_uid[uid_a].series) == 2
    assert sum(len(series.instances) for series in by_uid[uid_a].series) == 3
    by_series = {series.series_uid: series for series in by_uid[uid_a].series}
    assert len(by_series[series_a].instances) == 2
    assert len(by_uid[uid_b].series) == 1


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


def test_each_dicom_is_parsed_once_per_scan(tmp_path: Path, monkeypatch) -> None:
    """Э3/П.4: one header parse per file.

    The scanner used to read every DICOM two or three times (instance, study
    UID, study datetime), which is what made opening a folder slow and made
    cloud-backed files appear to hang.
    """
    import pydicom

    from echo_personal_tool.infrastructure import local_scanner as scanner_module

    study_uid = generate_uid()
    for name in ("a.dcm", "b.dcm", "c.dcm"):
        write_synthetic_dicom(tmp_path / name, study_uid=study_uid, series_uid=generate_uid())

    calls: list[str] = []
    real_dcmread = pydicom.dcmread

    def counting_dcmread(path, *args, **kwargs):
        calls.append(str(path))
        return real_dcmread(path, *args, **kwargs)

    monkeypatch.setattr(scanner_module.pydicom, "dcmread", counting_dcmread)

    scanner = LocalMediaDirectoryScanner()
    studies = scanner.scan(tmp_path)

    assert len(studies) == 1
    instances = [instance for series in studies[0].series for instance in series.instances]
    assert len(instances) == 3
    assert len(calls) == 3  # one read per file, not two or three

    # Repeated scans must not serve a stale header cache.
    scanner.scan(tmp_path)
    assert len(calls) == 6


def test_study_split_reuses_the_cached_header(tmp_path: Path, monkeypatch) -> None:
    """Two studies inside one folder are still split, with a single read each."""
    import pydicom

    from echo_personal_tool.infrastructure import local_scanner as scanner_module

    uid_a, uid_b = generate_uid(), generate_uid()
    write_synthetic_dicom(tmp_path / "a1.dcm", study_uid=uid_a, series_uid=generate_uid())
    write_synthetic_dicom(tmp_path / "a2.dcm", study_uid=uid_a, series_uid=generate_uid())
    write_synthetic_dicom(tmp_path / "b1.dcm", study_uid=uid_b, series_uid=generate_uid())

    reads: list[str] = []
    real_dcmread = pydicom.dcmread

    def counting_dcmread(path, *args, **kwargs):
        reads.append(str(path))
        return real_dcmread(path, *args, **kwargs)

    monkeypatch.setattr(scanner_module.pydicom, "dcmread", counting_dcmread)
    studies = LocalMediaDirectoryScanner().scan(tmp_path)

    assert {study.study_uid for study in studies} == {uid_a, uid_b}
    assert len(reads) == 3


def test_rejected_file_is_read_and_logged_once(tmp_path: Path, monkeypatch) -> None:
    """A broken DICOM is reported once, not once per reading code path."""
    from echo_personal_tool.infrastructure import local_scanner as scanner_module

    bad = tmp_path / "broken.dcm"
    bad.write_bytes(b"not a dicom file")
    write_synthetic_dicom(tmp_path / "good.dcm", study_uid=generate_uid(), series_uid=generate_uid())

    errors: list[tuple] = []
    scanner = LocalMediaDirectoryScanner()
    monkeypatch.setattr(scanner, "_log_scan_error", lambda path, exc: errors.append((path, exc)))

    reads: list[str] = []
    import pydicom

    real_dcmread = pydicom.dcmread

    def counting_dcmread(path, *args, **kwargs):
        reads.append(str(path))
        return real_dcmread(path, *args, **kwargs)

    monkeypatch.setattr(scanner_module.pydicom, "dcmread", counting_dcmread)
    scanner.scan(tmp_path)

    assert [path.name for path, _exc in errors].count("broken.dcm") == 1
    # The header scan rejects it before pydicom parses anything: the failure is
    # recorded once instead of once per reading code path.
    assert reads.count(str(bad)) == 0
    assert reads.count(str(tmp_path / "good.dcm")) == 1
