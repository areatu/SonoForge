"""Parse Doppler spectrogram region from DICOM ultrasound regions."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset

from echo_personal_tool.domain.models.doppler_roi import (
    DopplerCalibrationState,
    DopplerKind,
    DopplerSpectrogramRoi,
)
from echo_personal_tool.domain.services.doppler_baseline import detect_baseline_y
from echo_personal_tool.domain.services.doppler_calibration import calibration_from_roi_and_baseline
from echo_personal_tool.domain.services.ultrasound_region_physics import (
    is_maybe_doppler_from_units,
    is_spectral_doppler_region,
    region_physical_deltas,
    spectral_doppler_region_priority,
    time_span_ms_from_region,
    velocity_span_cm_s_from_region,
)
from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl

logger = logging.getLogger(__name__)


def _region_bounds(region: Dataset) -> tuple[float, float, float, float] | None:
    min_x = region.get("RegionLocationMinX0")
    min_y = region.get("RegionLocationMinY0")
    max_x = region.get("RegionLocationMaxX1")
    max_y = region.get("RegionLocationMaxY1")
    if None in (min_x, min_y, max_x, max_y):
        return None
    return float(min_x), float(min_y), float(max_x), float(max_y)


def _force_roi_to_bottom_half(
    roi: DopplerSpectrogramRoi,
    frame_height: float,
) -> DopplerSpectrogramRoi:
    """Force ROI to bottom half of image for Doppler regions.

    Samsung RS85 mis-tags Doppler as SF=1 with B-mode region bounds.
    When the ROI y0 is in the top half (< 50% of frame height),
    relocate it to the bottom half where the Doppler spectrum actually is.
    """
    if roi.y0 >= frame_height * 0.5:
        return roi
    # Keep same width and height, move to bottom half
    new_y0 = frame_height * 0.5
    return DopplerSpectrogramRoi(
        x0=roi.x0,
        y0=new_y0,
        width=roi.width,
        height=min(roi.height, frame_height - new_y0),
    )


def _sorted_doppler_regions(regions: object) -> list[Dataset]:
    strict = [region for region in regions if is_spectral_doppler_region(region)]
    if strict:
        return sorted(strict, key=spectral_doppler_region_priority, reverse=True)
    # Samsung mis-tags tissue/spectral Doppler as SF=1. Fallback: trust units.
    # But skip SF=1 if there's an SF=2 (M-mode) region — that's B-mode strip.
    has_mmode = any(
        int(r.get("RegionSpatialFormat", 0) or 0) == 2 for r in regions
    )
    if has_mmode:
        return []
    fallback = [region for region in regions if is_maybe_doppler_from_units(region)]
    return sorted(fallback, key=spectral_doppler_region_priority, reverse=True)


def _detect_baseline_fallback(frame: np.ndarray, roi: DopplerSpectrogramRoi) -> float:
    """Estimate baseline from pixel intensities when detect_baseline_y fails."""
    y0 = max(0, int(roi.y0))
    y1 = min(frame.shape[0], int(roi.y0 + roi.height))
    x0 = max(0, int(roi.x0))
    x1 = min(frame.shape[1], int(roi.x0 + roi.width))

    if y1 <= y0 or x1 <= x0:
        return roi.y0 + roi.height / 2.0

    roi_gray = frame[y0:y1, x0:x1]
    if roi_gray.ndim == 3:
        roi_gray = np.mean(roi_gray[..., :3], axis=2)

    # Sum horizontally — baseline is bright horizontal line
    profile = np.mean(roi_gray, axis=1)
    kernel = np.ones(5) / 5
    smoothed = np.convolve(profile, kernel, mode='same')
    baseline_rel = float(np.argmax(smoothed))
    return y0 + baseline_rel


def _extract_samsung_baseline(region: Dataset) -> float | None:
    """Extract baseline (absolute Y) from Samsung ReferencePixelY0 tag.

    ReferencePixelY0 is relative to the region origin:
    baseline_y = RegionLocationMinY0 + ReferencePixelY0
    """
    ref_y = region.get("ReferencePixelY0")
    if ref_y is None:
        return None
    try:
        ref_y_f = float(ref_y)
    except (TypeError, ValueError):
        return None
    min_y = region.get("RegionLocationMinY0")
    if min_y is None:
        return None
    return float(min_y) + ref_y_f


def try_parse_from_dataset(
    dataset: Dataset,
    frame: object | None = None,
    *,
    kind: DopplerKind = DopplerKind.SPECTRAL,
) -> DopplerCalibrationState | None:
    """Build calibration from DICOM tags (time and/or velocity axis from region deltas)."""
    regions = dataset.get("SequenceOfUltrasoundRegions")
    if not regions:
        return None

    # Get frame height for ROI relocation
    frame_height = float(dataset.get("Rows", 0) or 0)

    best: DopplerCalibrationState | None = None
    for region in _sorted_doppler_regions(regions):
        bounds = _region_bounds(region)
        if bounds is None:
            continue

        x0, y0, x1, y1 = bounds
        roi = DopplerSpectrogramRoi(
            x0=x0,
            y0=y0,
            width=max(1.0, x1 - x0),
            height=max(1.0, y1 - y0),
        )

        # Samsung RS85 mis-tags Doppler as SF=1 with B-mode region bounds.
        # Force ROI to bottom half for fallback (SF=1) regions.
        if not is_spectral_doppler_region(region) and frame_height > 0:
            roi = _force_roi_to_bottom_half(roi, frame_height)

        delta_x, delta_y, units_x, units_y = region_physical_deltas(region)

        time_span_ms = None
        if delta_x is not None and units_x is not None:
            time_span_ms = time_span_ms_from_region(roi.width, delta_x, units_x)
            if time_span_ms is None:
                logger.debug("Cannot compute time span: delta_x=%s, units_x=%s", delta_x, units_x)

        velocity_span = None
        if delta_y is not None and units_y is not None:
            velocity_span = velocity_span_cm_s_from_region(roi.height, delta_y, units_y)
            if velocity_span is None:
                logger.debug("Cannot compute velocity span: delta_y=%s, units_y=%s", delta_y, units_y)

        # Baseline detection priority:
        # 1. ReferencePixelY0 (Samsung vendor-specific)
        # 2. Auto-detect by intensity (detect_baseline_y)
        # 3. Intensity fallback (_detect_baseline_fallback)
        # 4. Center of ROI (last resort)
        baseline_y = roi.y0 + roi.height / 2.0
        samsung_baseline = _extract_samsung_baseline(region)
        if samsung_baseline is not None:
            baseline_y = samsung_baseline
            logger.debug("Using Samsung ReferencePixelY0 baseline: %s", baseline_y)
        elif frame is not None:
            arr = np.asarray(frame)
            if arr.ndim >= 2:
                try:
                    baseline_y = detect_baseline_y(arr, roi)
                except Exception:
                    logger.debug("detect_baseline_y failed, using intensity fallback")
                    baseline_y = _detect_baseline_fallback(arr, roi)

        data_type = int(region.get("RegionDataType", 0) or 0)
        region_kind = DopplerKind.TISSUE if data_type in (0x10, 0x11) else kind
        candidate = calibration_from_roi_and_baseline(
            roi,
            baseline_y,
            velocity_span_cm_s=velocity_span,
            time_span_ms=time_span_ms if time_span_ms is not None else 0.0,
            kind=region_kind,
        )
        candidate = DopplerCalibrationState(
            roi=candidate.roi,
            baseline_y_px=candidate.baseline_y_px,
            time_origin_ms=candidate.time_origin_ms,
            time_span_ms=candidate.time_span_ms,
            velocity_span_cm_s=candidate.velocity_span_cm_s,
            kind=candidate.kind,
            from_dicom_tags=True,
            time_from_dicom_tags=time_span_ms is not None,
            velocity_from_dicom_tags=velocity_span is not None,
        )
        if candidate.has_time_scale_from_dicom() or candidate.has_velocity_scale_from_dicom():
            return candidate
        if best is None:
            best = candidate

    return best


def try_parse_from_path(
    path: Path,
    *,
    kind: DopplerKind = DopplerKind.SPECTRAL,
    frame: object | None = None,
) -> DopplerCalibrationState | None:
    """Load DICOM and attempt spectrogram region calibration from tags only."""
    try:
        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    except Exception:
        return None

    if frame is None:
        try:
            reader = DicomReaderImpl()
            frame = reader.read_pixels(path, 0)
        except Exception:
            frame = None

    return try_parse_from_dataset(dataset, frame, kind=kind)
