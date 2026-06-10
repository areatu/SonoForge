"""Compute Doppler indices from marker DTOs."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.calculations.bernoulli import pressure_gradient_mmhg
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.measurements import DopplerResults


def _normalize_label(label: str) -> str:
    return label.strip().lower().replace("'", "").replace(" ", "_")


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


def _find_vti_cm(dto: DopplerMeasurementDTO) -> float | None:
    for trace in dto.traces:
        if _normalize_label(trace.label) != "vti":
            continue
        if len(trace.points) < 2:
            return None
        times = [point[0] for point in trace.points]
        velocities = [point[1] for point in trace.points]
        return float(np.trapz(velocities, times))
    return None


def compute(dto: DopplerMeasurementDTO) -> DopplerResults:
    """Derive clinical Doppler metrics from raw markers."""

    e_cm_s = _find_peak_velocity(dto, "e")
    a_cm_s = _find_peak_velocity(dto, "a")
    e_prime_sept_cm_s = _find_peak_velocity(dto, "e_sept", "esept")
    e_prime_lat_cm_s = _find_peak_velocity(dto, "e_lat", "elat")
    vpeak_cm_s = _find_peak_velocity(dto, "vmax", "v_peak", "vmax")

    e_a_ratio = e_cm_s / a_cm_s if e_cm_s is not None and a_cm_s not in (None, 0) else None

    e_prime_values = [
        value
        for value in (e_prime_sept_cm_s, e_prime_lat_cm_s)
        if value is not None
    ]
    e_prime_avg_cm_s = (
        sum(e_prime_values) / len(e_prime_values) if e_prime_values else None
    )
    e_over_e_prime = (
        e_cm_s / e_prime_avg_cm_s
        if e_cm_s is not None and e_prime_avg_cm_s not in (None, 0)
        else None
    )

    dt_ms = _find_interval_duration_ms(dto, "dt")
    ivrt_ms = _find_interval_duration_ms(dto, "ivrt")
    at_ms = _find_interval_duration_ms(dto, "at")

    vti_cm = _find_vti_cm(dto)
    pgpeak_mmhg = (
        pressure_gradient_mmhg(vpeak_cm_s) if vpeak_cm_s is not None else None
    )

    vmean_cm_s = None
    if vti_cm is not None and at_ms is not None and at_ms > 0:
        vmean_cm_s = vti_cm / (at_ms / 1000.0)

    pgmean_mmhg = (
        pressure_gradient_mmhg(vmean_cm_s) if vmean_cm_s is not None else None
    )

    return DopplerResults(
        e_cm_s=e_cm_s,
        a_cm_s=a_cm_s,
        e_a_ratio=e_a_ratio,
        dt_ms=dt_ms,
        ivrt_ms=ivrt_ms,
        at_ms=at_ms,
        e_prime_sept_cm_s=e_prime_sept_cm_s,
        e_prime_lat_cm_s=e_prime_lat_cm_s,
        e_prime_avg_cm_s=e_prime_avg_cm_s,
        e_over_e_prime=e_over_e_prime,
        vti_cm=vti_cm,
        vpeak_cm_s=vpeak_cm_s,
        vmean_cm_s=vmean_cm_s,
        pgpeak_mmhg=pgpeak_mmhg,
        pgmean_mmhg=pgmean_mmhg,
    )
