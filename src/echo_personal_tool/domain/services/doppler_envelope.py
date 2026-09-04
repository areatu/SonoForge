"""Semi-automatic Doppler spectral envelope tracing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi


@dataclass(frozen=True)
class EnvelopePreset:
    """Threshold/smoothing parameters for a trace sensitivity preset."""

    k: float
    median_window: int
    savgol_window: int
    savgol_polyorder: int
    noise_frac: float = 0.15
    min_signal_columns: int = 5


VESSEL_ENVELOPE_PRESETS: dict[str, EnvelopePreset] = {
    "low": EnvelopePreset(k=2.5, median_window=3, savgol_window=5, savgol_polyorder=2, min_signal_columns=3),
    "normal": EnvelopePreset(k=3.8, median_window=5, savgol_window=7, savgol_polyorder=2),
    "high": EnvelopePreset(k=5.5, median_window=7, savgol_window=7, savgol_polyorder=2),
}

_MIN_SIGNAL_FRACTION = 0.12


def _envelope_row_in_column(
    column: np.ndarray,
    baseline_row: int,
    *,
    above_baseline: bool,
    min_intensity: float,
) -> int | None:
    if above_baseline:
        end = baseline_row + 1 if baseline_row >= 0 else 1
        search = column[:end]
    else:
        search = column[baseline_row:] if baseline_row < column.size else column[-1:]

    if search.size == 0:
        return None

    peak = float(search.max())
    if peak < min_intensity:
        return None

    row = int(np.argmax(search))
    if not above_baseline:
        row = baseline_row + row
    return row


def _active_column_range(
    patch: np.ndarray,
    baseline_row: int,
    *,
    above_baseline: bool,
    min_intensity: float,
) -> tuple[int, int] | None:
    active: list[int] = []
    for col in range(patch.shape[1]):
        if (
            _envelope_row_in_column(
                patch[:, col],
                baseline_row,
                above_baseline=above_baseline,
                min_intensity=min_intensity,
            )
            is not None
        ):
            active.append(col)
    if not active:
        return None
    return active[0], active[-1]


def trace_envelope(
    grayscale: np.ndarray,
    roi: DopplerSpectrogramRoi,
    baseline_y_px: float,
    *,
    num_samples: int = 32,
    above_baseline: bool = True,
    start_at_baseline: bool = True,
) -> tuple[tuple[float, float], ...]:
    """Column-wise intensity ridge inside spectral flow; plot coordinates (x, y).

    Skips empty margin columns at ROI edges and can anchor the first point on the
    baseline at spectral onset (start of VTI trace).
    """
    if grayscale.ndim != 2 or num_samples < 2:
        return ()

    height, width = grayscale.shape[:2]
    x0 = int(max(0, min(roi.x0, width - 1)))
    y0 = int(max(0, min(roi.y0, height - 1)))
    x1 = int(max(x0 + 1, min(roi.x1, width)))
    y1 = int(max(y0 + 1, min(roi.y1, height)))

    patch = grayscale[y0:y1, x0:x1].astype(np.float64)
    if patch.size == 0:
        return ()

    baseline_row = int(round(baseline_y_px - y0))
    baseline_row = max(0, min(baseline_row, patch.shape[0] - 1))
    baseline_plot_y = float(baseline_y_px)

    min_intensity = max(12.0, float(patch.max()) * 0.08)
    column_range = _active_column_range(
        patch,
        baseline_row,
        above_baseline=above_baseline,
        min_intensity=min_intensity,
    )
    if column_range is None:
        return ()

    col_start, col_end = column_range
    if col_end <= col_start:
        return ()

    cols = np.linspace(col_start, col_end, num=num_samples, dtype=int)
    points: list[tuple[float, float]] = []

    if start_at_baseline:
        onset_x = float(x0 + col_start)
        points.append((onset_x, baseline_plot_y))

    for col in cols:
        row = _envelope_row_in_column(
            patch[:, col],
            baseline_row,
            above_baseline=above_baseline,
            min_intensity=min_intensity,
        )
        if row is None:
            continue
        plot_x = float(x0 + col)
        plot_y = float(y0 + row) + 0.5
        if points and abs(plot_x - points[-1][0]) < 0.5 and abs(plot_y - points[-1][1]) < 0.5:
            continue
        points.append((plot_x, plot_y))

    if len(points) < 2:
        return ()
    return tuple(points)


def trace_envelope_above_baseline(trace_label: str) -> bool:
    """TR/PR regurgitation envelopes are usually below the baseline."""
    normalized = trace_label.strip().upper()
    return normalized not in {"VTI TR", "VTI PR", "TR", "PR"}


def _extract_side(
    patch: np.ndarray,
    baseline_row: int,
    cfg: EnvelopePreset,
    *,
    above: bool,
    x0: int,
    y0: int,
) -> tuple[tuple[tuple[float, float], ...], float] | None:
    """Trace the max-velocity envelope on one side of the baseline.

    Column-wise "first bin above threshold" scan from the highest frequency
    toward the baseline. The threshold is estimated from the highest-frequency
    strip of that half (median/MAD keeps it robust to bright on-screen text
    glyphs that often sit in the ROI edge strip). Gaps are linearly
    interpolated and the result smoothed with a median filter and
    Savitzky-Golay. Returns ``(points, score)`` in plot coordinates
    (x_plot, y_plot) plus a signal score, or ``None`` when this side has no
    reliable envelope. The baseline row itself is included so structures are
    anchored at the baseline on either side.
    """
    if above:
        if baseline_row < 2:
            return None
        pos = patch[:baseline_row, :]
        noise_rows = max(1, int(pos.shape[0] * cfg.noise_frac))
        noise = pos[:noise_rows, :]
        anchor_row = -1
    else:
        if patch.shape[0] - baseline_row - 1 < 2:
            return None
        pos = patch[baseline_row + 1 :, :]
        noise_rows = max(1, int(pos.shape[0] * cfg.noise_frac))
        noise = pos[-noise_rows:, :]
        anchor_row = 0

    noise_median = float(np.median(noise))
    noise_mad = float(np.median(np.abs(noise - noise_median)))
    threshold = noise_median + cfg.k * noise_mad
    peak = float(pos.max())
    if peak <= threshold:
        return None
    # Floor so a clean (all-black) edge strip does not collapse the threshold
    # to zero and let faint speckle into the trace mask.
    # Use adaptive floor: for weak signals (peak < 3x threshold), lower the
    # floor to avoid rejecting valid but faint envelope pixels.
    signal_strength = peak / max(threshold, 1.0)
    if signal_strength < 3.0:
        floor_frac = max(0.03, _MIN_SIGNAL_FRACTION * signal_strength / 3.0)
    else:
        floor_frac = _MIN_SIGNAL_FRACTION
    threshold = max(threshold, peak * floor_frac)
    threshold = min(threshold, peak * 0.9)

    signal = pos > threshold
    from scipy.ndimage import label

    labels, num_labels = label(signal, structure=np.ones((3, 3), dtype=int))
    if num_labels == 0:
        return None
    # Keep only the structures anchored at the baseline: the spectral flow.
    # Disconnected artifacts (text, annotations) are discarded.
    baseline_labels = {int(lb) for lb in np.unique(labels[anchor_row, :]) if lb != 0}
    counts = np.bincount(labels.ravel())
    counts[0] = 0
    if baseline_labels:
        baseline_area = float(sum(counts[int(lb)] for lb in baseline_labels))
        largest_area = float(counts.max())
        if baseline_area >= _MIN_SIGNAL_FRACTION * largest_area:
            keep = np.isin(labels, tuple(baseline_labels))
        else:
            # A dark zero-velocity window can separate the real flow from the
            # baseline, leaving only a thin speckle line anchored there. Trace
            # the largest component (the actual flow) in that case.
            keep = labels == int(np.argmax(counts))
    else:
        # Nothing reaches the baseline: fall back to the largest component so a
        # thin envelope curve with a dark interior is still traced.
        keep = labels == int(np.argmax(counts))

    rows = np.full(pos.shape[1], -1.0, dtype=np.float64)
    energy = 0.0
    for c in range(pos.shape[1]):
        col_mask = keep[:, c]
        if np.any(col_mask):
            if above:
                rows[c] = int(np.argmax(col_mask))
            else:
                rows[c] = int(col_mask.size - 1 - int(np.argmax(col_mask[::-1])))
            energy += float(pos[col_mask, c].max())

    valid_mask = rows >= 0
    valid_count = int(valid_mask.sum())
    if valid_count < cfg.min_signal_columns:
        return None
    c0 = int(np.argmax(valid_mask))
    c1 = int(valid_mask.size - 1 - np.argmax(valid_mask[::-1]))
    span = c1 - c0 + 1
    # Continuity: fraction of valid columns in the active range.  A smooth
    # envelope with few gaps scores higher than a fragmented one with the
    # same total energy.
    continuity = valid_count / span if span > 0 else 0.0

    cols = np.arange(c0, c1 + 1, dtype=np.float64)
    band = rows[c0 : c1 + 1]
    band_valid = band >= 0
    y_arr = np.interp(cols, cols[band_valid], band[band_valid])

    if cfg.median_window > 1:
        from scipy.ndimage import median_filter

        y_arr = median_filter(y_arr, size=cfg.median_window, mode="nearest")

    swin = cfg.savgol_window
    if swin < 3:
        swin = 3
    if swin % 2 == 0:
        swin += 1
    if y_arr.size >= swin:
        from scipy.signal import savgol_filter

        y_arr = savgol_filter(
            y_arr,
            window_length=swin,
            polyorder=min(cfg.savgol_polyorder, swin - 1),
            mode="interp",
        )

    points: list[tuple[float, float]] = []
    prev: tuple[float, float] | None = None
    for c, r in zip(cols, y_arr):
        px = float(x0 + c)
        py = float(y0 + (r if above else baseline_row + 1 + r)) + 0.5
        if prev is not None and abs(px - prev[0]) < 0.5 and abs(py - prev[1]) < 0.5:
            continue
        points.append((px, py))
        prev = (px, py)
    if len(points) < 2:
        return None
    # Score combines signal energy and continuity so a smooth envelope with
    # few gaps outranks a fragmented one even when total energy is similar.
    score = energy * (0.5 + 0.5 * continuity)
    return tuple(points), score


def extract_doppler_envelope(
    grayscale: np.ndarray,
    roi: DopplerSpectrogramRoi,
    baseline_y_px: float,
    *,
    preset: str = "normal",
    force_direction: str | None = None,
) -> tuple[tuple[float, float], ...]:
    """Extract the max-velocity envelope on the side with the strongest flow.

    Traces both sides of the baseline and returns the side with the larger
    signal footprint (more active columns), so arterial flow above the baseline
    and venous/TR/PR flow below it are both handled automatically. Gaps are
    linearly interpolated and the result smoothed with a median filter and
    Savitzky-Golay. Returns plot coordinates (x_plot, y_plot).

    When *force_direction* is ``"up"`` only the above-baseline side is
    returned; when ``"down"`` only the below-baseline side is returned.
    ``None`` (default) picks the side with the strongest signal.
    """
    if grayscale.ndim != 2:
        return ()
    cfg = VESSEL_ENVELOPE_PRESETS.get(preset, VESSEL_ENVELOPE_PRESETS["normal"])

    height, width = grayscale.shape[:2]
    x0 = int(max(0, min(roi.x0, width - 1)))
    y0 = int(max(0, min(roi.y0, height - 1)))
    x1 = int(max(x0 + 1, min(roi.x1, width)))
    y1 = int(max(y0 + 1, min(roi.y1, height)))

    patch = grayscale[y0:y1, x0:x1].astype(np.float64)
    if patch.size == 0:
        return ()

    baseline_row = int(round(baseline_y_px - y0))
    baseline_row = max(0, min(baseline_row, patch.shape[0] - 1))

    if force_direction == "up":
        above = _extract_side(patch, baseline_row, cfg, above=True, x0=x0, y0=y0)
        return above[0] if above is not None else ()
    if force_direction == "down":
        below = _extract_side(patch, baseline_row, cfg, above=False, x0=x0, y0=y0)
        return below[0] if below is not None else ()

    above = _extract_side(patch, baseline_row, cfg, above=True, x0=x0, y0=y0)
    below = _extract_side(patch, baseline_row, cfg, above=False, x0=x0, y0=y0)

    if above is None and below is None:
        return ()
    if below is None:
        return above[0]
    if above is None:
        return below[0]
    return above[0] if above[1] >= below[1] else below[0]
