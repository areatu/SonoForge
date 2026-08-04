"""Cardiac cycle detection with ECG-to-spectrogram time alignment.

A single service that turns an ECG waveform (and, optionally, a spectral
fallback signal) into a list of :class:`CardiacCycle` boundaries expressed in
the spectrogram's local millisecond domain. Used by the vessel Doppler
auto-trace to snap PSV/EDV to real cardiac cycles instead of relying on the
raw ROI edges.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.models.ecg import EcgWaveform, RPeakResult
from echo_personal_tool.domain.services.ecg_rpeak_detector import detect_r_peaks

_ALIGN_CONFIDENCE_THRESHOLD = 0.3
_CYCLE_CONFIDENCE_THRESHOLD = 0.4
_MIN_PROFILE_SAMPLES = 5
_MARKER_SIGMA_MS = 60.0
_CYCLE_EDV_FRACTION = 0.25
_MIN_CYCLE_POINTS = 3


@dataclass(frozen=True)
class CycleAlignment:
    """Time offset aligning spectrogram local time to ECG absolute time."""

    offset_ms: float
    confidence: float
    source: str


@dataclass(frozen=True)
class CardiacCycle:
    """One cardiac cycle boundary, in the spectrogram's local ms domain."""

    start_ms: float
    end_ms: float
    r_peak_ms: float
    ed_ms: float
    es_ms: float
    source: str
    confidence: float
    rr_ms: float | None = None


def _primary_voltage(ecg: EcgWaveform) -> tuple[np.ndarray, float] | None:
    """Return (voltage_mv, sampling_frequency) of the primary ECG lead."""
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


def align_spectrogram_to_ecg(
    ecg: EcgWaveform,
    profile_times_ms: np.ndarray,
    fallback_signal: np.ndarray,
    *,
    max_shift_ms: float = 1500.0,
    r_peak_result: RPeakResult | None = None,
) -> CycleAlignment | None:
    """Recover the offset mapping spectrogram local time to ECG absolute time.

    The fallback signal (spectral column intensity / envelope velocity) has
    one burst per cardiac cycle; correlating it with the ECG R-peak impulse
    train recovers ``offset`` such that ``absolute_time = local_time + offset``.
    Returns ``None`` when the ECG is unusable or the correlation is too weak.
    """
    times = np.asarray(profile_times_ms, dtype=np.float64)
    signal = np.asarray(fallback_signal, dtype=np.float64)
    if times.ndim != 1 or signal.ndim != 1 or times.size != signal.size:
        return None
    if times.size < _MIN_PROFILE_SAMPLES:
        return None

    order = np.argsort(times, kind="stable")
    times = times[order]
    signal = signal[order]

    if np.nanstd(signal) <= 1e-9:
        return None

    lead_data = _primary_voltage(ecg)
    if lead_data is None:
        return None
    voltage, fs = lead_data

    if r_peak_result is None:
        r_peak_result = detect_r_peaks(voltage, fs)
    if len(r_peak_result.r_peak_indices) < 2:
        return None

    duration_ms = (voltage.size / fs) * 1000.0
    grid_ms = np.arange(0.0, duration_ms, 1.0)
    if grid_ms.size == 0:
        return None

    marker = np.zeros(grid_ms.size, dtype=np.float64)
    sigma = _MARKER_SIGMA_MS
    for peak_ms in r_peak_result.r_peak_times_ms:
        marker += np.exp(-0.5 * ((grid_ms - float(peak_ms)) / sigma) ** 2)

    max_shift_samples = max(1, int(round(max_shift_ms)))
    offsets = np.arange(-max_shift_samples, max_shift_samples + 1, dtype=np.float64)
    abs_times = times[None, :] + offsets[:, None]
    marker_values = np.interp(abs_times, grid_ms, marker, left=0.0, right=0.0)
    scores = marker_values @ signal

    best_idx = int(np.argmax(scores))
    best_offset = float(offsets[best_idx])

    best_abs = times + best_offset
    in_range = (best_abs >= 0.0) & (best_abs < duration_ms)
    if not np.any(in_range):
        return None

    aligned_marker = np.interp(best_abs, grid_ms, marker, left=0.0, right=0.0)
    p = signal[in_range]
    m = aligned_marker[in_range]
    denom = float(np.linalg.norm(p) * np.linalg.norm(m))
    confidence = float(np.dot(p, m) / denom) if denom > 0.0 else 0.0
    confidence = max(0.0, min(1.0, confidence))

    if confidence < _ALIGN_CONFIDENCE_THRESHOLD:
        return None
    return CycleAlignment(offset_ms=best_offset, confidence=confidence, source="ecg")


def derive_psv_edv_indices_with_cycles(
    envelope: tuple[tuple[float, float], ...],
    cycles: Sequence[CardiacCycle],
    axis_mapping: DopplerAxisMapping,
) -> tuple[int, int] | None:
    """Snap PSV/EDV to the ECG cycle that contains the systolic peak.

    Envelope points are plot coordinates ``(x_px, y_px)`` with velocity
    increasing upward. Times are derived through the axis mapping. PSV is the
    highest-velocity point (minimum y); EDV is the lowest-velocity point
    (maximum y) inside the last quarter of the selected cycle. Returns ``None``
    when no cycle contains the systolic peak or the cycle is too sparse.
    """
    if not envelope or not cycles:
        return None
    times = np.asarray([axis_mapping.time_ms_from_x(p[0]) for p in envelope], dtype=np.float64)
    ys = np.asarray([p[1] for p in envelope], dtype=np.float64)
    if ys.size < _MIN_CYCLE_POINTS:
        return None

    psv_idx = int(np.argmin(ys))
    psv_t = float(times[psv_idx])
    cycle = next((c for c in cycles if c.start_ms <= psv_t <= c.end_ms), None)
    if cycle is None:
        return None

    t_lo, t_hi = float(np.min(times)), float(np.max(times))
    eff_start = max(float(cycle.start_ms), t_lo)
    eff_end = min(float(cycle.end_ms), t_hi)
    if eff_end - eff_start < 1.0:
        return None

    in_cycle = (times >= eff_start) & (times <= eff_end)
    if int(in_cycle.sum()) < _MIN_CYCLE_POINTS:
        return None

    span = eff_end - eff_start
    edv_search_start = eff_start + (1.0 - _CYCLE_EDV_FRACTION) * span
    in_diastole = in_cycle & (times >= edv_search_start)
    if int(in_diastole.sum()) == 0:
        in_diastole = in_cycle
    diastole_indices = np.nonzero(in_diastole)[0]
    edv_idx = int(diastole_indices[int(np.argmax(ys[diastole_indices]))])
    return psv_idx, edv_idx


class CardiacCycleService:
    """Build cardiac cycle boundaries from an ECG waveform (or none)."""

    def get_cycles(
        self,
        *,
        ecg: EcgWaveform | None,
        spectrogram_time_axis_ms: np.ndarray | None = None,
        fallback_signal: np.ndarray | None = None,
        max_shift_ms: float = 1500.0,
    ) -> list[CardiacCycle]:
        """Return ECG cycles in the spectrogram's local ms domain.

        Returns an empty list when no ECG is available, the ECG is unusable,
        or the correlation between the fallback signal and the ECG R-peaks is
        too weak — the caller should fall back to image/manual cycles.
        """
        if ecg is None or spectrogram_time_axis_ms is None or fallback_signal is None:
            return []

        times = np.asarray(spectrogram_time_axis_ms, dtype=np.float64)
        signal = np.asarray(fallback_signal, dtype=np.float64)
        if times.ndim != 1 or signal.ndim != 1 or times.size != signal.size:
            return []
        if times.size < _MIN_PROFILE_SAMPLES:
            return []

        lead_data = _primary_voltage(ecg)
        if lead_data is None:
            return []
        voltage, fs = lead_data

        r_peak_result = detect_r_peaks(voltage, fs)
        if len(r_peak_result.r_peak_indices) < 2:
            return []
        if r_peak_result.confidence < _CYCLE_CONFIDENCE_THRESHOLD:
            return []

        alignment = align_spectrogram_to_ecg(
            ecg,
            times,
            signal,
            max_shift_ms=max_shift_ms,
            r_peak_result=r_peak_result,
        )
        if alignment is None:
            return []

        t0, t1 = float(np.min(times)), float(np.max(times))
        local_peaks = r_peak_result.r_peak_times_ms - alignment.offset_ms
        rr_intervals = r_peak_result.rr_intervals_ms

        cycles: list[CardiacCycle] = []
        for i, peak_local in enumerate(local_peaks):
            if i + 1 >= len(local_peaks):
                break
            next_local = float(local_peaks[i + 1])
            rr = float(rr_intervals[i]) if i < len(rr_intervals) else next_local - float(peak_local)
            start = max(float(peak_local), t0)
            end = min(next_local, t1)
            if end - start < 1.0:
                continue
            cycles.append(
                CardiacCycle(
                    start_ms=start,
                    end_ms=end,
                    r_peak_ms=float(peak_local),
                    ed_ms=float(peak_local),
                    es_ms=float(peak_local) + 0.35 * rr,
                    source="ecg",
                    confidence=min(float(r_peak_result.confidence), float(alignment.confidence)),
                    rr_ms=rr,
                )
            )
        return cycles
