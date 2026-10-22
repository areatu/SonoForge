"""Cardiac cycle detection without ECG: FFT-based HR and ED/ES auto-detection."""

from __future__ import annotations

import cv2
import numpy as np
from scipy.interpolate import UnivariateSpline

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    SpeckleConfig,
    TrackingKernel,
    TrackingResult,
)


def estimate_heart_rate_fft(
    frames: np.ndarray,
    roi_mask: np.ndarray | None = None,
    fps: float = 30.0,
) -> float:
    """Estimate heart rate from mean myocardial intensity over time.

    Uses FFT on the temporal intensity signal to find dominant frequency.

    Args:
        frames: (N, H, W) grayscale CINE frames.
        roi_mask: optional (H, W) binary mask of myocardial region.
        fps: frame rate in frames per second.

    Returns:
        Heart rate in BPM.
    """
    n_frames = frames.shape[0]
    if n_frames < 8:
        return 0.0

    if roi_mask is not None:
        signal = np.array([frames[i][roi_mask > 0].mean() for i in range(n_frames)])
    else:
        signal = np.array([frames[i].mean() for i in range(n_frames)])

    signal = signal - signal.mean()
    window = np.hanning(n_frames)
    fft_result = np.fft.rfft(signal * window)
    freqs = np.fft.rfftfreq(n_frames, d=1.0 / fps)

    min_bpm, max_bpm = 40.0, 200.0
    min_freq = min_bpm / 60.0
    max_freq = max_bpm / 60.0

    mask = (freqs >= min_freq) & (freqs <= max_freq)
    if not mask.any():
        return 0.0

    magnitudes = np.abs(fft_result)
    magnitudes[~mask] = 0
    peak_freq = freqs[np.argmax(magnitudes)]

    return float(peak_freq * 60.0)


def _shoelace_area(
    positions: np.ndarray,
    ma_chord: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> float:
    """Shoelace area from point array.

    For open arcs, closes via MA chord (lateral → septal) if provided,
    otherwise closes last → first point.

    Args:
        positions: (N, 2) point array (col, row).
        ma_chord: optional ((septal_x, septal_y), (lateral_x, lateral_y)).

    Returns:
        Area in pixel² units.
    """
    if len(positions) < 3:
        return 0.0

    pts = list(positions)
    if ma_chord is not None:
        septal, lateral = ma_chord
        pts.append(lateral)
        pts.append(septal)
    else:
        pts.append(pts[0])

    area = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _estimate_lv_area_proxy(frame: np.ndarray, zone: MyocardialZone) -> float:
    """Mean intensity inside bounding box of endo contour as area proxy."""
    if frame.ndim != 2 or zone.endo_points.size == 0:
        return 0.0

    endo = np.asarray(zone.endo_points, dtype=np.float64)
    h, w = frame.shape
    x0 = int(np.clip(np.floor(np.min(endo[:, 0])), 0, w - 1))
    x1 = int(np.clip(np.ceil(np.max(endo[:, 0])), 0, w - 1))
    y0 = int(np.clip(np.floor(np.min(endo[:, 1])), 0, h - 1))
    y1 = int(np.clip(np.ceil(np.max(endo[:, 1])), 0, h - 1))
    if x1 <= x0 or y1 <= y0:
        return 0.0

    roi = frame[y0 : y1 + 1, x0 : x1 + 1]
    return float(np.mean(roi)) if roi.size > 0 else 0.0


def detect_ed_es_from_frames(
    frames: np.ndarray,
    zone: MyocardialZone,
    config: SpeckleConfig,
) -> tuple[int, int]:
    """Pre-tracking ED/ES with cubic/UnivariateSpline smoothed area curve."""
    n_frames = int(frames.shape[0]) if frames.ndim >= 3 else 0
    if n_frames < 3:
        return (0, min(1, max(0, n_frames - 1)))

    curve = np.array(
        [_estimate_lv_area_proxy(frames[i], zone) for i in range(n_frames)],
        dtype=np.float64,
    )
    x = np.arange(n_frames, dtype=np.float64)

    if n_frames >= 4 and np.ptp(curve) > 1e-8:
        k = min(3, n_frames - 1)
        smooth_s = max(float(config.temporal_smoothing) * n_frames * 0.1, 0.0)
        spline = UnivariateSpline(x, curve, s=smooth_s, k=k)
        smooth_curve = spline(x)
    else:
        smooth_curve = curve

    ed_index = int(np.argmax(smooth_curve))
    es_index = int(np.argmin(smooth_curve))
    if ed_index == es_index:
        es_index = (ed_index + max(1, n_frames // 3)) % n_frames
    return ed_index, es_index


def detect_cycle_boundaries(areas: np.ndarray, min_cycle_frames: int = 15) -> list[tuple[int, int]]:
    """Detect cardiac cycles from smoothed area signal.

    Returns cycles as inclusive (start, end) frame ranges where cycle starts are
    ED peaks (maxima) and each cycle ends one frame before the next ED.
    """
    signal = np.asarray(areas, dtype=np.float64).reshape(-1)
    n = int(signal.size)
    if n < max(3, min_cycle_frames + 1):
        return []

    if np.ptp(signal) <= 1e-8:
        return []

    window = int(max(3, min(9, (min_cycle_frames // 2) * 2 + 1)))
    smooth = np.convolve(signal, np.ones(window, dtype=np.float64) / window, mode="same")

    peak_candidates: list[int] = []
    edge_margin = max(1, window // 2)
    for i in range(max(1, edge_margin), min(n - 1, n - edge_margin - 1)):
        if smooth[i] >= smooth[i - 1] and smooth[i] > smooth[i + 1]:
            peak_candidates.append(i)

    if len(peak_candidates) < 2:
        return []

    selected: list[int] = []
    for idx in sorted(peak_candidates, key=lambda j: smooth[j], reverse=True):
        if all(abs(idx - kept) >= min_cycle_frames for kept in selected):
            selected.append(idx)

    selected.sort()
    if len(selected) < 2:
        return []

    boundaries: list[tuple[int, int]] = []
    for start, next_start in zip(selected[:-1], selected[1:]):
        end = next_start - 1
        if end - start + 1 >= min_cycle_frames:
            boundaries.append((int(start), int(end)))
    return boundaries


def average_strain_curves(
    curves: list[np.ndarray],
    boundaries: list[tuple[int, int]],
    n_output_frames: int,
) -> np.ndarray:
    """Resample cycle strain curves to normalized phase and average."""
    if n_output_frames <= 0:
        return np.zeros(0, dtype=np.float64)

    resampled_cycles: list[np.ndarray] = []
    x_target = np.linspace(0.0, 1.0, int(n_output_frames))

    for curve in curves:
        arr = np.asarray(curve, dtype=np.float64).reshape(-1)
        for start, end in boundaries:
            s = int(start)
            e = int(end)
            if s < 0 or e >= arr.size or e <= s:
                continue
            segment = arr[s : e + 1]
            if segment.size < 2:
                continue
            x_src = np.linspace(0.0, 1.0, int(segment.size))
            resampled_cycles.append(np.interp(x_target, x_src, segment))

    if not resampled_cycles:
        return np.zeros(int(n_output_frames), dtype=np.float64)
    return np.mean(np.vstack(resampled_cycles), axis=0)


def build_myocardial_roi_mask(
    frame_shape: tuple[int, ...],
    zone: MyocardialZone,
) -> np.ndarray:
    """Boolean mask for HR estimation."""
    if len(frame_shape) < 2:
        return np.zeros((0, 0), dtype=bool)

    h, w = int(frame_shape[0]), int(frame_shape[1])
    if h <= 0 or w <= 0:
        return np.zeros((0, 0), dtype=bool)

    epi_mask = np.zeros((h, w), dtype=np.uint8)
    endo_mask = np.zeros((h, w), dtype=np.uint8)
    epi = np.round(zone.epi_points).astype(np.int32)
    endo = np.round(zone.endo_points).astype(np.int32)

    if len(epi) >= 3:
        cv2.fillPoly(epi_mask, [epi], 1)
    if len(endo) >= 3:
        cv2.fillPoly(endo_mask, [endo], 1)

    roi = (epi_mask > 0) & ~(endo_mask > 0)
    if not roi.any():
        roi = endo_mask > 0
    return roi


def auto_detect_ed_es(
    tracking_results: list[TrackingResult],
    kernels: list[TrackingKernel],
    pixel_spacing: tuple[float, float] = (1.0, 1.0),
) -> tuple[int, int]:
    """Auto-detect ED and ES frame indices from tissue motion.

    Uses Shoelace polygon area of endocardial contour at each frame.
    ED = maximum area, ES = minimum area.

    Args:
        tracking_results: per-frame tracking results.
        kernels: initial kernel positions.
        pixel_spacing: (row_spacing, column_spacing) in mm/pixel.

    Returns:
        (ed_index, es_index) frame indices.
    """
    n_frames = len(tracking_results) + 1
    if n_frames < 3:
        return (0, min(1, n_frames - 1))

    endo_kernels = [k for k in kernels if k.layer == "endo"]
    if len(endo_kernels) < 3:
        return (0, n_frames // 2)

    initial_positions = np.array([k.center for k in endo_kernels])

    ma_chord: tuple[tuple[float, float], tuple[float, float]] | None = None
    if len(initial_positions) >= 2:
        first = tuple(initial_positions[0].tolist())
        last = tuple(initial_positions[-1].tolist())
        ma_chord = (first, last)

    areas = np.zeros(n_frames)
    areas[0] = _shoelace_area(initial_positions, ma_chord)

    for t in range(1, n_frames):
        result = tracking_results[t - 1]
        endo_indices = [i for i, k in enumerate(kernels) if k.layer == "endo"]
        if len(endo_indices) == len(initial_positions):
            positions = result.kernel_positions[endo_indices]
        else:
            positions = initial_positions
        areas[t] = _shoelace_area(positions, ma_chord)

    ed_index = int(np.argmax(areas))
    es_index = int(np.argmin(areas))

    if ed_index == es_index:
        es_index = (ed_index + n_frames // 3) % n_frames

    return (ed_index, es_index)


def detect_cardiac_phases(
    frames: np.ndarray,
    tracking_results: list[TrackingResult],
    kernels: list[TrackingKernel],
    heart_rate_bpm: float,
    fps: float,
    pixel_spacing: tuple[float, float] = (1.0, 1.0),
) -> dict[str, int]:
    """Map frame indices to cardiac phase labels.

    Args:
        frames: (N, H, W) CINE frames.
        tracking_results: per-frame tracking results.
        kernels: initial kernel positions for ED/ES detection.
        heart_rate_bpm: estimated heart rate.
        fps: frame rate.
        pixel_spacing: (row_spacing, column_spacing) in mm/pixel.

    Returns:
        Dict mapping phase labels to frame indices.
    """
    n_frames = frames.shape[0]
    if heart_rate_bpm <= 0 or fps <= 0:
        return {"ED": 0, "ES": n_frames // 3}

    cycle_length_ms = 60000.0 / heart_rate_bpm
    frame_time_ms = 1000.0 / fps
    frames_per_cycle = cycle_length_ms / frame_time_ms

    ed_index, es_index = auto_detect_ed_es(tracking_results, kernels, pixel_spacing)
    systole_fraction = 0.35

    phases: dict[str, int] = {"ED": ed_index, "ES": es_index}

    md_frame = ed_index + int(frames_per_cycle * systole_fraction)
    ir_frame = es_index + int(frames_per_cycle * 0.05)
    er_frame = es_index + int(frames_per_cycle * 0.15)

    phases["MD"] = md_frame % n_frames
    phases["IR"] = ir_frame % n_frames
    phases["ER"] = er_frame % n_frames

    return phases
