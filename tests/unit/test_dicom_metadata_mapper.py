"""Unit tests for DicomMetadataMapper."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset, FileMetaDataset

from echo_personal_tool.infrastructure.dicom_metadata_mapper import (
    map_instance_metadata,
    parse_study_datetime,
    read_header_metadata,
)
from echo_personal_tool.infrastructure.local_scanner import LocalDicomDirectoryScanner


def _minimal_dataset() -> Dataset:
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.is_little_endian = True
    ds.is_implicit_VR = True
    ds.SOPInstanceUID = "1.2.3.4.5"
    ds.SeriesInstanceUID = "1.2.3.4.6"
    ds.StudyInstanceUID = "1.2.3.4.7"
    ds.Modality = "US"
    ds.SeriesDescription = "Apical 4C"
    ds.NumberOfFrames = 3
    ds.PixelSpacing = [0.5, 0.5]
    ds.FrameTime = 33.3
    ds.StudyDate = "20240115"
    ds.StudyTime = "103045"
    return ds


def test_map_instance_metadata_fields() -> None:
    meta = map_instance_metadata(_minimal_dataset(), path=Path("/tmp/test.dcm"))
    assert meta.sop_instance_uid == "1.2.3.4.5"
    assert meta.series_uid == "1.2.3.4.6"
    assert meta.modality == "US"
    assert meta.number_of_frames == 3
    assert meta.pixel_spacing == (0.5, 0.5)
    assert meta.pixel_spacing_source == "PixelSpacing"
    assert meta.frame_time_ms == 33.3
    assert meta.series_description == "Apical 4C"
    assert meta.path == Path("/tmp/test.dcm")


def test_map_instance_metadata_from_ultrasound_region() -> None:
    ds = _minimal_dataset()
    del ds.PixelSpacing
    region = Dataset()
    region.RegionSpatialFormat = 1
    region.RegionDataType = 1
    region.PhysicalDeltaX = 0.04
    region.PhysicalDeltaY = 0.04
    ds.SequenceOfUltrasoundRegions = [region]
    meta = map_instance_metadata(ds)
    assert meta.pixel_spacing == (0.4, 0.4)
    assert meta.pixel_spacing_source == "SequenceOfUltrasoundRegions"


def test_parse_study_datetime() -> None:
    dt = parse_study_datetime(_minimal_dataset())
    assert dt == datetime(2024, 1, 15, 10, 30, 45)


def test_read_header_metadata_from_synthetic_file(tmp_path: Path) -> None:
    from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

    path = tmp_path / "synth.dcm"
    write_synthetic_dicom(path)
    meta = read_header_metadata(path)
    assert meta.modality == "US"
    assert meta.number_of_frames == 1
    assert meta.pixel_spacing == (0.3, 0.3)


def test_local_scanner_builds_study_tree(tmp_path: Path) -> None:
    from pydicom.uid import generate_uid

    from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom

    study_uid = generate_uid()
    write_synthetic_dicom(tmp_path / "a.dcm", study_uid=study_uid, series_uid=generate_uid())
    write_synthetic_dicom(
        tmp_path / "nested" / "b.dcm",
        study_uid=study_uid,
        series_uid=generate_uid(),
        series_description="PW",
    )

    studies = LocalDicomDirectoryScanner().scan(tmp_path)
    assert len(studies) == 1
    assert len(studies[0].series) == 2
    assert sum(len(s.instances) for s in studies[0].series) == 2
