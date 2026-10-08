"""Compute Doppler indices from marker DTOs."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.calculations.bernoulli import pressure_gradient_mmhg
from echo_personal_tool.domain.doppler_catalog import (
    FLOW_SITES,
    flow_site_from_peak_label,
    flow_site_from_trace_label,
)
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.measurements import DopplerFlowResult, DopplerResults
from echo_personal_tool.domain.services.doppler_repeats import REPORT_WINDOW, mean_of_last

_np_trapezoid = getattr(np, "trapezoid", None) or np.trapz


def _normalize_label(label: str) -> str:
    return label.strip().lower().replace("'", "_prime").replace("′", "_prime").replace(" ", "_")


def _matching_peaks(dto: DopplerMeasurementDTO, labels: set[str]) -> list[float]:
    """Magnitudes of every measurement whose normalized label is in *labels*.

    Storage keeps the signed calibration truth (below-baseline jets are
    negative); every clinical read — ratios, criteria, norms — uses the
    magnitude, so the sign is normalized here, at the compute boundary (Э2).
    """
    return [abs(peak.velocity_cm_s) for peak in dto.peaks if _normalize_label(peak.label) in labels]


def _find_peak_velocity(dto: DopplerMeasurementDTO, *labels: str) -> float | None:
    """Mean of the most recent measurements of one peak parameter (D-23).

    Repeated measurements (several beats, atrial fibrillation) are stored side
    by side and the protocol uses the mean of the last three.  With a single
    measurement the result is that measurement, so legacy data is unchanged.
    """
    wanted = {_normalize_label(label) for label in labels}
    return mean_of_last(_matching_peaks(dto, wanted))


def _find_interval_duration_ms(dto: DopplerMeasurementDTO, label: str) -> float | None:
    wanted = _normalize_label(label)
    return mean_of_last(
        abs(interval.end_time_ms - interval.start_time_ms)
        for interval in dto.intervals
        if _normalize_label(interval.label) == wanted
    )


def _find_interval_bounds_ms(dto: DopplerMeasurementDTO, label: str) -> tuple[float, float] | None:
    wanted = _normalize_label(label)
    for interval in reversed(dto.intervals):
        if _normalize_label(interval.label) == wanted:
            return tuple(sorted((interval.start_time_ms, interval.end_time_ms)))
    return None


def _site_traces(dto: DopplerMeasurementDTO, site: str | None, *, window: int = REPORT_WINDOW):
    """The most recent *window* VTI traces of one site (or of every site)."""
    matching = [
        trace
        for trace in dto.traces
        if flow_site_from_trace_label(trace.label) is not None
        and (site is None or flow_site_from_trace_label(trace.label) == site)
        and len(trace.points) >= 2
    ]
    return matching[-window:]


def _find_vti_cm(dto: DopplerMeasurementDTO, site: str | None = None) -> float | None:
    """Mean of the most recent VTI traces of a site.

    Matches any trace whose label resolves to a flow site (``VTI``, ``VTI MV``,
    ``VTI MR``, ``VTI AR``, ``VTI TR``, ``VTI PR``, …), so valve-specific
    traces committed by the UI are measured too.  Multi-beat traces produced by
    the auto-trace flow each cover one cardiac cycle; averaging them yields the
    beat-averaged VTI.  Under D-23 at most the last
    :data:`~echo_personal_tool.domain.services.doppler_repeats.REPORT_WINDOW`
    traces enter the mean.  A single manual trace (the common case) averages to
    itself.

    Trace timestamps are milliseconds, so the raw trapezoidal integral of
    (cm/s) over (ms) is 1000x too large; dividing by 1000 yields cm.
    """
    values: list[float] = []
    for trace in _site_traces(dto, site):
        times = [point[0] for point in trace.points]
        velocities = [point[1] for point in trace.points]
        values.append(float(_np_trapezoid(velocities, times)) / 1000.0)
    if not values:
        return None
    return abs(sum(values) / len(values))


def _find_vti_repeats(dto: DopplerMeasurementDTO, site: str | None = None) -> int:
    return len(_site_traces(dto, site))


def _find_peak_velocity_from_trace(dto: DopplerMeasurementDTO, site: str | None = None) -> float | None:
    """Vpeak fallback: mean of the per-trace peaks of the site.

    Used when no explicit Vmax peak marker is placed.  For regurgitation
    traces (negative velocities) the absolute value is taken so the peak
    magnitude is reported correctly, and repeated beat traces are averaged
    like every other repeated parameter (D-23).
    """
    candidates = [max(abs(point[1]) for point in trace.points) for trace in _site_traces(dto, site)]
    return mean_of_last(candidates) if candidates else None


def _find_mean_velocity_from_trace(dto: DopplerMeasurementDTO, site: str | None = None) -> float | None:
    """Vmean from the site traces: mean of per-trace |VTI| / duration.

    Falls back to trace-based duration when no ET interval marker is
    available. Returns ``None`` when a trace has fewer than 2 points or the
    duration is zero. Uses ``abs(VTI)`` so regurgitation traces (negative
    velocities) still yield a positive mean velocity.
    """
    values: list[float] = []
    for trace in _site_traces(dto, site):
        times = [point[0] for point in trace.points]
        velocities = [point[1] for point in trace.points]
        duration_s = (max(times) - min(times)) / 1000.0
        if duration_s <= 0:
            continue
        vti = abs(float(_np_trapezoid(velocities, times)) / 1000.0)
        if vti <= 0:
            continue
        values.append(vti / duration_s)
    return mean_of_last(values) if values else None


def _integral_velocity_sq_ms(times: list[float], velocities: list[float], start_ms: float, end_ms: float) -> float:
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


def _find_mean_pressure_gradient_from_trace(dto: DopplerMeasurementDTO, site: str | None = None) -> float | None:
    """ASE/EACVI PGmean = (1/T)·∫4·v(t)²dt, averaged over the VTI traces.

    The instantaneous Bernoulli gradient is 4·(v/100)² with v in cm/s; this
    is averaged (not derived from Vmean) because Bernoulli is nonlinear:
    4·Vmean² underestimates the true mean gradient.

    The integration window is the newest ET interval when it is fully covered
    by a trace (consistent with Vmean = VTI / ET), otherwise the full trace
    span.  Like every repeated parameter, only the most recent
    :data:`~echo_personal_tool.domain.services.doppler_repeats.REPORT_WINDOW`
    traces of the site enter the average (D-23).
    """
    et_bounds = _find_interval_bounds_ms(dto, f"{site} ET") if site is not None else None
    if et_bounds is None and site in (None, "AV"):
        et_bounds = _find_interval_bounds_ms(dto, "et")
    values: list[float] = []
    for trace in _site_traces(dto, site):
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


def _site_mode(dto: DopplerMeasurementDTO, site: str) -> str:
    """Acquisition mode of the newest measurement of a site (display hint).

    Peaks win over traces because Vmax display follows the peak markers;
    the trace mode only matters for the trace-derived Vmax fallback.  Empty
    when no contributing measurement captured a mode (legacy records).
    """
    for peak in reversed(dto.peaks):
        if flow_site_from_peak_label(peak.label) == site and peak.mode:
            return peak.mode
    for trace in reversed(dto.traces):
        if flow_site_from_trace_label(trace.label) == site and trace.mode:
            return trace.mode
    return ""


def _compute_flow_results(dto: DopplerMeasurementDTO) -> tuple[DopplerFlowResult, ...]:
    """Compute independent values for every measured valve/flow region."""

    measured_sites = {
        site for site in (flow_site_from_peak_label(peak.label) for peak in dto.peaks) if site is not None
    }
    measured_sites.update(
        site for site in (flow_site_from_trace_label(trace.label) for trace in dto.traces) if site is not None
    )

    results: list[DopplerFlowResult] = []
    for site in FLOW_SITES:
        if site not in measured_sites:
            continue
        site_peaks = [
            abs(float(peak.velocity_cm_s)) for peak in dto.peaks if flow_site_from_peak_label(peak.label) == site
        ]
        vmax_cm_s = mean_of_last(site_peaks)
        if vmax_cm_s is None:
            vmax_cm_s = _find_peak_velocity_from_trace(dto, site)
        vti_cm = _find_vti_cm(dto, site)
        et_ms = _find_interval_duration_ms(dto, f"{site} ET")
        if et_ms is None and site == "AV":
            et_ms = _find_interval_duration_ms(dto, "ET")
        if vti_cm is not None and et_ms is not None and et_ms > 0:
            vmean_cm_s = abs(vti_cm) / (et_ms / 1000.0)
        else:
            vmean_cm_s = _find_mean_velocity_from_trace(dto, site)
        results.append(
            DopplerFlowResult(
                site=site,
                vmax_cm_s=vmax_cm_s,
                pgmax_mmhg=pressure_gradient_mmhg(vmax_cm_s) if vmax_cm_s is not None else None,
                vti_cm=vti_cm,
                vmean_cm_s=vmean_cm_s,
                pgmean_mmhg=_find_mean_pressure_gradient_from_trace(dto, site),
                vmax_repeats=len(site_peaks),
                vti_repeats=_find_vti_repeats(dto, site),
                mode=_site_mode(dto, site),
            )
        )
    return tuple(results)


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
    mv_pht_ms = _find_interval_duration_ms(dto, "MV PHT")
    if mv_pht_ms is None:
        mv_pht_ms = _find_interval_duration_ms(dto, "PHT")
    tv_pht_ms = _find_interval_duration_ms(dto, "TV PHT")
    ar_pht_ms = _find_interval_duration_ms(dto, "AR PHT")
    pr_pht_ms = _find_interval_duration_ms(dto, "PR PHT")
    av_at_ms = _find_interval_duration_ms(dto, "AV AT")
    av_et_ms = _find_interval_duration_ms(dto, "AV ET")
    rvot_at_ms = _find_interval_duration_ms(dto, "RVOT AT")
    mr_dpdt_ms = _find_interval_duration_ms(dto, "MR dP/dt")
    tr_dpdt_ms = _find_interval_duration_ms(dto, "TR dP/dt")

    flow_results = _compute_flow_results(dto)
    vti_cm = _find_vti_cm(dto)
    vpeak_cm_s = _find_peak_velocity(dto, "vmax", "v_peak", "vmax")
    av_flow = next((flow for flow in flow_results if flow.site == "AV"), None)
    if vpeak_cm_s is None and av_flow is not None:
        vpeak_cm_s = av_flow.vmax_cm_s
    if vpeak_cm_s is None:
        vpeak_cm_s = _find_peak_velocity_from_trace(dto)
    tr_vmax_cm_s = _find_peak_velocity(dto, "tr_vmax", "trvmax", "tr")
    tr_flow = next((flow for flow in flow_results if flow.site == "TR"), None)
    if tr_vmax_cm_s is None and tr_flow is not None:
        tr_vmax_cm_s = tr_flow.vmax_cm_s

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
        flow_results=flow_results,
        mv_pht_ms=mv_pht_ms,
        tv_pht_ms=tv_pht_ms,
        ar_pht_ms=ar_pht_ms,
        pr_pht_ms=pr_pht_ms,
        av_at_ms=av_at_ms,
        av_et_ms=av_et_ms,
        rvot_at_ms=rvot_at_ms,
        mr_dpdt_ms=mr_dpdt_ms,
        tr_dpdt_ms=tr_dpdt_ms,
    )
