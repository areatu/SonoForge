"""Detect tick marks on the Doppler velocity scale strip (right of spectrogram)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi


def _cluster_to_centers(rows: np.ndarray, min_distance: float) -> list[float]:
    """Cluster adjacent bright rows and return the center of each cluster."""
    if len(rows) == 0:
        return []
    sorted_rows = np.sort(rows)
    clusters: list[list[float]] = [[float(sorted_rows[0])]]
    for r in sorted_rows[1:]:
        if r - clusters[-1][-1] <= min_distance:
            clusters[-1].append(float(r))
        else:
            clusters.append([float(r)])
    return [sum(c) / len(c) for c in clusters]


def _detect_ticks_at_x(
    gray: np.ndarray,
    x_center: int,
    search_half_width: int,
    y0: int,
    y1: int,
    min_tick_spacing_px: int,
) -> list[float]:
    """Detect tick row indices (local to y0) for columns around *x_center*."""
    h, w = gray.shape
    x0 = max(0, x_center - search_half_width)
    x1 = min(w, x_center + search_half_width + 1)
    if x1 <= x0:
        return []
    sub = gray[y0:y1, x0:x1]
    if sub.size == 0:
        return []
    col_max = np.max(sub, axis=1)
    row_median = np.median(col_max)
    row_std = np.std(col_max)
    if row_std < 2.0:
        return []
    bright_threshold = max(row_median + 1.5 * row_std, 30.0)
    bright_rows = np.where(col_max > bright_threshold)[0]
    if len(bright_rows) == 0:
        return []
    candidates = _cluster_to_centers(bright_rows, min_tick_spacing_px)
    margin_top = int(sub.shape[0] * 0.04)
    margin_bottom = int(sub.shape[0] * 0.04)
    candidates = [c for c in candidates if margin_top <= c < sub.shape[0] - margin_bottom]
    return sorted(float(c) for c in candidates)


def _scan_columns_for_ticks(
    gray: np.ndarray,
    x_lo: int,
    x_hi: int,
    step_px: int,
    search_half_width: int,
    y0: int,
    y1: int,
    min_tick_spacing_px: int,
) -> tuple[list[float], int]:
    """Scan columns in [x_lo, x_hi) and return (best_tick_rows, best_x).

    The first column that achieves the maximum tick count is chosen,
    which tends to be closest to the tick marks on the left edge.
    """
    best_ticks: list[float] = []
    best_x = x_lo
    h, w = gray.shape
    for x_center in range(x_lo, min(x_hi, w), step_px):
        ticks = _detect_ticks_at_x(gray, x_center, search_half_width, y0, y1, min_tick_spacing_px)
        ticks = [float(t) for t in ticks]
        if len(ticks) > len(best_ticks):
            best_ticks = ticks
            best_x = x_center
    return best_ticks, best_x


def find_best_scale_column(
    frame: np.ndarray,
    roi: DopplerSpectrogramRoi,
    search_width_px: int = 100,
    step_px: int = 5,
    search_half_width: int = 15,
    min_tick_spacing_px: int = 5,
    baseline_y: float | None = None,
) -> list[float]:
    """Scan columns right of *roi* and return ticks from the best column.

    Mirrors the B-mode ``find_best_scale_column`` approach: tries multiple
    x-centres and picks the column with the most detected ticks, improving
    robustness when the scale strip position varies across frame types.

    When *baseline_y* is given, the y-search is restricted to the region
    around the baseline (±roi.height), excluding the B-mode area at the top
    of the frame.  When the ROI-based search finds fewer than 3 ticks, a
    fallback search of the full frame's right strip (80–95 % of width) is
    attempted, mirroring the B-mode strategy so detection works even when
    the ROI is the full frame.
    """
    if frame.ndim == 3:
        gray = np.mean(frame, axis=2).astype(np.float32)
    else:
        gray = frame.astype(np.float32)

    h, w = gray.shape

    y0 = max(0, int(roi.y0))
    y1 = min(h, int(roi.y0 + roi.height))
    if baseline_y is not None:
        # Restrict y-range to ±0.4*frame_height around the baseline,
        # excluding the B-mode area at the top of the frame.
        half = h * 0.4
        y0 = max(0, int(baseline_y - half))
        y1 = min(h, int(baseline_y + half))

    x_start = min(int(roi.x1), w - 1)
    x_end = min(x_start + search_width_px, w)

    best_ticks, _ = _scan_columns_for_ticks(
        gray,
        x_start,
        x_end,
        step_px,
        search_half_width,
        y0,
        y1,
        min_tick_spacing_px,
    )

    # Fallback: search the right strip of the full frame (like B-mode),
    # restricted to the y-range around the baseline.  This handles the case
    # where the ROI is the full frame (roi.x1 == frame width) and the
    # scale strip sits to the left of the right edge.
    if len(best_ticks) < 3:
        fb_y0 = y0
        fb_y1 = y1
        fb_ticks, _ = _scan_columns_for_ticks(
            gray,
            int(w * 0.80),
            int(w * 0.95),
            step_px,
            search_half_width,
            fb_y0,
            fb_y1,
            min_tick_spacing_px,
        )
        if len(fb_ticks) > len(best_ticks):
            best_ticks = fb_ticks

    return sorted(float(y0 + c) for c in best_ticks)


def detect_velocity_scale_ticks(
    frame: np.ndarray,
    *,
    roi: DopplerSpectrogramRoi,
    strip_width_px: int = 40,
    min_tick_spacing_px: int = 5,
    baseline_y: float | None = None,
) -> list[float]:
    """Detect y-positions of velocity-scale tick marks in the strip right of *roi*.

    Returns sorted y-positions (frame coordinates). Empty list when none found.
    Scans a range of columns right of the ROI and picks the best, matching the
    B-mode ``find_scale_ticks`` pattern for robustness across frame types.
    """
    return find_best_scale_column(
        frame,
        roi,
        search_width_px=strip_width_px if strip_width_px > 0 else 100,
        search_half_width=max(1, strip_width_px // 2) if strip_width_px > 0 else 15,
        min_tick_spacing_px=min_tick_spacing_px,
        baseline_y=baseline_y,
    )


def find_scale_strip_x(
    frame: np.ndarray,
    *,
    roi: DopplerSpectrogramRoi,
    baseline_y: float | None = None,
    search_half_width: int = 15,
    min_tick_spacing_px: int = 5,
) -> int:
    """Return the x-column of the best scale strip (right of *roi* or full-frame).

    Tries columns starting at *roi.x1* for ~120 px; if fewer than 3 ticks are
    found, falls back to scanning the right strip of the full frame (80–95 %
    of width).  When *baseline_y* is given the y-range is restricted to
    ±roi.height around it, excluding the B-mode area at the top of the frame.
    """
    if frame.ndim == 3:
        gray = np.mean(frame, axis=2).astype(np.float32)
    else:
        gray = frame.astype(np.float32)

    h, w = gray.shape

    y0 = max(0, int(roi.y0))
    y1 = min(h, int(roi.y0 + roi.height))
    if baseline_y is not None:
        half = h * 0.4
        y0 = max(0, int(baseline_y - half))
        y1 = min(h, int(baseline_y + half))

    x_start = min(int(roi.x1), w - 1)
    x_end = min(x_start + 120, w)

    _, best_x = _scan_columns_for_ticks(
        gray,
        x_start,
        x_end,
        5,
        search_half_width,
        y0,
        y1,
        min_tick_spacing_px,
    )

    if best_x < x_start + 1:
        # Fallback: search full frame right strip
        ticks, best_x = _scan_columns_for_ticks(
            gray,
            int(w * 0.80),
            int(w * 0.95),
            5,
            search_half_width,
            y0,
            y1,
            min_tick_spacing_px,
        )
        if len(ticks) >= 3:
            return best_x

    return best_x
