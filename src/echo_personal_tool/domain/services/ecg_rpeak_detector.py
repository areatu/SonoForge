"""R-peak detection from ECG signal using Pan-Tompkins-inspired algorithm."""

from __future__ import annotations

import logging

import numpy as np
from scipy.signal import butter, filtfilt

from echo_personal_tool.domain.models.ecg import EcgWaveform, RPeakResult

logger = logging.getLogger(__name__)


def primary_ecg_signal(ecg: EcgWaveform) -> tuple[np.ndarray, float] | None:
    """Return (voltage_mv, sampling_frequency) of the primary ECG lead.

    Prefers Lead II (standard for R-peak detection); falls back to the first
    lead. Returns None when no usable lead exists.
    """
    lead = ecg.primary_lead
    if lead is None or lead.sampling_frequency <= 0:
        return None
    try:
        lead_index = ecg.leads.index(lead)
    except ValueError:
        lead_index = 0
    voltage = ecg.as_voltage_mv(lead_index)
    if voltage.ndim != 1 or voltage.size < 10:
        return None
    return voltage, float(lead.sampling_frequency)


def detect_r_peaks_from_waveform(ecg: EcgWaveform) -> RPeakResult | None:
    """Detect R-peaks from the primary lead of an ECG waveform.

    Returns None when the waveform has no usable primary lead.
    """
    signal = primary_ecg_signal(ecg)
    if signal is None:
        return None
    voltage, fs = signal
    return detect_r_peaks(voltage, fs)


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
    signal_mv = np.asarray(ecg_signal_mv, dtype=np.float64)
    n_samples = len(signal_mv)
    empty = RPeakResult(
        r_peak_indices=np.array([], dtype=np.int64),
        r_peak_times_ms=np.array([], dtype=np.float64),
        heart_rate_bpm=0.0,
        rr_intervals_ms=np.array([], dtype=np.float64),
        confidence=0.0,
    )

    if n_samples < 10 or sampling_frequency <= 0 or not np.isfinite(signal_mv).all():
        return empty

    # Step 1: Bandpass filter 5–15 Hz (zero-phase, median-centred even padding)
    filtered = _bandpass_filter(signal_mv, sampling_frequency, low=5.0, high=15.0)

    # Step 2: Derivative + squaring + moving window integration
    diff = np.diff(filtered, prepend=filtered[0])
    squared = diff**2
    window_size = max(3, int(0.15 * sampling_frequency))  # ~150ms window
    integrated = _moving_average(squared, window_size)
    if float(np.max(integrated)) <= 1e-12:
        return empty

    # Step 3: Adaptive threshold detection + local QRS apex refinement
    min_rr_samples = max(1, int(min_rr_ms * sampling_frequency / 1000.0))
    cand_peaks = _adaptive_threshold_detect(integrated, min_rr_samples)
    if len(cand_peaks) < 2:
        return empty

    search_radius = max(1, int(0.08 * sampling_frequency))  # ±80ms half-QRS window
    peaks = _refine_peaks_to_qrs(filtered, cand_peaks, search_radius, min_rr_samples)
    if len(peaks) < 2:
        return empty

    # Step 4: Compute timing and HR
    peak_times_ms = (peaks / sampling_frequency) * 1000.0
    rr_intervals_ms = np.diff(peak_times_ms)

    if len(rr_intervals_ms) > 0:
        median_rr = float(np.median(rr_intervals_ms))
        heart_rate_bpm = 60000.0 / median_rr if median_rr > 0 else 0.0
    else:
        heart_rate_bpm = 0.0

    # Step 5: Confidence blends rhythm regularity, local bandpass QRS amplitude
    # consistency, and QRS pulsatility.
    # - Local bandpass peak height (instead of single-sample raw voltage) is
    #   invariant to 1-sample envelope shifts and respiratory baseline wander.
    # - Pulsatility (25th-percentile background vs peak integrated energy)
    #   prevents continuous periodic noise or white noise from scoring high.
    amp_values = np.array(
        [
            float(np.max(np.abs(filtered[max(0, int(p) - search_radius) : min(n_samples, int(p) + search_radius + 1)])))
            for p in peaks
        ],
        dtype=np.float64,
    )
    if len(amp_values) >= 2:
        amp_mean = float(np.mean(amp_values))
        amp_spread = float(np.std(amp_values))
        amp_cv = amp_spread / max(amp_mean, 1e-9)
        amp_quality = max(0.0, min(1.0, 1.0 - amp_cv))
    else:
        amp_quality = 0.5

    peak_integ = float(np.median(integrated[cand_peaks]))
    bg_integ = float(np.percentile(integrated, 25))
    bg_ratio = bg_integ / max(peak_integ, 1e-12)
    pulsatility = max(0.0, min(1.0, 1.0 - 4.0 * bg_ratio))

    if len(rr_intervals_ms) >= 2:
        mean_rr = float(np.mean(rr_intervals_ms))
        cv = float(np.std(rr_intervals_ms)) / mean_rr if mean_rr > 0 else 1.0
        regularity = max(0.0, min(1.0, 1.0 - cv))
    else:
        regularity = 0.3

    confidence = pulsatility * (0.55 * regularity + 0.45 * amp_quality)
    if not (25.0 <= heart_rate_bpm <= 220.0):
        confidence *= 0.3
    confidence = max(0.0, min(1.0, confidence))

    return RPeakResult(
        r_peak_indices=peaks,
        r_peak_times_ms=peak_times_ms,
        heart_rate_bpm=heart_rate_bpm,
        rr_intervals_ms=rr_intervals_ms,
        confidence=confidence,
    )


def _refine_peaks_to_qrs(
    filtered: np.ndarray,
    cand_peaks: np.ndarray,
    search_radius: int,
    min_rr_samples: int,
) -> np.ndarray:
    """Snap integrated-envelope candidates to local |filtered| QRS maxima."""
    n = len(filtered)
    abs_filtered = np.abs(filtered)
    refined: list[int] = []
    for p in cand_peaks:
        lo = max(0, int(p) - search_radius)
        hi = min(n, int(p) + search_radius + 1)
        if hi <= lo:
            continue
        r_idx = lo + int(np.argmax(abs_filtered[lo:hi]))
        if refined and (r_idx - refined[-1]) < min_rr_samples:
            if abs_filtered[r_idx] > abs_filtered[refined[-1]]:
                refined[-1] = r_idx
        else:
            refined.append(r_idx)
    return np.array(refined, dtype=np.int64)


def _bandpass_filter(signal: np.ndarray, fs: float, low: float, high: float) -> np.ndarray:
    """Apply Butterworth bandpass filter with even boundary reflection."""
    nyq = fs / 2.0
    low_n = low / nyq
    high_n = high / nyq
    low_n = max(low_n, 0.01)
    high_n = min(high_n, 0.99)
    if low_n >= high_n:
        return signal.copy()
    try:
        b, a = butter(2, [low_n, high_n], btype="band")
        centered = signal - float(np.median(signal))
        return np.asarray(filtfilt(b, a, centered, padtype="even"))
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
    """Detect peaks using chunked QRS reference thresholding."""
    if len(signal) < 3:
        return np.array([], dtype=np.int64)

    # Find local maxima (including flat-top plateaux from boxcar integration)
    peaks = [i for i in range(1, len(signal) - 1) if signal[i] >= signal[i - 1] and signal[i] > signal[i + 1]]

    if not peaks:
        return np.array([], dtype=np.int64)

    # Estimate QRS peak height from ~0.9s window maxima so P/T waves and tiny
    # filter ringing ripples cannot drag the median down to the noise floor,
    # while a single giant lead-pop outlier cannot blind the rest of the clip.
    peaks_arr = np.array(peaks, dtype=np.int64)
    chunk_len = max(1, min_rr_samples * 3)
    chunk_maxima = [
        float(np.max(signal[in_chunk]))
        for start in range(0, len(signal), chunk_len)
        if (in_chunk := peaks_arr[(peaks_arr >= start) & (peaks_arr < start + chunk_len)]).size
    ]
    ref_height = float(np.percentile(chunk_maxima, 75)) if chunk_maxima else float(np.max(signal[peaks_arr]))
    threshold = ref_height * 0.25

    # Filter by threshold and refractory period
    filtered_peaks: list[int] = []
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
