"""Resolve pixel spacing from DICOM tags and manual calibration."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin

from pydicom.dataset import Dataset


@dataclass(frozen=True)
class PixelSpacingResolution:
    """Pixel spacing in mm (row, column) and the DICOM tag path used."""

    spacing: tuple[float, float]
    source: str


def spacing_from_known_distance(
    pixel_length: float,
    known_mm: float,
) -> tuple[float, float]:
    """Derive isotropic spacing from a calibration line of known length in mm."""

    if pixel_length <= 0:
        raise ValueError("pixel_length must be positive")
    if known_mm <= 0:
        raise ValueError("known_mm must be positive")
    spacing = known_mm / pixel_length
    return (spacing, spacing)


def effective_pixel_spacing(
    dicom_spacing: tuple[float, float] | None,
    manual_spacing: tuple[float, float] | None,
) -> tuple[float, float] | None:
    """Manual calibration overrides DICOM-derived spacing."""

    if manual_spacing is not None:
        return manual_spacing
    return dicom_spacing


def resolve_pixel_spacing(dataset: Dataset) -> PixelSpacingResolution | None:
    """Try all known DICOM sources for pixel spacing (mm per pixel)."""

    resolvers = (
        _from_pixel_spacing_tag,
        _from_imager_pixel_spacing,
        _from_nominal_scanned_pixel_spacing,
        _from_ultrasound_regions,
        _from_shared_functional_groups,
        _from_per_frame_functional_groups,
    )
    for resolver in resolvers:
        result = resolver(dataset)
        if result is not None:
            return result
    return None


def _pair_from_values(first: object, second: object, source: str) -> PixelSpacingResolution | None:
    try:
        row = float(first)
        col = float(second)
    except (TypeError, ValueError):
        return None
    if row <= 0 or col <= 0:
        return None
    return PixelSpacingResolution(spacing=(row, col), source=source)


def _from_pixel_spacing_tag(dataset: Dataset) -> PixelSpacingResolution | None:
    spacing = dataset.get("PixelSpacing")
    if spacing is not None and len(spacing) >= 2:
        return _pair_from_values(spacing[0], spacing[1], "PixelSpacing")
    return None


def _from_imager_pixel_spacing(dataset: Dataset) -> PixelSpacingResolution | None:
    spacing = dataset.get("ImagerPixelSpacing")
    if spacing is not None and len(spacing) >= 2:
        return _pair_from_values(spacing[0], spacing[1], "ImagerPixelSpacing")
    return None


def _from_nominal_scanned_pixel_spacing(dataset: Dataset) -> PixelSpacingResolution | None:
    spacing = dataset.get("NominalScannedPixelSpacing")
    if spacing is not None and len(spacing) >= 2:
        return _pair_from_values(spacing[0], spacing[1], "NominalScannedPixelSpacing")
    return None


def _from_ultrasound_regions(dataset: Dataset) -> PixelSpacingResolution | None:
    regions = dataset.get("SequenceOfUltrasoundRegions")
    if not regions:
        return None

    preferred: PixelSpacingResolution | None = None
    fallback: PixelSpacingResolution | None = None
    for region in regions:
        result = _spacing_from_ultrasound_region(region)
        if result is None:
            continue
        spatial = int(region.get("RegionSpatialFormat", 0) or 0)
        data_type = int(region.get("RegionDataType", 0) or 0)
        if spatial == 1 and data_type == 1:
            preferred = result
            break
        if fallback is None:
            fallback = result
    return preferred or fallback


def _spacing_from_ultrasound_region(region: Dataset) -> PixelSpacingResolution | None:
    delta_x = region.get("PhysicalDeltaX")
    delta_y = region.get("PhysicalDeltaY")
    if delta_x is None or delta_y is None:
        return None
    try:
        col_mm = abs(float(delta_x)) * 10.0
        row_mm = abs(float(delta_y)) * 10.0
    except (TypeError, ValueError):
        return None
    if row_mm <= 0 or col_mm <= 0:
        return None
    return PixelSpacingResolution(
        spacing=(row_mm, col_mm),
        source="SequenceOfUltrasoundRegions",
    )


def _from_shared_functional_groups(dataset: Dataset) -> PixelSpacingResolution | None:
    shared = dataset.get("SharedFunctionalGroupsSequence")
    if not shared:
        return None
    return _spacing_from_functional_group_item(shared[0], "SharedFunctionalGroupsSequence")


def _from_per_frame_functional_groups(dataset: Dataset) -> PixelSpacingResolution | None:
    per_frame = dataset.get("PerFrameFunctionalGroupsSequence")
    if not per_frame:
        return None
    return _spacing_from_functional_group_item(
        per_frame[0],
        "PerFrameFunctionalGroupsSequence",
    )


def _spacing_from_functional_group_item(
    item: Dataset,
    source_prefix: str,
) -> PixelSpacingResolution | None:
    pixel_measures = item.get("PixelMeasuresSequence")
    if not pixel_measures:
        return None
    spacing = pixel_measures[0].get("PixelSpacing")
    if spacing is None or len(spacing) < 2:
        return None
    return _pair_from_values(spacing[0], spacing[1], f"{source_prefix}/PixelSpacing")


def pixel_length_along_angle(pixel_length: float, angle_degrees: float) -> float:
    """Euclidean length of a line ROI in image coordinates."""

    angle_radians = radians(angle_degrees)
    x_pixels = pixel_length * cos(angle_radians)
    y_pixels = pixel_length * sin(angle_radians)
    return (x_pixels**2 + y_pixels**2) ** 0.5
