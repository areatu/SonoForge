"""Automatic depth calibration from B-mode scale ticks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.services.depth_scale_detector import find_scale_ticks
from echo_personal_tool.domain.services.pixel_spacing_resolver import (
    spacing_from_known_distance,
)


@dataclass(frozen=True)
class AutoCalibrationResult:
    spacing: tuple[float, float]
    tick_count: int
    span_px: float
    confidence: float


def try_auto_depth_calibration(
    frame: np.ndarray,
    *,
    cm_per_major_tick: float = 1.0,
    min_ticks: int = 3,
    max_spacing_cv: float = 0.5,
    min_span_fraction: float = 0.15,
) -> AutoCalibrationResult | None:
    ticks = find_scale_ticks(frame)
    if len(ticks) < min_ticks:
        return None

    h = frame.shape[0]
    span_px = ticks[-1] - ticks[0]
    if span_px / h < min_span_fraction:
        return None

    spacings = np.array([ticks[i + 1] - ticks[i] for i in range(len(ticks) - 1)])

    major_spacing = _infer_major_spacing(spacings)
    if major_spacing is None:
        return None

    close_mask = (spacings > major_spacing * 0.5) & (spacings < major_spacing * 2.0)
    close_spacings = spacings[close_mask]
    if len(close_spacings) < 2:
        return None

    cv = float(np.std(close_spacings) / np.mean(close_spacings))
    if cv > max_spacing_cv:
        return None

    pixel_span = ticks[-1] - ticks[0]
    n_major_intervals = int(round(pixel_span / major_spacing))
    if n_major_intervals < 1:
        return None
    known_mm = n_major_intervals * cm_per_major_tick * 10.0
    spacing = spacing_from_known_distance(pixel_span, known_mm)

    tick_score = min(len(close_spacings) / 10.0, 1.0)
    uniformity_score = max(0.0, 1.0 - cv / max_spacing_cv)
    confidence = 0.5 * tick_score + 0.5 * uniformity_score

    return AutoCalibrationResult(
        spacing=spacing,
        tick_count=len(close_spacings),
        span_px=pixel_span,
        confidence=confidence,
    )


def _infer_major_spacing(spacings: np.ndarray) -> float | None:
    if len(spacings) == 0:
        return None
    sorted_s = np.sort(spacings)
    median_s = float(np.median(sorted_s))
    if median_s <= 0:
        return None
    close_to_median = sorted_s[(sorted_s > median_s * 0.5) & (sorted_s < median_s * 2.0)]
    if len(close_to_median) >= len(spacings) * 0.4:
        return median_s
    q75 = float(np.percentile(sorted_s, 75))
    q25 = float(np.percentile(sorted_s, 25))
    if q75 > q25 * 1.5:
        return q75
    return median_s
