"""Cardiac cycle detection with ECG-to-spectrogram time alignment.

A single service that turns an ECG waveform or, when the ECG is absent or
unusable, the spectral envelope itself into a list of
:class:`CardiacCycle` boundaries expressed in the spectrogram's local
millisecond domain. Used by the vessel Doppler auto-trace to snap PSV/EDV to
real cardiac cycles instead of relying on the raw ROI edges.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.models.ecg import EcgWaveform, RPeakResult
from echo_personal_tool.domain.services.ecg_rpeak_detector import (
    detect_r_peaks,
    primary_ecg_signal,
)

_ALIGN_CONFIDENCE_THRESHOLD = 0.3
_CYCLE_CONFIDENCE_THRESHOLD = 0.4
_MIN_PROFILE_SAMPLES = 5
_MARKER_SIGMA_MS = 60.0
_CYCLE_EDV_FRACTION = 0.25
_MIN_CYCLE_POINTS = 3
_MIN_PEAK_DISTANCE_MS = 300.0
_EDV_WINDOW_MS = 30.0
_EDV_WINDOW_MAX_POINTS = 10


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

    lead_data = primary_ecg_signal(ecg)
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


def _edv_window_indices(
    times: np.ndarray,
    min_idx: int,
    *,
    min_time: float,
    window_ms: float = _EDV_WINDOW_MS,
    max_window_points: int = _EDV_WINDOW_MAX_POINTS,
) -> tuple[tuple[int, ...], int]:
    """Return ``(window_indices, midpoint_idx)`` for the EDV averaging window.

    The window ends at *min_idx* (the diastolic minimum) and walks backward in
    time, collecting at most ``window_ms`` ms or ``max_window_points`` points
    and never before *min_time*. *midpoint_idx* is the envelope index nearest
    the window's midpoint in time.
    """
    window = [int(min_idx)]
    t_min = float(times[min_idx])
    for i in range(min_idx - 1, -1, -1):
        if float(times[i]) < min_time:
            break
        if t_min - float(times[i]) > window_ms or len(window) >= max_window_points:
            break
        window.append(i)
    window.sort()
    mid_t = (float(times[window[0]]) + float(times[window[-1]])) * 0.5
    midpoint_idx = int(np.argmin(np.abs(times - mid_t)))
    return tuple(window), midpoint_idx


def _edv_idx_before_upstroke(
    times: np.ndarray,
    ys: np.ndarray,
    cycle: CardiacCycle,
    psv_idx: int,
) -> int:
    """Index of the EDV marker just before the next systolic upstroke.

    Locates the diastolic minimum (maximum plot-y in the last quarter of the
    cycle) and returns the midpoint index of the adaptive averaging window
    ending there (backward, ≤ 30 ms / 10 points, truncated to the cycle start
    and to the PSV). Falls back to the minimum index when the window holds
    fewer than two points.
    """
    t_lo, t_hi = float(np.min(times)), float(np.max(times))
    eff_start = max(float(cycle.start_ms), t_lo)
    eff_end = min(float(cycle.end_ms), t_hi)
    if eff_end - eff_start < 1.0:
        return int(np.argmax(ys))
    span = eff_end - eff_start
    edv_search_start = eff_start + (1.0 - _CYCLE_EDV_FRACTION) * span
    in_cycle = (times >= eff_start) & (times <= eff_end)
    in_diastole = in_cycle & (times >= edv_search_start)
    if int(in_diastole.sum()) == 0:
        in_diastole = in_cycle
    diastole_indices = np.nonzero(in_diastole)[0]
    edv_min_idx = int(diastole_indices[int(np.argmax(ys[diastole_indices]))])
    min_time = max(eff_start, float(times[psv_idx]))
    window, midpoint_idx = _edv_window_indices(times, edv_min_idx, min_time=min_time)
    if len(window) < 2:
        return edv_min_idx
    return midpoint_idx


def _snap_in_cycle(
    times: np.ndarray,
    ys: np.ndarray,
    cycle: CardiacCycle,
    *,
    below_baseline: bool = False,
) -> tuple[int, int, float] | None:
    """Return ``(psv_idx, edv_idx, edv_value)`` snapped inside a cycle.

    PSV is the minimum envelope point (after optional baseline reflection);
    EDV is the mean of the adaptive window before the diastolic minimum, with
    the marker index at the window's midpoint. *edv_value* is in the same
    units as ``ys``; the caller converts to cm/s.
    """
    work = -ys if below_baseline else ys
    t_lo, t_hi = float(np.min(times)), float(np.max(times))
    eff_start = max(float(cycle.start_ms), t_lo)
    eff_end = min(float(cycle.end_ms), t_hi)
    if eff_end - eff_start < 1.0:
        return None

    in_cycle = (times >= eff_start) & (times <= eff_end)
    if int(in_cycle.sum()) < _MIN_CYCLE_POINTS:
        return None

    indices = np.nonzero(in_cycle)[0]
    psv_idx = int(indices[int(np.argmin(work[indices]))])

    span = eff_end - eff_start
    edv_search_start = eff_start + (1.0 - _CYCLE_EDV_FRACTION) * span
    in_diastole = in_cycle & (times >= edv_search_start)
    if int(in_diastole.sum()) == 0:
        in_diastole = in_cycle
    diastole_indices = np.nonzero(in_diastole)[0]
    edv_min_idx = int(diastole_indices[int(np.argmax(work[diastole_indices]))])

    min_time = max(eff_start, float(times[psv_idx]))
    window, midpoint_idx = _edv_window_indices(times, edv_min_idx, min_time=min_time)
    if len(window) < 2:
        return psv_idx, edv_min_idx, float(ys[edv_min_idx])
    edv_value = float(np.mean(ys[list(window)]))
    return psv_idx, midpoint_idx, edv_value


def detect_cycles_from_envelope(
    times_ms: np.ndarray,
    velocities: np.ndarray,
    *,
    max_cycles: int = 5,
    min_peak_prominence: float = 0.15,
) -> list[CardiacCycle]:
    """Detect cardiac cycles from the spectral envelope velocity profile.

    Each heartbeat produces a clear systolic peak, so cycles can be derived
    without any ECG. Peaks are found with :func:`scipy.signal.find_peaks`
    using a prominence floor of ``min_peak_prominence`` of the velocity range
    and a minimum peak distance of 300 ms. A cycle spans two consecutive
    peaks (mirroring the ECG-derived cycles). Flat/weak/malformed profiles
    yield ``[]``.
    """
    from scipy.signal import find_peaks

    times = np.asarray(times_ms, dtype=np.float64)
    velocities = np.asarray(velocities, dtype=np.float64)
    if times.ndim != 1 or velocities.ndim != 1 or times.size != velocities.size:
        return []
    if times.size < _MIN_PROFILE_SAMPLES:
        return []
    if np.isnan(velocities).any():
        return []

    order = np.argsort(times, kind="stable")
    times = times[order]
    velocities = velocities[order]

    if np.nanstd(velocities) <= 1e-9:
        return []
    span = float(np.max(velocities)) - float(np.min(velocities))
    if span <= 1e-9:
        return []

    dts = np.diff(times)
    sample_ms = float(np.median(dts)) if dts.size else 0.0
    min_distance = max(1, int(round(_MIN_PEAK_DISTANCE_MS / sample_ms))) if sample_ms > 0 else 1
    peaks, _ = find_peaks(velocities, prominence=min_peak_prominence * span, distance=min_distance)
    if peaks.size < 2:
        return []

    cycles: list[CardiacCycle] = []
    for i in range(peaks.size - 1):
        start = float(times[peaks[i]])
        end = float(times[peaks[i + 1]])
        rr = end - start
        cycles.append(
            CardiacCycle(
                start_ms=start,
                end_ms=end,
                r_peak_ms=start,
                ed_ms=end,
                es_ms=start + 0.35 * rr,
                source="envelope",
                confidence=1.0,
                rr_ms=rr,
            )
        )
        if len(cycles) >= max_cycles:
            break
    return cycles


def derive_psv_edv_indices_with_cycles(
    envelope: tuple[tuple[float, float], ...],
    cycles: Sequence[CardiacCycle],
    axis_mapping: DopplerAxisMapping,
    *,
    below_baseline: bool = False,
) -> tuple[int, int, float] | None:
    """Snap PSV/EDV to the ECG cycle that contains the systolic peak.

    Envelope points are plot coordinates ``(x_px, y_px)`` with velocity
    increasing upward. Times are derived through the axis mapping. PSV is the
    highest-velocity point (minimum y); EDV is the adaptive window mean before
    the diastolic minimum of the last quarter of the selected cycle. Returns
    ``(psv_idx, edv_idx, edv_value)`` or ``None`` when no cycle contains the
    systolic peak or the cycle is too sparse.
    """
    if not envelope or not cycles:
        return None
    times = np.asarray([axis_mapping.time_ms_from_x(p[0]) for p in envelope], dtype=np.float64)
    ys = np.asarray([p[1] for p in envelope], dtype=np.float64)
    if ys.size < _MIN_CYCLE_POINTS:
        return None

    ys_eff = -ys if below_baseline else ys
    psv_idx = int(np.argmin(ys_eff))
    psv_t = float(times[psv_idx])
    cycle = next((c for c in cycles if c.start_ms <= psv_t <= c.end_ms), None)
    if cycle is None:
        return None
    return _snap_in_cycle(times, ys, cycle, below_baseline=below_baseline)


def derive_psv_edv_indices_per_cycle(
    envelope: tuple[tuple[float, float], ...],
    cycles: Sequence[CardiacCycle],
    axis_mapping: DopplerAxisMapping,
    *,
    below_baseline: bool = False,
    max_cycles: int = 3,
) -> list[tuple[int, int, float, int]]:
    """Return per-cycle ``(psv_idx, edv_idx, edv_value, cycle_index)`` tuples.

    Up to *max_cycles* cycles are considered; cycles too sparse or falling
    outside the envelope time range are skipped. Used for multi-beat PSV/EDV
    averaging and the manual cycle-selection correction mode.
    """
    if not envelope or not cycles:
        return []
    times = np.asarray([axis_mapping.time_ms_from_x(p[0]) for p in envelope], dtype=np.float64)
    ys = np.asarray([p[1] for p in envelope], dtype=np.float64)
    if ys.size < _MIN_CYCLE_POINTS:
        return []

    results: list[tuple[int, int, float, int]] = []
    for i, cycle in enumerate(cycles[:max_cycles]):
        snapped = _snap_in_cycle(times, ys, cycle, below_baseline=below_baseline)
        if snapped is not None:
            psv_idx, edv_idx, edv_value = snapped
            results.append((psv_idx, edv_idx, edv_value, i))
    return results


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
        """Return cardiac cycles in the spectrogram's local ms domain.

        Cycles come from the ECG R-peak train when a usable ECG is present
        and aligns to the fallback signal; otherwise they are derived from the
        envelope velocity profile itself (``source="envelope"``) so averaging
        works without ECG. Returns an empty list only when no signal is
        available or it carries no detectable peaks.
        """
        if spectrogram_time_axis_ms is None or fallback_signal is None:
            return []

        times = np.asarray(spectrogram_time_axis_ms, dtype=np.float64)
        signal = np.asarray(fallback_signal, dtype=np.float64)
        if times.ndim != 1 or signal.ndim != 1 or times.size != signal.size:
            return []
        if times.size < _MIN_PROFILE_SAMPLES:
            return []

        if ecg is None:
            return detect_cycles_from_envelope(times, signal)

        lead_data = primary_ecg_signal(ecg)
        if lead_data is None:
            return detect_cycles_from_envelope(times, signal)
        voltage, fs = lead_data

        r_peak_result = detect_r_peaks(voltage, fs)
        if len(r_peak_result.r_peak_indices) < 2:
            return detect_cycles_from_envelope(times, signal)
        if r_peak_result.confidence < _CYCLE_CONFIDENCE_THRESHOLD:
            return detect_cycles_from_envelope(times, signal)

        alignment = align_spectrogram_to_ecg(
            ecg,
            times,
            signal,
            max_shift_ms=max_shift_ms,
            r_peak_result=r_peak_result,
        )
        if alignment is None:
            return detect_cycles_from_envelope(times, signal)

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
