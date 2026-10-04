"""Source/identity integration tests using only generated DICOM and images."""

from dataclasses import replace

import pytest

from echo_personal_tool.infrastructure.local_scanner import LocalMediaDirectoryScanner
from echo_personal_tool.infrastructure.measurement_codec import MeasurementStorageError
from echo_personal_tool.infrastructure.measurement_sources import describe_study
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom
from tests.fixtures.generate_synthetic_media import write_synthetic_png


def test_mixed_patients_even_with_same_series_are_not_grouped(tmp_path):
    write_synthetic_dicom(tmp_path / "a.dcm", study_uid="1.2.3", series_uid="1.2.99")
    write_synthetic_dicom(tmp_path / "b.dcm", study_uid="1.2.4", series_uid="1.2.99")
    studies = LocalMediaDirectoryScanner().scan(tmp_path)
    assert {s.study_uid for s in studies} == {"1.2.3", "1.2.4"}
    for study in studies:
        assert len(describe_study(study)) == 1


def test_dicom_relocation_stable_and_wrong_study_rejected(tmp_path):
    import shutil

    (tmp_path / "one").mkdir()
    write_synthetic_dicom(tmp_path / "one" / "clip.dcm", study_uid="1.2.3", series_uid="1.2.99")
    first = LocalMediaDirectoryScanner().scan(tmp_path / "one")[0]
    shutil.copytree(tmp_path / "one", tmp_path / "two")
    second = LocalMediaDirectoryScanner().scan(tmp_path / "two")[0]
    assert describe_study(first) == describe_study(second)
    with pytest.raises(MeasurementStorageError, match="identity"):
        describe_study(replace(first, study_uid="1.2.4"))


def test_same_uid_changed_geometry_fingerprint_differs(tmp_path):
    import pydicom

    path = tmp_path / "clip.dcm"
    write_synthetic_dicom(path, study_uid="1.2.3", series_uid="1.2.99")
    study = LocalMediaDirectoryScanner().scan(tmp_path)[0]
    before = describe_study(study)
    ds = pydicom.dcmread(path)
    ds.PixelSpacing = [2.0, 2.0]
    ds.save_as(path)
    assert describe_study(study) != before


def test_non_dicom_replacement_under_same_name_detected(tmp_path):
    path = tmp_path / "clip.png"
    write_synthetic_png(path)
    study = LocalMediaDirectoryScanner().scan(tmp_path)[0]
    before = describe_study(study)
    path.write_bytes(path.read_bytes() + b"changed")
    assert describe_study(study) != before
