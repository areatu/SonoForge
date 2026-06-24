"""DICOM Doppler calibration from ultrasound region tags."""

from __future__ import annotations

from pathlib import Path

import pydicom
from pydicom.dataset import Dataset

from echo_personal_tool.infrastructure.dicom_doppler_calibration import try_parse_from_dataset


def _doppler_region(
    *,
    dtype: int = 2,
    delta_x: float = 0.024,
    delta_y: float = 0.5,
    units_x: int = 3,
    units_y: int = 6,
    width: int = 1000,
    height: int = 400,
) -> Dataset:
    region = Dataset()
    region.RegionSpatialFormat = 1
    region.RegionDataType = dtype
    region.RegionLocationMinX0 = 0
    region.RegionLocationMinY0 = 50
    region.RegionLocationMaxX1 = width
    region.RegionLocationMaxY1 = 50 + height
    region.PhysicalDeltaX = delta_x
    region.PhysicalDeltaY = delta_y
    region.PhysicalUnitsXDirection = units_x
    region.PhysicalUnitsYDirection = units_y
    region.ReferencePixelPhysicalValueX = 0
    region.ReferencePixelPhysicalValueY = 0
    return region


def test_parse_spectral_dtype_2_time_only_when_velocity_units_missing() -> None:
    ds = Dataset()
    ds.SequenceOfUltrasoundRegions = [
        _doppler_region(dtype=2, units_y=3, delta_y=0.024),
    ]
    state = try_parse_from_dataset(ds)
    assert state is not None
    assert state.from_dicom_tags
    assert state.has_time_scale_from_dicom()
    assert state.time_span_ms is not None
    assert abs(state.time_span_ms - 1000.0 * 0.024 * 1000.0) < 0.1
    assert state.velocity_span_cm_s == 200.0


def test_parse_prefers_dtype_2_over_tissue_region() -> None:
    tissue = _doppler_region(dtype=1, units_y=3, delta_y=0.068)
    spectral = _doppler_region(dtype=2, delta_x=0.03, units_y=3, delta_y=0.03)
    ds = Dataset()
    ds.SequenceOfUltrasoundRegions = [tissue, spectral]
    state = try_parse_from_dataset(ds)
    assert state is not None
    assert state.has_time_scale_from_dicom()
    assert abs(state.time_span_ms - 1000.0 * 0.03 * 1000.0) < 0.1


def test_parse_user_download_dicom_when_available() -> None:
    root = Path("/home/areatu/Загрузки/Unknown Study")
    if not root.exists():
        return
    doppler_files = []
    for path in root.rglob("*.dcm"):
        ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        for region in ds.get("SequenceOfUltrasoundRegions") or []:
            if int(region.get("RegionDataType", 0) or 0) == 2:
                doppler_files.append(path)
                break
    if not doppler_files:
        return
    state = try_parse_from_dataset(pydicom.dcmread(doppler_files[0], force=True))
    assert state is not None
    assert state.has_time_scale_from_dicom()
