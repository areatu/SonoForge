"""Tests for DICOM ultrasound region physics helpers."""

from __future__ import annotations

from pydicom.dataset import Dataset

from echo_personal_tool.domain.services.ultrasound_region_physics import (
    DOPPLER_DATA_TYPES,
    PHYSICAL_UNIT_CM_PER_SEC,
    PHYSICAL_UNIT_SEC,
    horizontal_ms_per_pixel,
    is_spectral_doppler_region,
    time_span_ms_from_region,
    velocity_span_cm_s_from_region,
    vertical_mm_per_pixel,
)


def _region(**kwargs: object) -> Dataset:
    region = Dataset()
    for key, value in kwargs.items():
        setattr(region, key, value)
    return region


def test_doppler_data_types_include_spectral_code_2() -> None:
    assert 2 in DOPPLER_DATA_TYPES


def test_spectral_region_data_type_2_is_doppler() -> None:
    region = _region(RegionSpatialFormat=1, RegionDataType=2)
    assert is_spectral_doppler_region(region)


def test_horizontal_ms_per_pixel_seconds_unit_code_3() -> None:
    assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC) == 24.0


def test_time_span_from_vendor_like_region() -> None:
  span = time_span_ms_from_region(1276.0, 0.024, PHYSICAL_UNIT_SEC)
  assert span is not None
  assert abs(span - 1276.0 * 24.0) < 0.1


def test_velocity_span_requires_cm_per_sec_units() -> None:
    assert velocity_span_cm_s_from_region(400.0, 0.5, PHYSICAL_UNIT_SEC) is None
    assert velocity_span_cm_s_from_region(400.0, 0.5, PHYSICAL_UNIT_CM_PER_SEC) == 200.0


def test_mmode_vendor_hz_tag_reads_as_time_when_value_is_small() -> None:
    assert horizontal_ms_per_pixel(1.0 / 240.0, 4) is not None


def test_mmode_vendor_sec_tag_reads_as_depth_mm() -> None:
    from pytest import approx

    assert vertical_mm_per_pixel(0.035, PHYSICAL_UNIT_SEC) == approx(0.35)
