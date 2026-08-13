"""Vendor-aware DICOM calibration bridge.

Integrates vendor profiles with the existing calibration pipeline.
Replaces vendor-specific workarounds in dicom_doppler_calibration.py
with profile-based dispatch.
"""

from __future__ import annotations

import logging

import numpy as np
from pydicom.dataset import Dataset

from echo_personal_tool.domain.models.doppler_roi import (
    DopplerCalibrationState,
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.services.doppler_baseline import detect_baseline_y
from echo_personal_tool.domain.services.doppler_calibration import calibration_from_roi_and_baseline
from echo_personal_tool.domain.services.spectrogram_detector import detect_spectrogram_roi
from echo_personal_tool.domain.services.ultrasound_region_physics import (
    is_maybe_doppler_from_units,
    is_spectral_doppler_region,
)
from echo_personal_tool.infrastructure.samsung_tick_detector import detect_ticks
from echo_personal_tool.infrastructure.vendor_profiles.base import (
    Vendor,
    VendorProfile,
)
from echo_personal_tool.infrastructure.vendor_profiles.detector import detect_vendor
from echo_personal_tool.infrastructure.vendor_profiles.registry import get_profile_for_dataset

logger = logging.getLogger(__name__)


def _region_bounds(region: Dataset) -> tuple[float, float, float, float] | None:
    """Extract region bounding box."""
    min_x = region.get("RegionLocationMinX0")
    min_y = region.get("RegionLocationMinY0")
    max_x = region.get("RegionLocationMaxX1")
    max_y = region.get("RegionLocationMaxY1")
    if None in (min_x, min_y, max_x, max_y):
        return None
    return float(min_x), float(min_y), float(max_x), float(max_y)


def _compute_baseline_with_profile(
    profile: VendorProfile,
    region: Dataset,
    frame_height: int,
    frame_pixels: np.ndarray | None,
    roi: DopplerSpectrogramRoi,
) -> float:
    """Compute baseline using vendor profile, falling back to pixel detection."""
    # 1. Try vendor-specific baseline computation
    try:
        result = profile.compute_baseline(region, frame_height, frame_pixels)
        if result.confidence >= 0.5:
            logger.debug(
                "Using vendor baseline: vendor=%s, y=%.1f, conf=%.2f, source=%s",
                profile.vendor.value,
                result.baseline_y,
                result.confidence,
                result.source,
            )
            return result.baseline_y
    except Exception as e:
        logger.debug("Vendor baseline computation failed: %s", e)

    # 2. Fallback: center of ROI
    return roi.y0 + roi.height / 2.0


def try_parse_with_vendor_profile(
    dataset: Dataset,
    frame: np.ndarray | None = None,
    *,
    kind: DopplerKind = DopplerKind.SPECTRAL,
) -> DopplerCalibrationState | None:
    """Parse Doppler calibration using vendor-aware profiles.

    This function replaces the vendor-specific workarounds in
    dicom_doppler_calibration.py with profile-based dispatch.

    Args:
        dataset: DICOM dataset with SequenceOfUltrasoundRegions.
        frame: Optional pixel array for visual baseline detection.
        kind: Doppler kind (SPECTRAL or TISSUE).

    Returns:
        DopplerCalibrationState or None if calibration fails.
    """
    # 1. Detect vendor and get profile
    profile = get_profile_for_dataset(dataset)
    if profile is None:
        logger.debug("No vendor profile available, falling back to generic")
        return None

    regions = dataset.get("SequenceOfUltrasoundRegions")
    if not regions:
        return None

    frame_height = int(dataset.get("Rows", 0) or 0)
    if frame_height <= 0:
        return None

    # 2. Find the best Doppler region
    best_region = None
    best_priority = -1

    for region in regions:
        spatial = int(region.get("RegionSpatialFormat", 0) or 0)
        data_type = int(region.get("RegionDataType", 0) or 0)

        # Priority: explicit spectral Doppler > fallback from units
        if is_spectral_doppler_region(region):
            priority = 4 if data_type == 3 else 3
        elif is_maybe_doppler_from_units(region):
            priority = 1
        else:
            continue

        if priority > best_priority:
            best_priority = priority
            best_region = region

    if best_region is None:
        return None

    # 3. Extract region bounds
    bounds = _region_bounds(best_region)
    if bounds is None:
        return None

    x0, y0, x1, y1 = bounds
    roi = DopplerSpectrogramRoi(
        x0=x0,
        y0=y0,
        width=max(1.0, x1 - x0),
        height=max(1.0, y1 - y0),
    )

    # 4. Compute velocity span using vendor profile
    velocity_result = profile.compute_velocity_span(best_region, roi.height)
    velocity_span = velocity_result.span_cm_s if velocity_result else None

    # 5. Compute time span using vendor profile
    time_result = profile.compute_time_span(best_region, roi.width, frame)
    time_span_ms = time_result.span_ms if time_result else None

    # 6. Compute baseline using vendor profile
    baseline_y = _compute_baseline_with_profile(profile, best_region, frame_height, frame, roi)

    # 7. Build calibration state
    data_type = int(best_region.get("RegionDataType", 0) or 0)
    region_kind = DopplerKind.TISSUE if data_type in (0x10, 0x11) else kind

    candidate = calibration_from_roi_and_baseline(
        roi,
        baseline_y,
        velocity_span_cm_s=velocity_span,
        time_span_ms=time_span_ms if time_span_ms is not None else 0.0,
        kind=region_kind,
    )

    return DopplerCalibrationState(
        roi=candidate.roi,
        baseline_y_px=candidate.baseline_y_px,
        time_origin_ms=candidate.time_origin_ms,
        time_span_ms=candidate.time_span_ms,
        velocity_span_cm_s=candidate.velocity_span_cm_s,
        kind=candidate.kind,
        from_dicom_tags=True,
        time_from_dicom_tags=time_result is not None,
        velocity_from_dicom_tags=velocity_result is not None,
    )


def get_vendor_info(dataset: Dataset) -> dict[str, str | Vendor]:
    """Get vendor information from dataset for debugging/logging.

    Returns:
        Dictionary with vendor, profile class, and detection source.
    """
    from echo_personal_tool.infrastructure.vendor_profiles.detector import detect_vendor

    vendor = detect_vendor(dataset)
    profile = get_profile_for_dataset(dataset)

    return {
        "vendor": vendor,
        "profile": profile.__class__.__name__ if profile else None,
        "manufacturer": str(dataset.get("Manufacturer", "")),
        "model": str(dataset.get("ManufacturerModelName", "")),
    }


def try_parse_samsung_tick_calibration(
    dataset: Dataset,
    frame: np.ndarray | None = None,
    *,
    kind: DopplerKind = DopplerKind.SPECTRAL,
) -> DopplerCalibrationState | None:
    """Samsung RS85 tick-based time calibration fallback.

    Samsung RS85 mis-tags PW/CW Doppler regions as SF=1 with unusable
    physical deltas, so no tagged time scale exists. When called with a
    frame, the bottom-edge time ruler is detected visually and the sweep
    frequency derived from the tick spacing via the trained linear
    calibration (``frequency_hz = k_constant * spacing_px``).

    Returns a state with ``time_from_dicom_tags=True`` (so the caller's
    time-scale gates enable) using the *visible* ruler extent as the span.
    """
    if frame is None:
        return None
    if detect_vendor(dataset) is not Vendor.SAMSUNG:
        return None

    profile = get_profile_for_dataset(dataset)
    tick_calibration = getattr(profile, "_tick_calibration", None)
    if tick_calibration is None:
        return None

    arr = np.asarray(frame)
    if arr.ndim not in (2, 3):
        return None

    tick_result = detect_ticks(arr)
    if tick_result.confidence < 0.3 or tick_result.spacing_px <= 0.0:
        return None
    if len(tick_result.tick_positions) < 2:
        return None

    positions = tick_result.tick_positions
    visible_width_px = float(positions[-1] - positions[0]) + tick_result.spacing_px
    frequency_hz = tick_calibration.k_constant * tick_result.spacing_px
    per_pixel_ms = 1000.0 / frequency_hz
    time_span_ms = per_pixel_ms * visible_width_px

    # ROI: prefer detected spectrogram panel, else full-frame fallback.
    roi = None
    detected = None
    try:
        detected = detect_spectrogram_roi(arr)
    except Exception:
        detected = None
    if detected is not None:
        x0, y0, x1, y1 = detected
        roi = DopplerSpectrogramRoi(
            x0=float(x0),
            y0=float(y0),
            width=max(1.0, float(x1 - x0)),
            height=max(1.0, float(y1 - y0)),
        )
    if roi is None:
        h, w = arr.shape[:2]
        roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=float(w), height=float(h))

    baseline_y = roi.y0 + roi.height / 2.0
    try:
        detected_baseline = detect_baseline_y(arr, roi)
        if detected_baseline is not None:
            baseline_y = float(detected_baseline)
    except Exception:
        logger.debug("Samsung tick fallback: baseline detection failed")

    candidate = calibration_from_roi_and_baseline(
        roi,
        baseline_y,
        velocity_span_cm_s=kind.default_velocity_span_cm_s,
        time_span_ms=time_span_ms,
        kind=kind,
    )
    return DopplerCalibrationState(
        roi=candidate.roi,
        baseline_y_px=candidate.baseline_y_px,
        time_origin_ms=candidate.time_origin_ms,
        time_span_ms=candidate.time_span_ms,
        velocity_span_cm_s=candidate.velocity_span_cm_s,
        kind=candidate.kind,
        from_dicom_tags=True,
        time_from_dicom_tags=True,
        velocity_from_dicom_tags=False,
    )
