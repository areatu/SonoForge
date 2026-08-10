"""Interpret DICOM SequenceOfUltrasoundRegions physical deltas and units."""

from __future__ import annotations

import logging

from pydicom.dataset import Dataset

logger = logging.getLogger(__name__)

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


def horizontal_ms_per_pixel(
    delta_x: float,
    units_x: int,
    spatial_format: int | None = None,
) -> float | None:
    """M-mode / spectral sweep: milliseconds per pixel on the time axis."""
    if delta_x <= 0.0:
        return None
    # SF=1 (2D/B-mode) regions are never time sweeps — reject them outright.
    # Callers decide whether a mis-tagged SF=1 region is really Doppler; those
    # that are (Samsung tissue/spectral) compute via the region-level filter.
    if spatial_format is not None and spatial_format == SPATIAL_2D:
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
    if ms_per_px is None:
        logger.debug("Cannot compute time span: delta_x=%s, units_x=%s", delta_x, units_x)
        return None
    if width_px <= 0.0:
        return None
    return width_px * ms_per_px


def velocity_span_cm_s_from_region(height_px: float, delta_y: float, units_y: int) -> float | None:
    """Full vertical velocity span (cm/s) for spectral Doppler.

    Negative delta_y is valid — it means the spectrum is inverted
    (positive velocity points up). Use abs() for the full scale.
    """
    # units_y=6 is standard cm/s; units_y=7 is a known vendor mis-tag (also cm/s)
    if units_y not in (PHYSICAL_UNIT_CM_PER_SEC, 7):
        logger.debug("Unsupported velocity units: %s", units_y)
        return None
    if delta_y == 0.0 or height_px <= 0.0:
        return None
    return height_px * abs(delta_y)


def is_spatial_calibration_region(region: Dataset) -> bool:
    """True when region deltas describe B-mode distance (cm/mm), not time/velocity."""
    if is_spectral_doppler_region(region):
        return False
    spatial = int(region.get("RegionSpatialFormat", 0) or 0)
    data_type = int(region.get("RegionDataType", 0) or 0)
    if spatial == SPATIAL_2D and data_type == 1:
        return True
    _, _, units_x, units_y = region_physical_deltas(region)
    if units_x is None or units_y is None:
        return False
    if units_x not in _SPATIAL_UNIT_CODES:
        return False
    if units_y not in _SPATIAL_UNIT_CODES:
        return False
    return True


def is_spectral_doppler_region(region: Dataset) -> bool:
    spatial = int(region.get("RegionSpatialFormat", 0) or 0)
    data_type = int(region.get("RegionDataType", 0) or 0)
    if spatial == SPATIAL_SPECTRAL:
        return True
    if data_type in DOPPLER_DATA_TYPES:
        return True
    return False


def is_maybe_doppler_from_units(region: Dataset) -> bool:
    """Samsung mis-tags tissue/spectral Doppler as SF=1 (2D). Trust time/velocity units.

    Excludes SF=2 (M-mode) — those are correctly tagged and handled separately.
    Rejects SF=1 regions where DeltaX ≈ DeltaY (spatial B-mode resolution mis-tagged as SEC).
    """
    spatial = int(region.get("RegionSpatialFormat", 0) or 0)
    data_type = int(region.get("RegionDataType", 0) or 0)
    # Exclude Color Flow (DT=2) — not spectral
    if data_type == 2:
        return False
    # SF=2 (M-mode) — correctly tagged, handled by mmode_state_from_panel
    if spatial == SPATIAL_M_MODE:
        return False
    # SF=1 — potential Samsung mis-tagged tissue/spectral Doppler
    if spatial == SPATIAL_2D:
        delta_x, delta_y, units_x, units_y = region_physical_deltas(region)
        # Velocity units on Y axis → genuine tissue/spectral Doppler
        if units_y in (PHYSICAL_UNIT_CM_PER_SEC, 7):
            return True
        # SEC/Hz on X axis: only if DeltaX != DeltaY (not spatial B-mode resolution).
        # Samsung B-mode: DeltaX == DeltaY with UnitsX=UnitsY=3 (cm mis-tagged as SEC).
        if units_x in (PHYSICAL_UNIT_SEC, PHYSICAL_UNIT_HZ) and delta_x is not None and delta_y is not None:
            if abs(delta_x - delta_y) > 1e-6:
                return True
    return False


def is_mmode_region(region: Dataset) -> bool:
    return int(region.get("RegionSpatialFormat", 0) or 0) == SPATIAL_M_MODE


def spectral_doppler_region_priority(region: Dataset) -> int:
    """Higher = preferred when multiple regions match Doppler."""
    if not is_spectral_doppler_region(region):
        # Fallback regions from is_maybe_doppler_from_units
        if not is_maybe_doppler_from_units(region):
            return -1
        return 1  # SF=1 fallback
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
