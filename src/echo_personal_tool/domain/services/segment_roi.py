"""ROI selection for ONNX LV segmentation (DICOM vs untagged cine)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from scipy import ndimage

from echo_personal_tool.infrastructure.dicom_frame_panels import try_parse_from_path
from echo_personal_tool.infrastructure.pixel_utils import to_grayscale_uint8
from echo_personal_tool.infrastructure.samsung_tick_detector import detect_ticks

logger = logging.getLogger(__name__)

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
    """Detect Doppler ROI from horizontal time scale at bottom of frame.

    Algorithm:
    1. Detect horizontal tick marks (time scale) in the bottom 15% of the frame.
    2. If ticks found with sufficient confidence → Doppler frame, compute ROI
       from tick positions and the dark spectral band above them.
    3. If no ticks → B-mode frame, return None (no ROI needed).

    This replaces the old heuristic that always returned a B-mode ROI, which
    incorrectly marked B-mode frames as having Doppler content.
    """
    try:
        grayscale = to_grayscale_uint8(frame)
    except ValueError:
        return None

    height, width = grayscale.shape[:2]
    if height < 80 or width < 80:
        return None

    # Step 1: Detect horizontal time scale (tick marks) at bottom of frame.
    # A real Doppler frame has periodic vertical ticks on a ruler near the bottom.
    # B-mode frames have a black strip but NO periodic ticks.
    tick_result = detect_ticks(grayscale)

    if tick_result.confidence < 0.4 or len(tick_result.tick_positions) < 5:
        # No reliable time scale detected → B-mode frame, no ROI.
        logger.debug(
            "resolve_cine_segment_roi_xyxy: no time scale (conf=%.2f, ticks=%d) → B-mode",
            tick_result.confidence,
            len(tick_result.tick_positions),
        )
        return None

    # Step 2: Time scale found → Doppler frame. Compute ROI from ticks.
    band_y = tick_result.band_y  # center of tick band (bottom of spectral region)
    tick_positions = tick_result.tick_positions
    spacing = tick_result.spacing_px

    # ROI horizontal bounds: from tick positions with margin.
    tick_x0 = min(tick_positions)
    tick_x1 = max(tick_positions)
    margin_x = max(spacing * 2, 10.0)
    left_x = max(0.0, tick_x0 - margin_x)
    right_x = min(float(width), tick_x1 + margin_x)

    # ROI vertical bounds: top from dark spectral band above the ticks.
    # The spectral band sits above the time ruler and is DARK.
    # Estimate its height as ~45% of frame height (typical Samsung Doppler).
    estimated_band_height = height * 0.45
    top_y = max(0.0, band_y - estimated_band_height)
    bottom_y = min(float(height), band_y + 10.0)  # include the tick ruler

    # Validate width >= 90% of frame width.
    roi_width = right_x - left_x
    if roi_width < width * 0.9:
        deficit = width * 0.9 - roi_width
        left_x = max(0.0, left_x - deficit / 2)
        right_x = min(float(width), right_x + deficit / 2)

    # Validate height is 30%-70% of frame height.
    roi_height = bottom_y - top_y
    min_height = height * 0.3
    max_height = height * 0.7
    if roi_height < min_height:
        top_y = bottom_y - min_height
    elif roi_height > max_height:
        top_y = bottom_y - max_height
    top_y = max(0.0, top_y)

    if right_x <= left_x or bottom_y <= top_y:
        return None

    logger.debug(
        "resolve_cine_segment_roi_xyxy: Doppler ROI from ticks (conf=%.2f, ticks=%d, roi=(%.0f,%.0f,%.0f,%.0f))",
        tick_result.confidence,
        len(tick_positions),
        left_x,
        top_y,
        right_x,
        bottom_y,
    )
    return (left_x, top_y, right_x, bottom_y)


def resolve_dicom_segment_roi_xyxy(
    frame: np.ndarray,
    instance_path: Path | None,
) -> tuple[float, float, float, float] | None:
    """DICOM SequenceOfUltrasoundRegions first, then heuristic fallback.

    No sector trim applied — SequenceOfUltrasoundRegions bounds are already
    correct for DICOM; trimming risks cutting the LV apex.

    Priority:
    1. B-mode panel bounds (this ROI feeds ONNX LV segmentation).
    2. Doppler panel bounds (frames with spectral content only).
    3. Cine fallback (tick detection for Doppler, None for B-mode).
    """
    if instance_path is not None:
        layout = try_parse_from_path(instance_path)
        if layout is not None:
            # Prefer B-mode panel bounds: this ROI is used for LV segmentation.
            # On split-screen files (B-mode + Doppler) the Doppler panel would
            # feed the spectrum to EchoNet instead of the chamber.
            if layout.b_mode is not None:
                bounds = layout.b_mode.bounds
                return _bounds_to_xyxy(bounds.x0, bounds.y0, bounds.width, bounds.height)
            if layout.doppler is not None:
                bounds = layout.doppler.bounds
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
