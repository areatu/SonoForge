"""Cardiac cycle detection without ECG: FFT-based HR and ED/ES auto-detection."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models.speckle import TrackingKernel, TrackingResult


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

    ed_index, es_index = auto_detect_ed_es(
        tracking_results, kernels, pixel_spacing
    )
    systole_fraction = 0.35

    phases: dict[str, int] = {"ED": ed_index, "ES": es_index}

    md_frame = ed_index + int(frames_per_cycle * systole_fraction)
    ir_frame = es_index + int(frames_per_cycle * 0.05)
    er_frame = es_index + int(frames_per_cycle * 0.15)

    phases["MD"] = md_frame % n_frames
    phases["IR"] = ir_frame % n_frames
    phases["ER"] = er_frame % n_frames

    return phases
