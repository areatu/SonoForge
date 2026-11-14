"""Resolve pixel spacing from DICOM tags and manual calibration."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, radians, sin
from typing import Any

from pydicom.dataset import Dataset

from echo_personal_tool.domain.models.calibration import (
    CALIBRATION_NONE,
    CalibrationConfidence,
    CalibrationContext,
    CalibrationRegion,
    CalibrationScope,
    select_calibration,
)
from echo_personal_tool.domain.services.ultrasound_region_physics import (
    PHYSICAL_UNIT_CM,
    PHYSICAL_UNIT_MM,
    PHYSICAL_UNIT_SEC,
    is_spatial_calibration_region,
    region_physical_deltas,
)


@dataclass(frozen=True)
class PixelSpacingResolution:
    """Pixel spacing in mm (row, column), source tag and calibration context."""

    spacing: tuple[float, float]
    source: str
    calibration: CalibrationContext | None = None


def spacing_from_known_distance(
    pixel_length: float,
    known_mm: float,
) -> tuple[float, float]:
    """Derive isotropic spacing from a calibration line of known length in mm."""

    if not isfinite(pixel_length) or pixel_length <= 0:
        raise ValueError("pixel_length must be positive")
    if not isfinite(known_mm) or known_mm <= 0:
        raise ValueError("known_mm must be positive")
    spacing = known_mm / pixel_length
    if not isfinite(spacing) or spacing <= 0:
        raise ValueError("spacing must be finite and positive")
    return (spacing, spacing)


def _valid_spacing_pair(spacing: tuple[float, float] | None) -> bool:
    if spacing is None:
        return False
    try:
        row, col = float(spacing[0]), float(spacing[1])
    except (TypeError, ValueError):
        return False
    return isfinite(row) and isfinite(col) and row > 0.0 and col > 0.0


def effective_pixel_spacing(
    dicom_spacing: tuple[float, float] | None,
    manual_spacing: tuple[float, float] | None,
) -> tuple[float, float] | None:
    """Manual calibration overrides DICOM-derived spacing when both are valid.

    A non-finite or non-positive manual pair is discarded rather than promoted
    to a calibration; the DICOM pair is still used when it is valid (#547).
    """
    if _valid_spacing_pair(manual_spacing):
        return manual_spacing
    if _valid_spacing_pair(dicom_spacing):
        return dicom_spacing
    return None


def manual_calibration_context(
    spacing: tuple[float, float],
    *,
    frame_index: int | None = None,
    region: CalibrationRegion | None = None,
    revision: int = 0,
) -> CalibrationContext:
    """Calibration from a known-distance line.

    A single line gives isotropic spacing, not evidence that the pixel grid is
    isotropic.  The context is therefore ``ASSUMED`` and carries
    ``assumed_isotropic=True`` so the UI/report can say so (#547, #555).
    """
    scope = CalibrationScope.INSTANCE
    if region is not None:
        scope = CalibrationScope.REGION
    elif frame_index is not None:
        scope = CalibrationScope.FRAME
    return CalibrationContext(
        spacing=(float(spacing[0]), float(spacing[1])),
        source="manual",
        scope=scope,
        confidence=CalibrationConfidence.ASSUMED,
        frame_index=frame_index,
        region=region,
        revision=revision,
        assumed_isotropic=True,
    )


def resolution_from_contexts(contexts: tuple[CalibrationContext, ...]) -> PixelSpacingResolution | None:
    """Choose one unambiguous instance default from already-resolved contexts."""
    context = _default_context(contexts)
    if context is None:
        return None
    return PixelSpacingResolution(spacing=context.spacing, source=context.source, calibration=context)


def resolve_pixel_spacing(dataset: Dataset) -> PixelSpacingResolution | None:
    """Return one unambiguous spacing, or ``None`` when only scoped scales exist.

    Per-frame and multi-panel calibrations are returned by
    :func:`resolve_calibration_contexts`; collapsing them into one
    instance-level tuple would attach the wrong scale to measurements outside
    the selected frame/region (#547).
    """
    return resolution_from_contexts(resolve_calibration_contexts(dataset))


def resolve_calibration_contexts(dataset: Dataset) -> tuple[CalibrationContext, ...]:
    """All frame/region-scoped spatial calibrations, in source priority order.

    Only the highest-priority source that provides a valid context is used, as
    before.  Within that source every valid frame/region is retained, so a
    consumer can select by measurement geometry instead of trusting the first
    item.
    """
    resolvers = (
        _from_pixel_spacing_tag,
        _from_imager_pixel_spacing,
        _from_nominal_scanned_pixel_spacing,
        _from_ultrasound_regions,
        _from_shared_functional_groups,
        _from_per_frame_functional_groups,
    )
    for resolver in resolvers:
        contexts = tuple(resolver(dataset))
        if contexts:
            return contexts
    return ()


def select_for_geometry(
    contexts: tuple[CalibrationContext, ...],
    *,
    frame_index: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> CalibrationContext:
    """Select a context, raising ``ValueError`` with a stable reason code."""
    selection = select_calibration(contexts, frame_index=frame_index, bbox=bbox)
    if selection.context is None:
        raise ValueError(selection.reason or CALIBRATION_NONE)
    return selection.context


def _default_context(contexts: tuple[CalibrationContext, ...]) -> CalibrationContext | None:
    if not contexts:
        return None
    if len(contexts) == 1:
        return contexts[0]
    spacings = {(context.row_spacing, context.column_spacing) for context in contexts}
    if len(spacings) == 1:
        # Every available region/frame agrees on the scale: an instance-level
        # default is safe even though the source scopes each panel separately.
        return contexts[0]
    return None


def _pair_context(
    first: Any,
    second: Any,
    *,
    source: str,
    confidence: CalibrationConfidence,
    scope: CalibrationScope = CalibrationScope.INSTANCE,
    frame_index: int | None = None,
    region: CalibrationRegion | None = None,
) -> CalibrationContext | None:
    try:
        row = float(first)
        col = float(second)
    except (TypeError, ValueError):
        return None
    if not isfinite(row) or not isfinite(col) or row <= 0 or col <= 0:
        return None
    try:
        return CalibrationContext(
            spacing=(row, col),
            source=source,
            scope=scope,
            confidence=confidence,
            frame_index=frame_index,
            region=region,
        )
    except ValueError:
        return None


def _from_pixel_spacing_tag(dataset: Dataset) -> list[CalibrationContext]:
    spacing = dataset.get("PixelSpacing")
    if spacing is not None and len(spacing) >= 2:
        context = _pair_context(
            spacing[0],
            spacing[1],
            source="PixelSpacing",
            confidence=CalibrationConfidence.MEASURED,
        )
        return [context] if context is not None else []
    return []


def _from_imager_pixel_spacing(dataset: Dataset) -> list[CalibrationContext]:
    spacing = dataset.get("ImagerPixelSpacing")
    if spacing is not None and len(spacing) >= 2:
        # ImagerPixelSpacing is a detector-plane value, not necessarily the
        # patient-plane scale; never present it as measured spatial calibration.
        context = _pair_context(
            spacing[0],
            spacing[1],
            source="ImagerPixelSpacing",
            confidence=CalibrationConfidence.ASSUMED,
        )
        return [context] if context is not None else []
    return []


def _from_nominal_scanned_pixel_spacing(dataset: Dataset) -> list[CalibrationContext]:
    spacing = dataset.get("NominalScannedPixelSpacing")
    if spacing is not None and len(spacing) >= 2:
        context = _pair_context(
            spacing[0],
            spacing[1],
            source="NominalScannedPixelSpacing",
            confidence=CalibrationConfidence.ASSUMED,
        )
        return [context] if context is not None else []
    return []


def _region_from_dataset(region: Dataset) -> CalibrationRegion | None:
    try:
        x0 = int(region.get("RegionLocationMinX0", 0) or 0)
        x1 = int(region.get("RegionLocationMaxX1", 0) or 0)
        y0 = int(region.get("RegionLocationMinY0", 0) or 0)
        y1 = int(region.get("RegionLocationMaxY1", 0) or 0)
    except (TypeError, ValueError):
        return None
    # DICOM max coordinates are inclusive; convert to half-open bounds.
    try:
        return CalibrationRegion(x0=x0, x1=x1 + 1, y0=y0, y1=y1 + 1)
    except ValueError:
        return None


def _from_ultrasound_regions(dataset: Dataset) -> list[CalibrationContext]:
    regions = dataset.get("SequenceOfUltrasoundRegions")
    if not regions:
        return []
    contexts: list[CalibrationContext] = []
    for region in regions:
        if not is_spatial_calibration_region(region):
            continue
        context = _spacing_context_from_ultrasound_region(region)
        if context is not None:
            contexts.append(context)
    return contexts


def _spacing_context_from_ultrasound_region(region: Dataset) -> CalibrationContext | None:
    delta_x, delta_y, units_x, units_y = region_physical_deltas(region)
    if delta_x is None or delta_y is None:
        return None

    assumed = False

    def _delta_to_mm(delta: float, units: int | None, *, tissue_2d: bool) -> float | None:
        nonlocal assumed
        magnitude = abs(delta)
        if not isfinite(magnitude):
            return None
        if units in (None, PHYSICAL_UNIT_CM):
            result = magnitude * 10.0
        elif units == PHYSICAL_UNIT_MM:
            result = magnitude
        elif tissue_2d and units == PHYSICAL_UNIT_SEC and magnitude < 1.0:
            # Vendor heuristic: seconds used where length was intended.  Keep
            # the value usable but mark it as an assumption, not spatial truth.
            assumed = True
            result = magnitude * 10.0
        else:
            return None
        return result if isfinite(result) and result > 0.0 else None

    spatial = int(region.get("RegionSpatialFormat", 0) or 0)
    data_type = int(region.get("RegionDataType", 0) or 0)
    tissue_2d = spatial == 1 and data_type == 1
    col_mm = _delta_to_mm(delta_x, units_x, tissue_2d=tissue_2d)
    row_mm = _delta_to_mm(delta_y, units_y, tissue_2d=tissue_2d)
    if col_mm is None or row_mm is None:
        return None
    confidence = CalibrationConfidence.ASSUMED if assumed else CalibrationConfidence.DERIVED
    bounds = _region_from_dataset(region)
    if bounds is None:
        return _pair_context(
            row_mm,
            col_mm,
            source="SequenceOfUltrasoundRegions",
            confidence=confidence,
        )
    return _pair_context(
        row_mm,
        col_mm,
        source="SequenceOfUltrasoundRegions",
        confidence=confidence,
        scope=CalibrationScope.REGION,
        region=bounds,
    )


def _from_shared_functional_groups(dataset: Dataset) -> list[CalibrationContext]:
    shared = dataset.get("SharedFunctionalGroupsSequence")
    if not shared:
        return []
    context = _context_from_functional_group_item(
        shared[0],
        "SharedFunctionalGroupsSequence",
    )
    return [context] if context is not None else []


def _from_per_frame_functional_groups(dataset: Dataset) -> list[CalibrationContext]:
    per_frame = dataset.get("PerFrameFunctionalGroupsSequence")
    if not per_frame:
        return []
    contexts: list[CalibrationContext] = []
    for frame_index, item in enumerate(per_frame):
        context = _context_from_functional_group_item(
            item,
            "PerFrameFunctionalGroupsSequence",
            frame_index=frame_index,
        )
        if context is not None:
            contexts.append(context)
    if not contexts:
        return []
    if len({context.spacing for context in contexts}) == 1 and len(contexts) == len(per_frame):
        # Uniform per-frame measures describe the whole instance; attach one
        # instance-level context instead of a frame-specific one.
        first = contexts[0]
        return [
            CalibrationContext(
                spacing=first.spacing,
                source=first.source,
                scope=CalibrationScope.INSTANCE,
                confidence=first.confidence,
            )
        ]
    return contexts


def _context_from_functional_group_item(
    item: Dataset,
    source_prefix: str,
    *,
    frame_index: int | None = None,
) -> CalibrationContext | None:
    pixel_measures = item.get("PixelMeasuresSequence")
    if not pixel_measures:
        return None
    spacing = pixel_measures[0].get("PixelSpacing")
    if spacing is None or len(spacing) < 2:
        return None
    scope = CalibrationScope.FRAME if frame_index is not None else CalibrationScope.INSTANCE
    return _pair_context(
        spacing[0],
        spacing[1],
        source=f"{source_prefix}/PixelSpacing",
        confidence=CalibrationConfidence.DERIVED,
        scope=scope,
        frame_index=frame_index,
    )


def pixel_length_along_angle(pixel_length: float, angle_degrees: float) -> float:
    """Euclidean length of a line ROI in image coordinates."""

    angle_radians = radians(angle_degrees)
    x_pixels = pixel_length * cos(angle_radians)
    y_pixels = pixel_length * sin(angle_radians)
    return float((x_pixels**2 + y_pixels**2) ** 0.5)
