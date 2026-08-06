"""ROI selection for ONNX LV segmentation (DICOM vs untagged cine)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import ndimage

from echo_personal_tool.domain.services.frame_panel_parser import detect_panels_heuristic
from echo_personal_tool.infrastructure.dicom_frame_panels import try_parse_from_path
from echo_personal_tool.infrastructure.pixel_utils import to_grayscale_uint8

ECHONET_CROP_CENTER_SQUARE = "center_square"
ECHONET_CROP_FULL_ROI = "full_roi"

# Extra basal sector below heuristic B-mode split (MV annulus clearance on composite cine).
CINE_PANEL_BOTTOM_PAD_RATIO = 0.05


def echonet_crop_mode_for_media(media_format: str) -> str:
    """Both DICOM and cine use center-square EchoNet embed."""
    del media_format
    return ECHONET_CROP_CENTER_SQUARE


def _bounds_to_xyxy(x0: float, y0: float, width: float, height: float) -> tuple[float, float, float, float]:
    return (x0, y0, x0 + width, y0 + height)


def _trim_lateral_content_columns(
    grayscale: np.ndarray,
    *,
    y0: int,
    y1: int,
    std_threshold: float = 12.0,
    mean_margin: float = 8.0,
    min_run_width_ratio: float = 0.22,
    pad_px: int = 8,
) -> tuple[int, int]:
    """Largest high-activity column run inside the B-mode strip (excludes side UI bars)."""
    _height, width = grayscale.shape[:2]
    strip = grayscale[y0:y1, :].astype(np.float32)
    if strip.size == 0:
        return 0, width

    col_std = np.std(strip, axis=0)
    col_mean = np.mean(strip, axis=0)
    background = float(np.percentile(col_mean, 15))
    active = (col_std >= std_threshold) | (col_mean > background + mean_margin)
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate(active):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, width - 1))
    if not runs:
        return 0, width

    min_width = max(1, int(round(width * min_run_width_ratio)))
    eligible = [run for run in runs if (run[1] - run[0] + 1) >= min_width]
    if not eligible:
        eligible = runs
    best_start, best_end = max(eligible, key=lambda run: run[1] - run[0])
    x0 = max(0, best_start - pad_px)
    x1 = min(width, best_end + 1 + pad_px)
    if x1 <= x0:
        return 0, width
    return x0, x1


def _trim_sector_content_bounds(
    grayscale: np.ndarray,
    roi_xyxy: tuple[float, float, float, float],
    *,
    intensity_percentile: float = 35.0,
    pad_px: int = 6,
    trim_bottom: bool = True,
    apex_guard: bool = False,
    apex_guard_max_removal_ratio: float = 0.15,
    apex_guard_band_ratio: float = 0.12,
) -> tuple[float, float, float, float]:
    """Tighten ROI to the fan sector (drop black margins above/below tissue).

    When apex_guard=True, aborts trim if removed area exceeds
    apex_guard_max_removal_ratio of original height or apex band is empty.
    """
    x0f, y0f, x1f, y1f = roi_xyxy
    x0 = int(np.clip(round(x0f), 0, grayscale.shape[1] - 1))
    y0 = int(np.clip(round(y0f), 0, grayscale.shape[0] - 1))
    x1 = int(np.clip(round(x1f), x0 + 1, grayscale.shape[1]))
    y1 = int(np.clip(round(y1f), y0 + 1, grayscale.shape[0]))
    original_height = y1 - y0
    panel = grayscale[y0:y1, x0:x1]
    if panel.size == 0:
        return roi_xyxy

    threshold = float(np.percentile(panel, intensity_percentile))
    labeled, component_count = ndimage.label(panel > threshold)
    if component_count == 0:
        return roi_xyxy

    counts = np.bincount(labeled.ravel())
    counts[0] = 0
    largest_label = int(np.argmax(counts))
    component = labeled == largest_label
    ys, xs = np.where(component)
    if xs.size == 0:
        return roi_xyxy

    sx0 = max(0, int(xs.min()) - pad_px)
    sy0 = max(0, int(ys.min()) - pad_px)
    sx1 = min(panel.shape[1], int(xs.max()) + 1 + pad_px)
    if trim_bottom:
        sy1 = min(panel.shape[0], int(ys.max()) + 1 + pad_px)
    else:
        sy1 = panel.shape[0]
    if sx1 <= sx0 or sy1 <= sy0:
        return roi_xyxy

    trimmed_height = sy1 - sy0
    if apex_guard and original_height > 0:
        removal_ratio = (original_height - trimmed_height) / original_height
        if removal_ratio > apex_guard_max_removal_ratio:
            return roi_xyxy
        apex_band_start = sy0
        apex_band_end = min(sy1, sy0 + int(round(original_height * apex_guard_band_ratio)))
        if apex_band_end <= apex_band_start:
            return roi_xyxy
        apex_panel = grayscale[y0 + apex_band_start : y0 + apex_band_end, x0 + sx0 : x0 + sx1]
        if apex_panel.size == 0 or not np.any(apex_panel > threshold):
            return roi_xyxy

    return (float(x0 + sx0), float(y0 + sy0), float(x0 + sx1), float(y0 + sy1))


def resolve_cine_segment_roi_xyxy(frame: np.ndarray) -> tuple[float, float, float, float] | None:
    """Heuristic B-mode strip for MP4/video without DICOM ultrasound regions."""
    try:
        grayscale = to_grayscale_uint8(frame)
    except ValueError:
        return None

    height, width = grayscale.shape[:2]
    layout = detect_panels_heuristic(grayscale)
    if layout is not None and layout.b_mode is not None:
        bounds = layout.b_mode.bounds
        panel_y0 = int(round(bounds.y0))
        panel_y1 = int(round(bounds.y0 + bounds.height))
    else:
        panel_y0 = 0
        panel_y1 = height

    panel_y1 = min(
        height - 8,
        panel_y1 + max(12, int(round(height * CINE_PANEL_BOTTOM_PAD_RATIO))),
    )

    x0, x1 = _trim_lateral_content_columns(grayscale, y0=panel_y0, y1=panel_y1)
    panel_roi = (float(x0), float(panel_y0), float(x1), float(panel_y1))
    return _trim_sector_content_bounds(
        grayscale,
        panel_roi,
        trim_bottom=False,
        apex_guard=True,
    )


def resolve_dicom_segment_roi_xyxy(
    frame: np.ndarray,
    instance_path: Path | None,
) -> tuple[float, float, float, float] | None:
    """DICOM SequenceOfUltrasoundRegions first, then heuristic fallback.

    No sector trim applied — SequenceOfUltrasoundRegions bounds are already
    correct for DICOM; trimming risks cutting the LV apex.
    """
    if instance_path is not None:
        layout = try_parse_from_path(instance_path)
        if layout is not None and layout.b_mode is not None:
            bounds = layout.b_mode.bounds
            return _bounds_to_xyxy(bounds.x0, bounds.y0, bounds.width, bounds.height)

    return resolve_cine_segment_roi_xyxy(frame)


def resolve_segment_roi_xyxy(
    frame: np.ndarray,
    *,
    media_format: str,
    instance_path: Path | None = None,
    frozen_cine_roi: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float] | None:
    if media_format == "dicom":
        return resolve_dicom_segment_roi_xyxy(frame, instance_path)
    if frozen_cine_roi is not None:
        return frozen_cine_roi
    return resolve_cine_segment_roi_xyxy(frame)
