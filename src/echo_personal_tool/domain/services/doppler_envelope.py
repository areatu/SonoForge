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
    "low": EnvelopePreset(k=2.5, median_window=3, savgol_window=5, savgol_polyorder=2),
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


def extract_doppler_envelope(
    grayscale: np.ndarray,
    roi: DopplerSpectrogramRoi,
    baseline_y_px: float,
    *,
    preset: str = "normal",
) -> tuple[tuple[float, float], ...]:
    """Extract the max-velocity envelope above the baseline.

    Column-wise "first bin above threshold" scan from the highest frequency
    toward the baseline. The threshold is estimated from the highest-frequency
    region of the positive half (mean + k*std per preset). Gaps are linearly
    interpolated and the result smoothed with a median filter and
    Savitzky-Golay. Returns plot coordinates (x_plot, y_plot).
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
    if baseline_row < 2:
        return ()

    pos = patch[: baseline_row + 1, :]
    noise_rows = max(1, int(pos.shape[0] * cfg.noise_frac))
    noise = pos[:noise_rows, :]
    # Median/MAD keeps the threshold robust to bright on-screen text glyphs
    # (probe type, frequency, mode) that often sit in the top strip of the ROI.
    noise_median = float(np.median(noise))
    noise_mad = float(np.median(np.abs(noise - noise_median)))
    threshold = noise_median + cfg.k * noise_mad
    peak = float(pos.max())
    if peak <= threshold:
        return ()
    # Floor so a clean (all-black) top strip does not collapse the threshold
    # to zero and let faint speckle into the trace mask.
    threshold = max(threshold, peak * _MIN_SIGNAL_FRACTION)
    threshold = min(threshold, peak * 0.9)

    above = pos > threshold
    from scipy.ndimage import label

    labels, num_labels = label(above, structure=np.ones((3, 3), dtype=int))
    if num_labels == 0:
        return ()
    # Keep only the structures anchored at the baseline: the spectral flow.
    # Disconnected artifacts (text, annotations) are discarded.
    baseline_labels = {int(lb) for lb in np.unique(labels[-1, :]) if lb != 0}
    if baseline_labels:
        keep = np.isin(labels, tuple(baseline_labels))
    else:
        # Nothing reaches the baseline: fall back to the largest component so a
        # thin envelope curve with a dark interior is still traced.
        counts = np.bincount(labels.ravel())
        counts[0] = 0
        keep = labels == int(np.argmax(counts))

    rows = np.full(pos.shape[1], -1.0, dtype=np.float64)
    for c in range(pos.shape[1]):
        col_mask = keep[:, c]
        if np.any(col_mask):
            rows[c] = int(np.argmax(col_mask))

    valid_mask = rows >= 0
    if int(valid_mask.sum()) < cfg.min_signal_columns:
        return ()
    c0 = int(np.argmax(valid_mask))
    c1 = int(valid_mask.size - 1 - np.argmax(valid_mask[::-1]))

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
        py = float(y0 + r) + 0.5
        if prev is not None and abs(px - prev[0]) < 0.5 and abs(py - prev[1]) < 0.5:
            continue
        points.append((px, py))
        prev = (px, py)
    if len(points) < 2:
        return ()
    return tuple(points)
