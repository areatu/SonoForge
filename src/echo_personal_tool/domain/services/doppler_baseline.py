"""Auto-detect Doppler zero-velocity baseline within a spectrogram ROI."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi


def detect_baseline_line_y(
    grayscale: np.ndarray,
    roi: DopplerSpectrogramRoi,
) -> float | None:
    """Return plot Y of the baseline line, or None when no confident line.

    Mirrors how a sonographer finds the baseline by eye: scan the ROI for a
    *thin* (a few pixels) horizontal band of a single, uniform color that
    stretches across most of the spectrogram width (colored, gray, or white
    — vendor-independent, no specific color is assumed). Returns the plot Y
    of the band center, or None when no such line is found.
    """
    if grayscale.ndim not in (2, 3):
        return None

    height, width = grayscale.shape[:2]
    x0 = int(max(0, min(roi.x0, width - 1)))
    y0 = int(max(0, min(roi.y0, height - 1)))
    x1 = int(max(x0 + 1, min(roi.x1, width)))
    y1 = int(max(y0 + 1, min(roi.y1, height)))

    patch = grayscale[y0:y1, x0:x1]
    if patch.size == 0:
        return None
    if patch.ndim == 3:
        patch = patch[..., :3].astype(np.float64)
    else:
        patch = patch.astype(np.float64)[..., None]

    n_rows, n_cols = patch.shape[:2]
    if n_rows < 3 or n_cols < 4:
        return None

    tolerance = 25.0
    coverage = np.empty(n_rows)
    dominant_mag = np.empty(n_rows)
    for r in range(n_rows):
        row = patch[r]
        dominant = np.median(row, axis=0)
        match = np.all(np.abs(row - dominant) <= tolerance, axis=1)
        coverage[r] = float(match.mean())
        dominant_mag[r] = float(np.mean(dominant))

    # Line rows: a single uniform (non-black) color covers most of the width.
    # The cutoff is relative to the strongest row (with a 0.5 floor) because
    # line strength varies across vendors/frames: weak lines reach ~0.63
    # coverage (IM_0252), strong ones ~0.95. The line is always well above
    # the multi-color signal rows (typically <0.4), so a relative cutoff
    # separates them reliably without a brittle absolute threshold.
    bright = dominant_mag > 25.0
    peak = float(np.max(coverage[bright])) if np.any(bright) else 0.0
    cutoff = max(0.5, 0.75 * peak)
    row_candidate = (coverage > cutoff) & bright
    thin_limit = max(4, min(8, int(0.04 * n_rows)))

    best_coverage = 0.0
    best_center: float | None = None
    start = 0
    while start < n_rows:
        if not row_candidate[start]:
            start += 1
            continue
        end = start
        while end + 1 < n_rows and row_candidate[end + 1]:
            end += 1
        band_height = end - start + 1
        if band_height <= thin_limit:
            band_cover = float(np.mean(coverage[start : end + 1]))
            if band_cover > best_coverage:
                best_coverage = band_cover
                best_center = y0 + (start + end) / 2.0 + 0.5
        start = end + 1

    if best_center is not None and best_coverage >= 0.5:
        return best_center
    return None


def detect_baseline_y(grayscale: np.ndarray, roi: DopplerSpectrogramRoi) -> float:
    """Return plot Y of the Doppler baseline within the ROI.

    Accepts 2D grayscale or 3D RGB/BGR frames. Strategy:
    1. Line detection first (the operator's primary visual cue): a thin
       horizontal band of one uniform color stretching across the width,
       wherever it sits (even at the ROI edge).
    2. Otherwise, intensity fallback: the row with the lowest smoothed mean
       intensity *inside the convex hull of signal rows*. This handles a
       black gap at the baseline (signal both above and below), signal on
       one side only (baseline at the signal edge), or no black zone at all
       (valley between two lobes). Rows outside the signal hull are pure
       background, so a dead zone is not mistaken for the baseline.
    """
    line_y = detect_baseline_line_y(grayscale, roi)
    if line_y is not None:
        return line_y

    if grayscale.ndim == 3:
        grayscale = np.mean(grayscale[..., :3].astype(np.float32), axis=2)
    if grayscale.ndim != 2:
        return roi.y0 + roi.height / 2.0

    height, width = grayscale.shape[:2]
    x0 = int(max(0, min(roi.x0, width - 1)))
    y0 = int(max(0, min(roi.y0, height - 1)))
    x1 = int(max(x0 + 1, min(roi.x1, width)))
    y1 = int(max(y0 + 1, min(roi.y1, height)))

    patch = grayscale[y0:y1, x0:x1].astype(np.float64)
    if patch.size == 0:
        return roi.y0 + roi.height / 2.0

    row_mean = np.mean(patch, axis=1)
    row_max = np.max(patch, axis=1)
    if row_mean.size == 0:
        return roi.y0 + roi.height / 2.0

    global_max = float(np.max(patch))
    signal_threshold = max(4.0, 0.12 * global_max)
    signal = row_max > signal_threshold
    if not signal.any():
        # No signal content at all → fall back to ROI center.
        return roi.y0 + roi.height / 2.0

    first = int(np.argmax(signal))
    last = height - 1 - int(np.argmax(signal[::-1]))
    if last < first:
        return roi.y0 + roi.height / 2.0

    # Smooth the row-mean profile with edge-replicated padding so boundary
    # rows are not artificially darker than the interior.
    padded = np.concatenate(([row_mean[0]], row_mean, [row_mean[-1]]))
    smoothed = np.convolve(padded, np.ones(3) / 3, mode="valid")

    band = smoothed[first : last + 1]
    idx = first + int(np.argmin(band))

    # One-sided spectrum: signal occupies one edge of the ROI. The baseline
    # is the signal boundary facing the *larger* empty region, not the spot
    # where the profile happens to dip at the opposite (ramp-up) edge.
    empty_above = first
    empty_below = height - 1 - last
    if idx <= first + 2 and empty_below > empty_above:
        idx = last
    elif idx >= last - 2 and empty_above > empty_below:
        idx = first

    return float(y0 + idx) + 0.5
