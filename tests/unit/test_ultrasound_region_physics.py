"""Tests for DICOM ultrasound region physics helpers."""

from __future__ import annotations

from pydicom.dataset import Dataset

from echo_personal_tool.domain.services.ultrasound_region_physics import (
    DOPPLER_DATA_TYPES,
    PHYSICAL_UNIT_CM_PER_SEC,
    PHYSICAL_UNIT_SEC,
    horizontal_ms_per_pixel,
    is_maybe_doppler_from_units,
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


def test_doppler_data_types_exclude_color_flow() -> None:
    """Color Flow (2) should NOT be in spectral Doppler data types."""
    assert 2 not in DOPPLER_DATA_TYPES
    assert 3 in DOPPLER_DATA_TYPES  # PW
    assert 4 in DOPPLER_DATA_TYPES  # CW


def test_color_flow_region_is_not_spectral_doppler() -> None:
    """Color Flow (RegionDataType=2) should not be treated as spectral Doppler."""
    region = _region(RegionSpatialFormat=1, RegionDataType=2)
    assert not is_spectral_doppler_region(region)


def test_pw_doppler_region_is_spectral() -> None:
    region = _region(RegionSpatialFormat=3, RegionDataType=3)
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


def test_horizontal_ms_per_pixel_rejects_bmode_sf1_with_sec_units() -> None:
    """SF=1 (B-mode) rejected outright — callers use is_maybe_doppler_from_units for Samsung mis-tag."""
    assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC, spatial_format=1) is None


def test_horizontal_ms_per_pixel_rejects_bmode_sf1_with_cm_units() -> None:
    """B-mode region (SF=1) with CM units → None (spatial, not temporal)."""
    assert horizontal_ms_per_pixel(0.0375, 1, spatial_format=1) is None


def test_horizontal_ms_per_pixel_accepts_mmode_sf2() -> None:
    """M-mode region (SF=2) with SEC units → valid value."""
    assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC, spatial_format=2) == 24.0


def test_horizontal_ms_per_pixel_accepts_spectral_sf3() -> None:
    """Spectral region (SF=3) with SEC units → valid value."""
    assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC, spatial_format=3) == 24.0


def test_horizontal_ms_per_pixel_no_spatial_format() -> None:
    """No spatial_format provided → no guard, returns value."""
    assert horizontal_ms_per_pixel(0.024, PHYSICAL_UNIT_SEC) == 24.0


def test_samsung_bmode_sf1_with_sec_units_is_not_maybe_doppler() -> None:
    """Samsung B-mode: SF=1, SEC units, DeltaX==DeltaY → spatial resolution, NOT Doppler."""
    region = _region(
        RegionSpatialFormat=1,
        RegionDataType=1,
        PhysicalUnitsXDirection=PHYSICAL_UNIT_SEC,
        PhysicalDeltaX=0.0375,
        PhysicalUnitsYDirection=3,
        PhysicalDeltaY=0.0375,
    )
    assert is_maybe_doppler_from_units(region) is False


def test_samsung_sf1_with_hz_no_delta_y_is_not_maybe_doppler() -> None:
    """SF=1, Hz units, no DeltaY → cannot determine, reject."""
    region = _region(
        RegionSpatialFormat=1,
        RegionDataType=1,
        PhysicalUnitsXDirection=4,  # Hz
        PhysicalDeltaX=0.5,
    )
    assert is_maybe_doppler_from_units(region) is False


def test_sf1_with_sec_and_different_deltas_is_maybe_doppler() -> None:
    """SF=1, SEC units, DeltaX != DeltaY → genuine temporal Doppler."""
    region = _region(
        RegionSpatialFormat=1,
        RegionDataType=1,
        PhysicalUnitsXDirection=PHYSICAL_UNIT_SEC,
        PhysicalDeltaX=0.0375,
        PhysicalUnitsYDirection=3,
        PhysicalDeltaY=0.01,
    )
    assert is_maybe_doppler_from_units(region) is True


def test_sf1_with_velocity_units_is_maybe_doppler() -> None:
    """SF=1 with velocity units on Y → genuine tissue/spectral Doppler."""
    region = _region(
        RegionSpatialFormat=1,
        RegionDataType=1,
        PhysicalUnitsXDirection=1,  # cm
        PhysicalUnitsYDirection=6,  # cm/s
        PhysicalDeltaX=0.0375,
        PhysicalDeltaY=0.5,
    )
    assert is_maybe_doppler_from_units(region) is True


def test_bmode_sf1_with_cm_units_is_not_maybe_doppler() -> None:
    """Genuine B-mode region (SF=1, CM units) should not be detected as Doppler."""
    region = _region(
        RegionSpatialFormat=1,
        RegionDataType=1,
        PhysicalUnitsXDirection=1,  # cm
        PhysicalUnitsYDirection=1,  # cm
        PhysicalDeltaX=0.0375,
        PhysicalDeltaY=0.0375,
    )
    assert is_maybe_doppler_from_units(region) is False


def test_velocity_span_with_negative_delta_y() -> None:
    """Negative delta_y (inverted spectrum) → abs() full scale."""
    assert velocity_span_cm_s_from_region(319.0, -0.5069, 7) == 319.0 * 0.5069


def test_velocity_span_rejects_zero_delta_y() -> None:
    """Zero delta_y → None (no scale)."""
    assert velocity_span_cm_s_from_region(319.0, 0.0, 7) is None


def test_velocity_span_accepts_vendor_unit_7() -> None:
    """Unit code 7 is a vendor mis-tag for cm/s — accept."""
    assert velocity_span_cm_s_from_region(100.0, 0.5, 7) == 50.0
