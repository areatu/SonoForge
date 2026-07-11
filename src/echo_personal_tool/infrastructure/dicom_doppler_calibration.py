"""Parse Doppler spectrogram region from DICOM ultrasound regions."""

from __future__ import annotations

from pathlib import Path

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
    is_spectral_doppler_region,
    region_physical_deltas,
    spectral_doppler_region_priority,
    time_span_ms_from_region,
    velocity_span_cm_s_from_region,
)
from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl


def _region_bounds(region: Dataset) -> tuple[float, float, float, float] | None:
    min_x = region.get("RegionLocationMinX0")
    min_y = region.get("RegionLocationMinY0")
    max_x = region.get("RegionLocationMaxX1")
    max_y = region.get("RegionLocationMaxY1")
    if None in (min_x, min_y, max_x, max_y):
        return None
    return float(min_x), float(min_y), float(max_x), float(max_y)


def _sorted_doppler_regions(regions: object) -> list[Dataset]:
    items = [region for region in regions if is_spectral_doppler_region(region)]
    return sorted(items, key=spectral_doppler_region_priority, reverse=True)


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

        delta_x, delta_y, units_x, units_y = region_physical_deltas(region)
        if None in (delta_x, units_x):
            continue

        time_span_ms = time_span_ms_from_region(roi.width, delta_x, units_x)

        velocity_span = None
        if delta_y is not None and units_y is not None:
            velocity_span = velocity_span_cm_s_from_region(roi.height, delta_y, units_y)

        # Skip if neither time nor velocity could be computed
        if time_span_ms is None and velocity_span is None:
            continue

        baseline_y = roi.y0 + roi.height / 2.0
        if frame is not None:
            import numpy as np

            arr = np.asarray(frame)
            if arr.ndim >= 2:
                baseline_y = detect_baseline_y(arr, roi)

        data_type = int(region.get("RegionDataType", 0) or 0)
        region_kind = DopplerKind.TISSUE if data_type in (0x11, 17) else kind
        candidate = calibration_from_roi_and_baseline(
            roi,
            baseline_y,
            velocity_span_cm_s=velocity_span,
            time_span_ms=time_span_ms if time_span_ms is not None else 1000.0,
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
        dataset = pydicom.dcmread(path, force=True)
    except Exception:
        return None

    if frame is None:
        try:
            reader = DicomReaderImpl()
            frame = reader.read_pixels(path, 0)
        except Exception:
            frame = None

    return try_parse_from_dataset(dataset, frame, kind=kind)
