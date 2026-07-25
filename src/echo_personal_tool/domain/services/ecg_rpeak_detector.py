"""R-peak detection from ECG signal using Pan-Tompkins-inspired algorithm."""

from __future__ import annotations

import logging

import numpy as np
from scipy.signal import butter, filtfilt

from echo_personal_tool.domain.models.ecg import RPeakResult

logger = logging.getLogger(__name__)


def detect_r_peaks(
    ecg_signal_mv: np.ndarray,
    sampling_frequency: float,
    min_rr_ms: float = 300.0,
) -> RPeakResult:
    """Detect R-peaks using Pan-Tompkins-inspired algorithm.

    Args:
        ecg_signal_mv: ECG signal in millivolts (1D array).
        sampling_frequency: Sampling rate in Hz.
        min_rr_ms: Minimum R-R interval in ms (refractory period).

    Returns:
        RPeakResult with peak positions, timing, and derived HR.
    """
    n_samples = len(ecg_signal_mv)
    empty = RPeakResult(
        r_peak_indices=np.array([], dtype=np.int64),
        r_peak_times_ms=np.array([], dtype=np.float64),
        heart_rate_bpm=0.0,
        rr_intervals_ms=np.array([], dtype=np.float64),
        confidence=0.0,
    )

    if n_samples < 10 or sampling_frequency <= 0:
        return empty

    # Step 1: Bandpass filter 5–15 Hz
    filtered = _bandpass_filter(ecg_signal_mv, sampling_frequency, low=5.0, high=15.0)

    # Step 2: Derivative + squaring + moving window integration
    diff = np.diff(filtered, prepend=filtered[0])
    squared = diff ** 2
    window_size = max(3, int(0.15 * sampling_frequency))  # ~150ms window
    integrated = _moving_average(squared, window_size)

    # Step 3: Adaptive threshold detection
    min_rr_samples = int(min_rr_ms * sampling_frequency / 1000.0)
    peaks = _adaptive_threshold_detect(integrated, min_rr_samples)

    if len(peaks) < 2:
        return empty

    # Step 4: Compute timing and HR
    peak_times_ms = (peaks / sampling_frequency) * 1000.0
    rr_intervals_ms = np.diff(peak_times_ms)

    if len(rr_intervals_ms) > 0:
        median_rr = np.median(rr_intervals_ms)
        heart_rate_bpm = 60000.0 / median_rr if median_rr > 0 else 0.0
    else:
        heart_rate_bpm = 0.0

    # Step 5: Confidence based on regularity
    if len(rr_intervals_ms) >= 2:
        cv = np.std(rr_intervals_ms) / np.mean(rr_intervals_ms) if np.mean(rr_intervals_ms) > 0 else 1.0
        confidence = max(0.0, min(1.0, 1.0 - cv))
    else:
        confidence = 0.3

    return RPeakResult(
        r_peak_indices=peaks,
        r_peak_times_ms=peak_times_ms,
        heart_rate_bpm=heart_rate_bpm,
        rr_intervals_ms=rr_intervals_ms,
        confidence=confidence,
    )


def _bandpass_filter(signal: np.ndarray, fs: float, low: float, high: float) -> np.ndarray:
    """Apply Butterworth bandpass filter."""
    nyq = fs / 2.0
    low_n = low / nyq
    high_n = high / nyq
    low_n = max(low_n, 0.01)
    high_n = min(high_n, 0.99)
    if low_n >= high_n:
        return signal.copy()
    try:
        b, a = butter(2, [low_n, high_n], btype="band")
        return filtfilt(b, a, signal)
    except Exception:
        return signal.copy()


def _moving_average(signal: np.ndarray, window_size: int) -> np.ndarray:
    """Compute moving average with uniform window."""
    if window_size <= 1:
        return signal.copy()
    kernel = np.ones(window_size) / window_size
    return np.convolve(signal, kernel, mode="same")


def _adaptive_threshold_detect(
    signal: np.ndarray,
    min_rr_samples: int,
) -> np.ndarray:
    """Detect peaks using adaptive thresholding."""
    if len(signal) < 3:
        return np.array([], dtype=np.int64)

    # Find local maxima
    peaks = []
    for i in range(1, len(signal) - 1):
        if signal[i] > signal[i - 1] and signal[i] > signal[i + 1]:
            peaks.append(i)

    if not peaks:
        return np.array([], dtype=np.int64)

    # Adaptive threshold: use median of peak values
    peak_values = signal[np.array(peaks)]
    threshold = np.median(peak_values) * 0.5

    # Filter by threshold and refractory period
    filtered_peaks = []
    for p in peaks:
        if signal[p] < threshold:
            continue
        if filtered_peaks and (p - filtered_peaks[-1]) < min_rr_samples:
            # Keep the stronger peak
            if signal[p] > signal[filtered_peaks[-1]]:
                filtered_peaks[-1] = p
        else:
            filtered_peaks.append(p)

    return np.array(filtered_peaks, dtype=np.int64)
