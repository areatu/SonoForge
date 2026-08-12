"""Compute Doppler indices from marker DTOs."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.calculations.bernoulli import pressure_gradient_mmhg
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.measurements import DopplerResults

_np_trapezoid = getattr(np, "trapezoid", None) or np.trapz


def _normalize_label(label: str) -> str:
    return label.strip().lower().replace("'", "_prime").replace("′", "_prime").replace(" ", "_")


def _find_peak_velocity(dto: DopplerMeasurementDTO, *labels: str) -> float | None:
    wanted = {_normalize_label(label) for label in labels}
    for peak in dto.peaks:
        if _normalize_label(peak.label) in wanted:
            return peak.velocity_cm_s
    return None


def _find_interval_duration_ms(dto: DopplerMeasurementDTO, label: str) -> float | None:
    wanted = _normalize_label(label)
    for interval in dto.intervals:
        if _normalize_label(interval.label) == wanted:
            return interval.end_time_ms - interval.start_time_ms
    return None


def _find_interval_bounds_ms(dto: DopplerMeasurementDTO, label: str) -> tuple[float, float] | None:
    wanted = _normalize_label(label)
    for interval in dto.intervals:
        if _normalize_label(interval.label) == wanted:
            return interval.start_time_ms, interval.end_time_ms
    return None


def _find_vti_cm(dto: DopplerMeasurementDTO) -> float | None:
    """Average the trapezoidal VTI over all VTI traces.

    Matches any trace whose normalized label starts with the ``vti`` prefix
    (``VTI``, ``VTI MV``, ``VTI MR``, ``VTI AR``, ``VTI TR``, ``VTI PR``, …),
    so valve-specific traces committed by the UI are measured too.     Multi-beat
    traces produced by the auto-trace flow each cover one cardiac cycle;
    averaging them yields the beat-averaged VTI. A single manual trace (the
    common case) averages to itself.

    Trace timestamps are milliseconds, so the raw trapezoidal integral of
    (cm/s) over (ms) is 1000x too large; dividing by 1000 yields cm.
    """
    values: list[float] = []
    for trace in dto.traces:
        if not _normalize_label(trace.label).startswith("vti"):
            continue
        if len(trace.points) < 2:
            continue
        times = [point[0] for point in trace.points]
        velocities = [point[1] for point in trace.points]
        values.append(float(_np_trapezoid(velocities, times)) / 1000.0)
    if not values:
        return None
    return abs(sum(values) / len(values))


def _find_peak_velocity_from_trace(dto: DopplerMeasurementDTO) -> float | None:
    """Vpeak from the highest absolute velocity across all VTI traces.

    Used as a fallback when no explicit Vmax peak marker is placed.
    For regurgitation traces (negative velocities) the absolute value
    is taken so the peak magnitude is reported correctly.
    """
    candidates: list[float] = []
    for trace in dto.traces:
        if not _normalize_label(trace.label).startswith("vti"):
            continue
        if not trace.points:
            continue
        max_v = max(abs(point[1]) for point in trace.points)
        candidates.append(max_v)
    return max(candidates) if candidates else None


def _find_mean_velocity_from_trace(dto: DopplerMeasurementDTO) -> float | None:
    """Vmean from the first VTI trace: |VTI| / duration in seconds.

    Falls back to trace-based duration when no ET interval marker is
    available. Returns ``None`` when the trace has fewer than 2 points
    or the duration is zero. Uses ``abs(VTI)`` so regurgitation traces
    (negative velocities) still yield a positive mean velocity.
    """
    vti = _find_vti_cm(dto)
    if vti is None:
        return None
    vti_abs = abs(vti)
    if vti_abs <= 0:
        return None
    for trace in dto.traces:
        if not _normalize_label(trace.label).startswith("vti"):
            continue
        if len(trace.points) < 2:
            continue
        times = [point[0] for point in trace.points]
        duration_s = (max(times) - min(times)) / 1000.0
        if duration_s > 0:
            return vti_abs / duration_s
    return None


def _integral_velocity_sq_ms(
    times: list[float], velocities: list[float], start_ms: float, end_ms: float
) -> float:
    """Exact ∫v(t)²dt over [start_ms, end_ms] for a piecewise-linear envelope.

    Velocities are in cm/s and times in ms, so the result has units
    (cm/s)²·ms. Only the portion of each linear segment that falls inside
    the window contributes, so baseline samples outside the flow period are
    correctly excluded.
    """
    points = sorted(zip(times, velocities))
    total = 0.0
    for i in range(len(points) - 1):
        (ta, va), (tb, vb) = points[i], points[i + 1]
        if tb <= start_ms or ta >= end_ms or tb == ta:
            continue
        a = max(ta, start_ms)
        b = min(tb, end_ms)
        if a >= b:
            continue
        va_a = va + (vb - va) * (a - ta) / (tb - ta)
        va_b = va + (vb - va) * (b - ta) / (tb - ta)
        width = b - a
        total += width * (va_a * va_a + va_a * va_b + va_b * va_b) / 3.0
    return total


def _find_mean_pressure_gradient_from_trace(dto: DopplerMeasurementDTO) -> float | None:
    """ASE/EACVI PGmean = (1/T)·∫4·v(t)²dt, averaged over the VTI traces.

    The instantaneous Bernoulli gradient is 4·(v/100)² with v in cm/s; this
    is averaged (not derived from Vmean) because Bernoulli is nonlinear:
    4·Vmean² underestimates the true mean gradient.

    The integration window is the ET interval when it is fully covered by a
    trace (consistent with Vmean = VTI / ET), otherwise the full trace span.
    """
    et_bounds = _find_interval_bounds_ms(dto, "et")
    values: list[float] = []
    for trace in dto.traces:
        if not _normalize_label(trace.label).startswith("vti"):
            continue
        if len(trace.points) < 2:
            continue
        times = [point[0] for point in trace.points]
        velocities = [point[1] for point in trace.points]
        t_min = min(times)
        t_max = max(times)
        start_ms, end_ms = t_min, t_max
        if et_bounds is not None:
            es, ee = et_bounds
            if ee > es and es >= t_min and ee <= t_max:
                start_ms, end_ms = es, ee
        duration_ms = end_ms - start_ms
        if duration_ms <= 0:
            continue
        area_sq_ms = _integral_velocity_sq_ms(times, velocities, start_ms, end_ms)
        pgmean = 4.0 * area_sq_ms / (100.0 * 100.0 * duration_ms)
        if pgmean <= 0:
            continue
        values.append(pgmean)
    if not values:
        return None
    return sum(values) / len(values)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def compute(dto: DopplerMeasurementDTO) -> DopplerResults:
    """Derive clinical Doppler metrics from raw markers."""

    e_cm_s = _find_peak_velocity(dto, "e")
    a_cm_s = _find_peak_velocity(dto, "a")
    e_prime_sept_cm_s = _find_peak_velocity(dto, "e_prime_sept", "e_sept", "esept")
    e_prime_lat_cm_s = _find_peak_velocity(dto, "e_prime_lat", "e_lat", "elat")
    a_prime_sept_cm_s = _find_peak_velocity(dto, "a_prime_sept", "a_prime", "a_sept", "aprime_sept", "a_prime_sept")
    a_prime_lat_cm_s = _find_peak_velocity(dto, "a_prime_lat", "a_prime", "a_lat", "aprime_lat", "a_prime_lat")
    a_prime_values = [v for v in (a_prime_sept_cm_s, a_prime_lat_cm_s) if v is not None]
    a_prime_avg = sum(a_prime_values) / len(a_prime_values) if a_prime_values else None

    e_a_ratio = _ratio(e_cm_s, a_cm_s)

    e_prime_values = [value for value in (e_prime_sept_cm_s, e_prime_lat_cm_s) if value is not None]
    e_prime_avg_cm_s = sum(e_prime_values) / len(e_prime_values) if e_prime_values else None
    e_over_e_prime = _ratio(e_cm_s, e_prime_avg_cm_s)
    e_over_e_prime_sept = _ratio(e_cm_s, e_prime_sept_cm_s)
    e_over_e_prime_lat = _ratio(e_cm_s, e_prime_lat_cm_s)

    e_prime_over_a_prime = _ratio(e_prime_avg_cm_s, a_prime_avg)

    s_prime_sept_cm_s = _find_peak_velocity(dto, "s_prime_sept", "s_sept", "ssept")
    s_prime_lat_cm_s = _find_peak_velocity(dto, "s_prime_lat", "s_lat", "slat")
    s_prime_rv_cm_s = _find_peak_velocity(dto, "s_prime_rv", "s_prime_rv", "rv_s_prime")

    dt_ms = _find_interval_duration_ms(dto, "dt")
    ivrt_ms = _find_interval_duration_ms(dto, "ivrt")
    at_ms = _find_interval_duration_ms(dto, "at")
    et_ms = _find_interval_duration_ms(dto, "et")

    vti_cm = _find_vti_cm(dto)
    vpeak_cm_s = _find_peak_velocity(dto, "vmax", "v_peak", "vmax")
    if vpeak_cm_s is None:
        vpeak_cm_s = _find_peak_velocity_from_trace(dto)
    tr_vmax_cm_s = _find_peak_velocity(dto, "tr_vmax", "trvmax", "tr")

    vmean_cm_s = None
    if vti_cm is not None:
        if et_ms is not None and et_ms > 0:
            vmean_cm_s = abs(vti_cm) / (et_ms / 1000.0)
        else:
            vmean_cm_s = _find_mean_velocity_from_trace(dto)

    pgpeak_mmhg = pressure_gradient_mmhg(vpeak_cm_s) if vpeak_cm_s is not None else None
    pgmean_mmhg = _find_mean_pressure_gradient_from_trace(dto)

    return DopplerResults(
        e_cm_s=e_cm_s,
        a_cm_s=a_cm_s,
        e_a_ratio=e_a_ratio,
        dt_ms=dt_ms,
        ivrt_ms=ivrt_ms,
        at_ms=at_ms,
        et_ms=et_ms,
        e_prime_sept_cm_s=e_prime_sept_cm_s,
        e_prime_lat_cm_s=e_prime_lat_cm_s,
        e_prime_avg_cm_s=e_prime_avg_cm_s,
        e_over_e_prime=e_over_e_prime,
        e_over_e_prime_sept=e_over_e_prime_sept,
        e_over_e_prime_lat=e_over_e_prime_lat,
        e_prime_over_a_prime=e_prime_over_a_prime,
        a_prime_sept_cm_s=a_prime_sept_cm_s,
        a_prime_lat_cm_s=a_prime_lat_cm_s,
        s_prime_sept_cm_s=s_prime_sept_cm_s,
        s_prime_lat_cm_s=s_prime_lat_cm_s,
        s_prime_rv_cm_s=s_prime_rv_cm_s,
        tr_vmax_cm_s=tr_vmax_cm_s,
        vti_cm=vti_cm,
        vpeak_cm_s=vpeak_cm_s,
        vmean_cm_s=vmean_cm_s,
        pgpeak_mmhg=pgpeak_mmhg,
        pgmean_mmhg=pgmean_mmhg,
    )
