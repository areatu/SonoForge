"""Interpret DICOM SequenceOfUltrasoundRegions physical deltas and units."""

from __future__ import annotations

from pydicom.dataset import Dataset

# DICOM PS3.3 C.8.5.5 Physical Units
PHYSICAL_UNIT_CM = 1
PHYSICAL_UNIT_MM = 2
PHYSICAL_UNIT_SEC = 3
PHYSICAL_UNIT_HZ = 4
PHYSICAL_UNIT_DB = 5
PHYSICAL_UNIT_CM_PER_SEC = 6

# RegionSpatialFormat
SPATIAL_2D = 1
SPATIAL_M_MODE = 2
SPATIAL_SPECTRAL = 3

# RegionDataType — spectral / tissue Doppler
# 2 = Color Flow (NOT spectral), 3 = PW, 4 = CW, 0x10 = TDI, 0x11 = TDI_PW
DOPPLER_DATA_TYPES = frozenset({3, 4, 0x10, 0x11})

_SPATIAL_UNIT_CODES = frozenset(
    {
        PHYSICAL_UNIT_CM,
        PHYSICAL_UNIT_MM,
    }
)


def region_physical_deltas(region: Dataset) -> tuple[float | None, float | None, int | None, int | None]:
    """Return (delta_x, delta_y, units_x, units_y) from one ultrasound region item."""
    dx = region.get("PhysicalDeltaX")
    dy = region.get("PhysicalDeltaY")
    ux = region.get("PhysicalUnitsXDirection")
    uy = region.get("PhysicalUnitsYDirection")
    delta_x = abs(float(dx)) if dx is not None else None
    delta_y = abs(float(dy)) if dy is not None else None
    units_x = int(ux) if ux is not None else None
    units_y = int(uy) if uy is not None else None
    return delta_x, delta_y, units_x, units_y


def horizontal_ms_per_pixel(delta_x: float, units_x: int) -> float | None:
    """M-mode / spectral sweep: milliseconds per pixel on the time axis."""
    if delta_x <= 0.0:
        return None
    if units_x == PHYSICAL_UNIT_SEC:
        return delta_x * 1000.0
    # Vendor quirk: time increment mis-tagged as Hz while value is seconds/pixel.
    if units_x == PHYSICAL_UNIT_HZ and delta_x < 1.0:
        return delta_x * 1000.0
    return None


def vertical_mm_per_pixel(delta_y: float, units_y: int) -> float | None:
    """Depth axis: millimeters per pixel."""
    if delta_y <= 0.0:
        return None
    if units_y == PHYSICAL_UNIT_CM:
        return delta_y * 10.0
    if units_y == PHYSICAL_UNIT_MM:
        return delta_y
    # Vendor quirk: depth increment mis-tagged as seconds while value is cm/pixel.
    if units_y == PHYSICAL_UNIT_SEC and delta_y < 1.0:
        return delta_y * 10.0
    return None


def time_span_ms_from_region(width_px: float, delta_x: float, units_x: int) -> float | None:
    """Full horizontal span of a spectrogram/M-mode strip in milliseconds."""
    ms_per_px = horizontal_ms_per_pixel(delta_x, units_x)
    if ms_per_px is None or width_px <= 0.0:
        return None
    return width_px * ms_per_px


def velocity_span_cm_s_from_region(height_px: float, delta_y: float, units_y: int) -> float | None:
    """Full vertical velocity span (cm/s) for spectral Doppler."""
    # units_y=6 is standard cm/s; units_y=7 is a known vendor mis-tag (also cm/s)
    if units_y not in (PHYSICAL_UNIT_CM_PER_SEC, 7) or delta_y <= 0.0 or height_px <= 0.0:
        return None
    return height_px * delta_y


def is_spatial_calibration_region(region: Dataset) -> bool:
    """True when region deltas describe B-mode distance (cm/mm), not time/velocity."""
    if is_spectral_doppler_region(region):
        return False
    spatial = int(region.get("RegionSpatialFormat", 0) or 0)
    data_type = int(region.get("RegionDataType", 0) or 0)
    if spatial == SPATIAL_2D and data_type == 1:
        return True
    _, _, units_x, units_y = region_physical_deltas(region)
    if units_x is not None and units_x not in _SPATIAL_UNIT_CODES:
        return False
    if units_y is not None and units_y not in _SPATIAL_UNIT_CODES:
        return False
    return True


def is_spectral_doppler_region(region: Dataset) -> bool:
    spatial = int(region.get("RegionSpatialFormat", 0) or 0)
    data_type = int(region.get("RegionDataType", 0) or 0)
    if spatial == SPATIAL_SPECTRAL:
        return True
    return data_type in DOPPLER_DATA_TYPES


def is_mmode_region(region: Dataset) -> bool:
    return int(region.get("RegionSpatialFormat", 0) or 0) == SPATIAL_M_MODE


def spectral_doppler_region_priority(region: Dataset) -> int:
    """Higher = preferred when multiple regions match Doppler."""
    if not is_spectral_doppler_region(region):
        return -1
    data_type = int(region.get("RegionDataType", 0) or 0)
    if data_type == 3:
        return 4
    if data_type == 4:
        return 3
    if data_type in {0x10, 16}:
        return 2
    if data_type in {0x11, 17}:
        return 1
    if int(region.get("RegionSpatialFormat", 0) or 0) == SPATIAL_SPECTRAL:
        return 3
    return 1
