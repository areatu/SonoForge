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


class TestPatientDemographics:
    """The study report header is filled from these DICOM tags."""

    @staticmethod
    def _dataset(**kwargs):
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, generate_uid

        dataset = Dataset()
        dataset.file_meta = FileMetaDataset()
        dataset.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
        dataset.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        dataset.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        dataset.SOPClassUID = dataset.file_meta.MediaStorageSOPClassUID
        dataset.SOPInstanceUID = dataset.file_meta.MediaStorageSOPInstanceUID
        for key, value in kwargs.items():
            setattr(dataset, key, value)
        return dataset

    def test_maps_every_report_field(self) -> None:
        from echo_personal_tool.infrastructure.dicom_metadata_mapper import (
            map_patient_demographics,
        )

        demographics = map_patient_demographics(
            self._dataset(
                PatientName="Иванов^Иван^Иванович",
                PatientID="12345",
                PatientBirthDate="19800517",
                PatientSex="F",
                StudyDate="20240520",
                InstitutionName="ГБ 1",
                Manufacturer="GE",
                ManufacturerModelName="Vivid E95",
                ReferringPhysicianName="Петров^Пётр",
                PatientSize=1.72,
                PatientWeight=68.0,
            )
        )
        # DICOM keeps family name first; a report reads given name first.
        assert demographics.name == "Иван Иванович Иванов"
        assert demographics.patient_id == "12345"
        assert demographics.birth_date == "17.05.1980"
        assert demographics.sex == "F"
        assert demographics.study_date == "20.05.2024"
        assert demographics.age == "44"
        assert demographics.institution == "ГБ 1"
        assert demographics.equipment == "GE Vivid E95"
        assert demographics.referring_physician == "Пётр Петров"
        assert demographics.height_m == 1.72
        assert demographics.weight_kg == 68.0
        assert demographics.is_empty is False

    def test_missing_header_is_empty_not_broken(self) -> None:
        from echo_personal_tool.infrastructure.dicom_metadata_mapper import (
            map_patient_demographics,
        )

        demographics = map_patient_demographics(self._dataset())
        assert demographics.is_empty is True
        assert demographics.age == ""
        assert demographics.name == ""

    def test_unparsable_birth_date_gives_no_age(self) -> None:
        from echo_personal_tool.infrastructure.dicom_metadata_mapper import (
            map_patient_demographics,
        )

        demographics = map_patient_demographics(
            self._dataset(PatientBirthDate="unknown", StudyDate="20240520")
        )
        assert demographics.age == ""
        assert demographics.birth_date == "unknown"

    def test_birthday_not_yet_reached_this_year(self) -> None:
        from echo_personal_tool.infrastructure.dicom_metadata_mapper import (
            map_patient_demographics,
        )

        demographics = map_patient_demographics(
            self._dataset(PatientBirthDate="19801231", StudyDate="20240101")
        )
        assert demographics.age == "43"

    def test_reads_from_a_file(self, tmp_path: Path) -> None:
        from echo_personal_tool.infrastructure.dicom_metadata_mapper import (
            read_patient_demographics,
        )

        path = tmp_path / "patient.dcm"
        dataset = self._dataset(PatientName="Doe^John", PatientID="777", PatientSex="M")
        dataset.save_as(str(path), enforce_file_format=True)
        demographics = read_patient_demographics(path)
        assert demographics.name == "John Doe"
        assert demographics.patient_id == "777"
        assert demographics.sex == "M"
