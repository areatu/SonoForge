"""Heart rate estimation from cine echo — optical flow and area-time methods.

Pure NumPy/OpenCV/SciPy — no Qt dependency. Designed to run in a background
thread without affecting playback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from scipy import signal as _signal


@dataclass(frozen=True)
class HeartRateResult:
    """Result of heart rate estimation."""

    bpm: float
    method: str  # "optical_flow" | "area_time" | "combined"
    confidence: float  # 0.0–1.0
    es_intervals_ms: list[float]  # ES→ES intervals in ms
    frame_rate: float  # fps
    num_frames_used: int


# ── Optical flow method ───────────────────────────────────────────


def estimate_hr_optical_flow(
    frames: list[np.ndarray],
    *,
    fps: float,
    roi_xyxy: tuple[int, int, int, int] | None = None,
) -> HeartRateResult:
    """Estimate heart rate from dense optical flow magnitude in ROI.

    Algorithm:
    1. Compute Farneback optical flow between consecutive frames.
    2. Integrate flow magnitude inside ROI → 1D signal.
    3. Bandpass filter (40–200 BPM) to isolate cardiac motion.
    4. Autocorrelation → dominant period → BPM.
    """
    if len(frames) < 4:
        return HeartRateResult(bpm=0.0, method="optical_flow", confidence=0.0,
                               es_intervals_ms=[], frame_rate=fps, num_frames_used=0)

    gray = [_to_gray(f) for f in frames]
    h, w = gray[0].shape

    # Default ROI: center 60% of frame (covers LV region typically)
    if roi_xyxy is not None:
        x0, y0, x1, y1 = roi_xyxy
        x0, y0 = max(0, x0), max(0, y1)
        x1, y1 = min(w, x1), min(h, y1)
    else:
        margin_x = int(w * 0.2)
        margin_y = int(h * 0.2)
        x0, y0 = margin_x, margin_y
        x1, y1 = w - margin_x, h - margin_y

    if x1 - x0 < 10 or y1 - y0 < 10:
        return HeartRateResult(bpm=0.0, method="optical_flow", confidence=0.0,
                               es_intervals_ms=[], frame_rate=fps, num_frames_used=0)

    # Compute flow magnitude signal
    magnitudes = []
    for i in range(len(gray) - 1):
        flow = cv2.calcOpticalFlowFarneback(
            gray[i], gray[i + 1],
            None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2,
            flags=0,
        )
        # Magnitude in ROI
        mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        roi_mag = mag[y0:y1, x0:x1]
        magnitudes.append(float(np.mean(roi_mag)))

    signal_data = np.array(magnitudes)

    # Bandpass filter: 40–200 BPM
    bpm_low, bpm_high = 40.0, 200.0
    freq_low = bpm_low / 60.0
    freq_high = bpm_high / 60.0
    nyquist = fps / 2.0
    if nyquist <= freq_low:
        return HeartRateResult(bpm=0.0, method="optical_flow", confidence=0.0,
                               es_intervals_ms=[], frame_rate=fps, num_frames_used=len(frames))

    # Normalize frequencies
    Wn = [freq_low / nyquist, min(freq_high / nyquist, 0.99)]
    try:
        b, a = _signal.butter(4, Wn, btype="band")
        filtered = _signal.filtfilt(b, a, signal_data)
    except ValueError:
        filtered = signal_data - np.mean(signal_data)

    # Autocorrelation
    bpm, confidence, period_ms = _autocorrelation_bpm(filtered, fps)

    return HeartRateResult(
        bpm=bpm,
        method="optical_flow",
        confidence=confidence,
        es_intervals_ms=[period_ms] if period_ms > 0 else [],
        frame_rate=fps,
        num_frames_used=len(frames),
    )


# ── Area-time method ──────────────────────────────────────────────


def estimate_hr_area_time(
    contour_areas: list[float],
    *,
    fps: float,
    frame_indices: list[int] | None = None,
) -> HeartRateResult:
    """Estimate heart rate from LV area curve using ES-to-ES intervals.

    contour_areas: list of area values (mm²) for each sampled frame.
    fps: frame rate of the original cine.
    frame_indices: if provided, the frame index for each area value
                   (needed when areas are from sparse sampling).
    """
    if len(contour_areas) < 4:
        return HeartRateResult(bpm=0.0, method="area_time", confidence=0.0,
                               es_intervals_ms=[], frame_rate=fps, num_frames_used=0)

    areas = np.array(contour_areas, dtype=np.float64)

    # Determine frame duration
    if frame_indices is not None and len(frame_indices) == len(areas):
        # Sparse sampling: compute actual time gaps
        frame_durations_ms = []
        for i in range(1, len(frame_indices)):
            gap = abs(frame_indices[i] - frame_indices[i - 1])
            frame_durations_ms.append(gap * (1000.0 / fps))
        avg_frame_ms = np.mean(frame_durations_ms) if frame_durations_ms else (1000.0 / fps)
    else:
        avg_frame_ms = 1000.0 / fps

    # Find ES frames (local minima of area = systolic peaks)
    es_indices = _find_local_minima(areas)

    if len(es_indices) < 2:
        # Fallback: use autocorrelation on area signal
        bpm, confidence, period_ms = _autocorrelation_bpm(areas - np.mean(areas), fps)
        return HeartRateResult(
            bpm=bpm,
            method="area_time",
            confidence=confidence,
            es_intervals_ms=[period_ms] if period_ms > 0 else [],
            frame_rate=fps,
            num_frames_used=len(contour_areas),
        )

    # Compute ES→ES intervals
    es_intervals_ms = []
    for i in range(1, len(es_indices)):
        gap_frames = es_indices[i] - es_indices[i - 1]
        es_intervals_ms.append(gap_frames * avg_frame_ms)

    # Heart rate from median interval
    median_interval_ms = float(np.median(es_intervals_ms))
    if median_interval_ms <= 0:
        return HeartRateResult(bpm=0.0, method="area_time", confidence=0.0,
                               es_intervals_ms=es_intervals_ms, frame_rate=fps,
                               num_frames_used=len(contour_areas))

    bpm = 60000.0 / median_interval_ms

    # Confidence: low variance of intervals → high confidence
    if len(es_intervals_ms) >= 2:
        cv = float(np.std(es_intervals_ms) / np.mean(es_intervals_ms))
        confidence = max(0.0, min(1.0, 1.0 - cv))
    else:
        confidence = 0.5

    return HeartRateResult(
        bpm=round(bpm, 1),
        method="area_time",
        confidence=confidence,
        es_intervals_ms=es_intervals_ms,
        frame_rate=fps,
        num_frames_used=len(contour_areas),
    )


# ── Helpers ───────────────────────────────────────────────────────


def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.shape[2] == 3 else np.mean(frame, axis=2).astype(np.uint8)
    return frame.astype(np.uint8)


def _autocorrelation_bpm(signal_1d: np.ndarray, fps: float) -> tuple[float, float, float]:
    """Return (bpm, confidence, period_ms) from autocorrelation."""
    n = len(signal_1d)
    if n < 4:
        return 0.0, 0.0, 0.0

    # Normalize
    sig = signal_1d - np.mean(signal_1d)
    std = np.std(sig)
    if std < 1e-10:
        return 0.0, 0.0, 0.0

    # Autocorrelation via FFT
    fft = np.fft.rfft(sig, n=2 * n)
    acf = np.fft.irfft(fft * np.conj(fft))[:n]
    acf = acf / (std ** 2 * n)

    # Search range: 40–200 BPM
    min_lag = int(60.0 / 200.0 * fps)  # fastest heart rate
    max_lag = int(60.0 / 40.0 * fps)   # slowest heart rate
    min_lag = max(min_lag, 1)
    max_lag = min(max_lag, n - 1)

    if min_lag >= max_lag:
        return 0.0, 0.0, 0.0

    search_region = acf[min_lag:max_lag + 1]
    if len(search_region) == 0:
        return 0.0, 0.0, 0.0

    peak_idx = int(np.argmax(search_region))
    peak_lag = min_lag + peak_idx
    peak_val = float(acf[peak_lag])

    if peak_val < 0.3:
        return 0.0, peak_val, 0.0

    bpm = 60.0 * fps / peak_lag
    period_ms = peak_lag * (1000.0 / fps)

    return round(bpm, 1), min(peak_val, 1.0), period_ms


def _find_local_minima(data: np.ndarray) -> list[int]:
    """Find indices of local minima (ES frames in area curve)."""
    if len(data) < 3:
        return []
    minima = []
    for i in range(1, len(data) - 1):
        if data[i] < data[i - 1] and data[i] < data[i + 1]:
            minima.append(i)
    return minima
