"""Unit tests for properties_extractor."""

from __future__ import annotations

from pathlib import Path

import pydicom
from pydicom.dataset import Dataset, FileMetaDataset

from echo_personal_tool.infrastructure.properties_extractor import (
    extract_properties_snapshot,
)


def _minimal_dataset() -> Dataset:
    """Create a minimal DICOM dataset for testing."""
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
    ds.NumberOfFrames = 1
    ds.PixelSpacing = [0.5, 0.5]
    ds.FrameTime = 33.3
    ds.Manufacturer = "SAMSUNG MEDISON"
    ds.ManufacturerModelName = "RS85"
    ds.SoftwareVersions = "1.0.0"
    ds.ImageType = ["ORIGINAL", "PRIMARY"]
    ds.HeartRate = 72
    ds.PatientSize = 1.75
    ds.PatientWeight = 80.0
    ds.TransducerFrequency = 5
    return ds


def _write_dicom(ds: Dataset, path: Path) -> Path:
    """Write a dataset to a DICOM file."""
    ds.save_as(path)
    return path


def test_extract_basic_fields(tmp_path: Path) -> None:
    """Test basic field extraction."""
    path = _write_dicom(_minimal_dataset(), tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert snap.modality == "US"
    assert snap.series_description == "Apical 4C"
    assert snap.manufacturer == "SAMSUNG MEDISON"
    assert snap.manufacturer_model == "RS85"
    assert snap.software_versions == "1.0.0"
    assert snap.image_type == ("ORIGINAL", "PRIMARY")
    assert snap.number_of_frames == 1
    assert snap.media_format == "dicom"


def test_extract_timing_fields(tmp_path: Path) -> None:
    """Test timing field extraction."""
    path = _write_dicom(_minimal_dataset(), tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert snap.frame_time_ms == 33.3
    assert snap.cine_rate_fps is not None
    assert abs(snap.cine_rate_fps - 30.03) < 0.1
    assert snap.heart_rate_bpm == 72.0


def test_extract_spatial_fields(tmp_path: Path) -> None:
    """Test spatial field extraction."""
    path = _write_dicom(_minimal_dataset(), tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert snap.pixel_spacing_mm == (0.5, 0.5)
    assert snap.pixel_spacing_source == "PixelSpacing"
    assert snap.transducer_frequency_mhz == 5.0


def test_extract_patient_fields(tmp_path: Path) -> None:
    """Test patient field extraction and BSA calculation."""
    path = _write_dicom(_minimal_dataset(), tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert snap.patient_height_m == 1.75
    assert snap.patient_weight_kg == 80.0
    assert snap.bsa_m2 is not None
    assert 1.5 < snap.bsa_m2 < 2.5  # Reasonable BSA range


def test_extract_calibration_flags(tmp_path: Path) -> None:
    """Test calibration flag extraction."""
    path = _write_dicom(_minimal_dataset(), tmp_path / "test.dcm")
    snap = extract_properties_snapshot(
        path,
        depth_ok=True,
        mmode_calibrated=False,
        mmode_has_time_scale=True,
        doppler_calibrated=True,
        doppler_has_time_from_dicom=True,
        doppler_has_velocity_from_dicom=False,
        doppler_partial=True,
    )

    assert snap.depth_calibrated is True
    assert snap.mmode_calibrated is False
    assert snap.mmode_has_time_scale is True
    assert snap.doppler_calibrated is True
    assert snap.doppler_has_time_from_dicom is True
    assert snap.doppler_has_velocity_from_dicom is False
    assert snap.doppler_partial is True


def test_extract_mmode_calibration_values(tmp_path: Path) -> None:
    """Test M-mode calibration value extraction."""
    path = _write_dicom(_minimal_dataset(), tmp_path / "test.dcm")
    snap = extract_properties_snapshot(
        path,
        mmode_calibrated=True,
        mmode_has_time_scale=True,
        mmode_vertical_mm_per_pixel=0.15,
        mmode_horizontal_ms_per_pixel=2.5,
        mmode_has_depth_from_dicom=True,
        mmode_has_time_from_dicom=True,
    )

    assert snap.mmode_calibrated is True
    assert snap.mmode_has_time_scale is True
    assert snap.mmode_vertical_mm_per_pixel == 0.15
    assert snap.mmode_horizontal_ms_per_pixel == 2.5
    assert snap.mmode_has_depth_from_dicom is True
    assert snap.mmode_has_time_from_dicom is True


def test_extract_mmode_calibration_defaults(tmp_path: Path) -> None:
    """Test M-mode calibration fields default to None/False."""
    path = _write_dicom(_minimal_dataset(), tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert snap.mmode_vertical_mm_per_pixel is None
    assert snap.mmode_horizontal_ms_per_pixel is None
    assert snap.mmode_has_depth_from_dicom is False
    assert snap.mmode_has_time_from_dicom is False
    """Test ultrasound region extraction."""
    ds = _minimal_dataset()
    del ds.PixelSpacing

    region = Dataset()
    region.RegionSpatialFormat = 1  # B-mode
    region.RegionDataType = 1
    region.RegionLocationMinX0 = 0
    region.RegionLocationMaxX1 = 800
    region.RegionLocationMinY0 = 0
    region.RegionLocationMaxY1 = 400
    region.PhysicalDeltaX = 0.04
    region.PhysicalDeltaY = 0.04
    region.PhysicalUnitsXDirection = 1  # cm
    region.PhysicalUnitsYDirection = 1  # cm
    ds.SequenceOfUltrasoundRegions = [region]

    path = _write_dicom(ds, tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert len(snap.regions) == 1
    r = snap.regions[0]
    assert r.index == 0
    assert r.spatial_format == "B-mode"
    assert r.bounds == (0, 800, 0, 400)
    assert r.delta_x == 0.04
    assert r.delta_y == 0.04
    assert r.units_x == 1
    assert r.units_y == 1


def test_extract_mmode_region(tmp_path: Path) -> None:
    """Test M-mode region extraction."""
    ds = _minimal_dataset()
    del ds.PixelSpacing

    region = Dataset()
    region.RegionSpatialFormat = 2  # M-mode
    region.RegionDataType = 1
    region.RegionLocationMinX0 = 0
    region.RegionLocationMaxX1 = 800
    region.RegionLocationMinY0 = 420
    region.RegionLocationMaxY1 = 600
    region.PhysicalDeltaX = 0.01  # time
    region.PhysicalDeltaY = 0.04  # depth
    region.PhysicalUnitsXDirection = 3  # seconds
    region.PhysicalUnitsYDirection = 1  # cm
    ds.SequenceOfUltrasoundRegions = [region]

    path = _write_dicom(ds, tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert len(snap.regions) == 1
    r = snap.regions[0]
    assert r.spatial_format == "M-mode"
    assert r.bounds == (0, 800, 420, 600)


def test_extract_spectral_doppler_region(tmp_path: Path) -> None:
    """Test spectral Doppler region extraction."""
    ds = _minimal_dataset()
    del ds.PixelSpacing

    region = Dataset()
    region.RegionSpatialFormat = 3  # Spectral
    region.RegionDataType = 3  # PW
    region.RegionLocationMinX0 = 0
    region.RegionLocationMaxX1 = 600
    region.RegionLocationMinY0 = 500
    region.RegionLocationMaxY1 = 700
    region.PhysicalDeltaX = 0.01
    region.PhysicalDeltaY = 10.0
    region.PhysicalUnitsXDirection = 3  # seconds
    region.PhysicalUnitsYDirection = 6  # cm/s
    ds.SequenceOfUltrasoundRegions = [region]

    path = _write_dicom(ds, tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert len(snap.regions) == 1
    r = snap.regions[0]
    assert r.spatial_format == "Spectral"
    assert r.data_type == "PW"


def test_extract_cine_rate_from_cine_rate_tag(tmp_path: Path) -> None:
    """Test cine rate extraction from CineRate tag."""
    ds = _minimal_dataset()
    del ds.FrameTime
    ds.CineRate = 60

    path = _write_dicom(ds, tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert snap.cine_rate_fps == 60.0
    assert snap.frame_time_ms is not None
    assert abs(snap.frame_time_ms - 16.67) < 0.1


def test_extract_frame_time_vector(tmp_path: Path) -> None:
    """Test frame time vector presence detection."""
    ds = _minimal_dataset()
    ds.FrameTimeVector = [33.3, 33.3, 33.3]

    path = _write_dicom(ds, tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert snap.frame_time_vector_present is True


def test_extract_missing_fields(tmp_path: Path) -> None:
    """Test extraction with missing optional fields."""
    ds = Dataset()
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian
    ds.file_meta = meta
    ds.is_little_endian = True
    ds.is_implicit_VR = True
    ds.Modality = "OT"

    path = _write_dicom(ds, tmp_path / "test.dcm")
    snap = extract_properties_snapshot(path)

    assert snap.modality == "OT"
    assert snap.series_description == ""
    assert snap.manufacturer is None
    assert snap.frame_time_ms is None
    assert snap.pixel_spacing_mm is None
    assert snap.regions == ()
    assert snap.bsa_m2 is None
