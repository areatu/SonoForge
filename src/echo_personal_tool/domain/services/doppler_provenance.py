"""Lineage of the Doppler and strain aggregates a report row is built from.

Issue 555 asks the «откуда значение» card to answer for *derived* values too:
a Vmax is often the mean of several peak measurements, a VTI the mean of
several traces, and a GLS a speckle-tracking result of one endocardial contour.
The markers and the contour already know their measurement identity, clip and
frame; this module keeps that knowledge at the calculation/report boundary
instead of letting the card say «происхождение не записано» about a study that
recorded everything.

The honesty rule is the same as for the other origins: when the markers or the
contour lineage are absent (old documents, results computed outside the app),
the value gets :func:`unrecorded_origin` with the ``unverified`` status.  A
source is never reconstructed from the current viewer state.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from echo_personal_tool.domain.doppler_catalog import (
    canonical_interval_label,
    canonical_peak_label,
    flow_site_from_peak_label,
    flow_site_from_trace_label,
    normalize_label,
    scale_velocity_for_display,
)
from echo_personal_tool.domain.measurement_catalog import format_measurement
from echo_personal_tool.domain.models.measurements import DopplerFlowResult, DopplerResults, StrainReport
from echo_personal_tool.domain.models.value_origin import (
    METHOD_DOPPLER_AGGREGATE,
    METHOD_STRAIN,
    ClipSource,
    OriginInput,
    ValueOrigin,
    derived_origin,
    unrecorded_origin,
)
from echo_personal_tool.domain.services.doppler_repeats import mean_of_last
from echo_personal_tool.domain.services.nomenclature import flow_measurement_id

#: Report measurement id → the peak labels that feed it.  The aliases mirror
#: the lookup in ``doppler_metrics`` so the card cites exactly the markers the
#: calculation actually averaged.
_PEAK_FIELDS: dict[str, tuple[str, ...]] = {
    "mv.e": ("e",),
    "mv.a": ("a",),
    "tdi.e_sept": ("e_prime_sept", "e_sept", "esept"),
    "tdi.e_lat": ("e_prime_lat", "e_lat", "elat"),
}

#: Report measurement id → canonical interval label.
_INTERVAL_FIELDS: dict[str, str] = {
    "mv.dt": "DT",
    "lv.ivrt": "IVRT",
    "mv.at": "AT",
    "doppler.et": "ET",
    "mv.pht": "MV PHT",
    "tv.pht": "TV PHT",
    "ar.pht": "AR PHT",
    "pr.pht": "PR PHT",
    "av.at": "AV AT",
    "av.et": "AV ET",
    "rvot.at": "RVOT AT",
}

#: Report measurement id → the result fields whose values it combines.
_COMPOSITE_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "mv.ea": (("E", "mv.e"), ("A", "mv.a")),
    "tdi.e_avg": (("e' sept", "tdi.e_sept"), ("e' lat", "tdi.e_lat")),
    "mv.e_e_avg": (("E", "mv.e"), ("e' avg", "tdi.e_avg")),
    "tdi.e_e_sept": (("E", "mv.e"), ("e' sept", "tdi.e_sept")),
    "tdi.e_e_lat": (("E", "mv.e"), ("e' lat", "tdi.e_lat")),
    "tdi.e_a_prime": (
        ("e' avg", "tdi.e_avg"),
        ("a' sept", "tdi.a_prime_sept"),
        ("a' lat", "tdi.a_prime_lat"),
    ),
}

#: Report/component id → ``DopplerResults`` attribute.
_FIELD_ATTRS: dict[str, str] = {
    "mv.e": "e_cm_s",
    "mv.a": "a_cm_s",
    "mv.ea": "e_a_ratio",
    "mv.dt": "dt_ms",
    "lv.ivrt": "ivrt_ms",
    "mv.at": "at_ms",
    "doppler.et": "et_ms",
    "tdi.e_sept": "e_prime_sept_cm_s",
    "tdi.e_lat": "e_prime_lat_cm_s",
    "tdi.e_avg": "e_prime_avg_cm_s",
    "tdi.a_prime_sept": "a_prime_sept_cm_s",
    "tdi.a_prime_lat": "a_prime_lat_cm_s",
    "mv.e_e_avg": "e_over_e_prime",
    "tdi.e_e_sept": "e_over_e_prime_sept",
    "tdi.e_e_lat": "e_over_e_prime_lat",
    "tdi.e_a_prime": "e_prime_over_a_prime",
    "mv.pht": "mv_pht_ms",
    "tv.pht": "tv_pht_ms",
    "ar.pht": "ar_pht_ms",
    "pr.pht": "pr_pht_ms",
    "av.at": "av_at_ms",
    "av.et": "av_et_ms",
    "rvot.at": "rvot_at_ms",
}

#: Unit of every component value (ratios have none).
_FIELD_UNITS: dict[str, str] = {
    "mv.e": "cm/s",
    "mv.a": "cm/s",
    "tdi.e_sept": "cm/s",
    "tdi.e_lat": "cm/s",
    "tdi.e_avg": "cm/s",
    "tdi.a_prime_sept": "cm/s",
    "tdi.a_prime_lat": "cm/s",
}

#: Component ids whose input is itself an aggregate of several measurements.
_DERIVED_INPUTS = frozenset({"tdi.e_avg"})


def _markers_context(markers: Iterable[Any]) -> tuple[tuple[ClipSource, ...], tuple[str, ...]]:
    """Clips and measurement identities of *markers*, without duplicates."""
    sources: list[ClipSource] = []
    ids: list[str] = []
    for marker in markers:
        source = ClipSource(
            str(getattr(marker, "sop_instance_uid", "") or ""),
            getattr(marker, "frame_index", None),
        )
        if source.has_clip and source not in sources:
            sources.append(source)
        measurement_id = str(getattr(marker, "measurement_id", "") or "")
        if measurement_id and measurement_id not in ids:
            ids.append(measurement_id)
    return tuple(sources), tuple(ids)


def _peaks(doppler: DopplerResults, aliases: tuple[str, ...]) -> tuple[Any, ...]:
    wanted = {normalize_label(alias) for alias in aliases}
    return tuple(peak for peak in doppler.peaks if normalize_label(peak.label) in wanted)


def _intervals(doppler: DopplerResults, canonical: str) -> tuple[Any, ...]:
    return tuple(interval for interval in doppler.intervals if canonical_interval_label(interval.label) == canonical)


def _peak_inputs(markers: Iterable[Any], measurement_id: str) -> tuple[OriginInput, ...]:
    inputs: list[OriginInput] = []
    for marker in markers:
        scaled, unit, _ = scale_velocity_for_display(
            abs(float(marker.velocity_cm_s)),
            marker.mode or None,
            measurement_id=measurement_id,
        )
        text = f"{format_measurement(measurement_id, scaled, unit)} {unit}".strip()
        inputs.append(OriginInput(id=canonical_peak_label(marker.label), value=text, source="measured"))
    return tuple(inputs)


def _interval_inputs(markers: Iterable[Any]) -> tuple[OriginInput, ...]:
    inputs: list[OriginInput] = []
    for marker in markers:
        duration_ms = abs(float(marker.end_time_ms) - float(marker.start_time_ms))
        text = f"{format_measurement('doppler.time', duration_ms, 'ms')} ms"
        inputs.append(
            OriginInput(
                id=canonical_interval_label(marker.label),
                value=text,
                source="measured",
            )
        )
    return tuple(inputs)


def _field_markers(doppler: DopplerResults, field_id: str) -> tuple[Any, ...]:
    """Every primary marker behind *field_id*, recursively for composites."""
    if field_id in _PEAK_FIELDS:
        return _peaks(doppler, _PEAK_FIELDS[field_id])
    if field_id in _INTERVAL_FIELDS:
        return _intervals(doppler, _INTERVAL_FIELDS[field_id])
    markers: list[Any] = []
    for _, component in _COMPOSITE_FIELDS.get(field_id, ()):
        for marker in _field_markers(doppler, component):
            if marker not in markers:
                markers.append(marker)
    return tuple(markers)


def _component_inputs(doppler: DopplerResults, field_id: str, label: str) -> tuple[OriginInput, ...]:
    attr = _FIELD_ATTRS.get(field_id)
    value = getattr(doppler, attr, None) if attr is not None else None
    if value is None:
        return ()
    unit = _FIELD_UNITS.get(field_id, "")
    text = format_measurement(field_id, float(value), unit)
    if unit:
        text = f"{text} {unit}"
    source = "derived" if field_id in _DERIVED_INPUTS or field_id in _COMPOSITE_FIELDS else "measured"
    return (OriginInput(id=label, value=text, source=source),)


def _origin_from_markers(markers: Iterable[Any], inputs: tuple[OriginInput, ...]) -> ValueOrigin:
    materialized = tuple(markers)
    sources, ids = _markers_context(materialized)
    if not materialized:
        return unrecorded_origin(METHOD_DOPPLER_AGGREGATE)
    return derived_origin(
        METHOD_DOPPLER_AGGREGATE,
        sources=sources,
        measurement_ids=ids,
        inputs=inputs,
    )


def doppler_value_origin(doppler: DopplerResults, measurement_id: str) -> ValueOrigin:
    """Origin of one generic Doppler row (``mv.e``, ``mv.dt``, ``hr``…)."""
    if measurement_id == "hr":
        markers = tuple(
            marker
            for marker in _intervals(doppler, canonical_interval_label("RR"))
            if abs(float(marker.end_time_ms) - float(marker.start_time_ms)) > 0
        )
        return _origin_from_markers(markers, _interval_inputs(markers))
    if measurement_id in _PEAK_FIELDS:
        markers = _peaks(doppler, _PEAK_FIELDS[measurement_id])
        return _origin_from_markers(markers, _peak_inputs(markers, measurement_id))
    if measurement_id in _INTERVAL_FIELDS:
        markers = _intervals(doppler, _INTERVAL_FIELDS[measurement_id])
        return _origin_from_markers(markers, _interval_inputs(markers))
    if measurement_id in _COMPOSITE_FIELDS:
        markers = _field_markers(doppler, measurement_id)
        if not markers:
            return unrecorded_origin(METHOD_DOPPLER_AGGREGATE)
        inputs: list[OriginInput] = []
        for label, component in _COMPOSITE_FIELDS[measurement_id]:
            inputs.extend(_component_inputs(doppler, component, label))
        return _origin_from_markers(markers, tuple(inputs))
    return unrecorded_origin(METHOD_DOPPLER_AGGREGATE)


def _flow_et_intervals(doppler: DopplerResults, site: str) -> tuple[Any, ...]:
    markers = _intervals(doppler, f"{site} ET")
    if not markers and site == "AV":
        markers = _intervals(doppler, "ET")
    return markers


def _flow_et_ms(doppler: DopplerResults, site: str) -> float | None:
    durations = (
        abs(float(marker.end_time_ms) - float(marker.start_time_ms)) for marker in _flow_et_intervals(doppler, site)
    )
    return mean_of_last(durations)


def _flow_peak_inputs(flow: DopplerFlowResult, measurement_id: str) -> tuple[OriginInput, ...]:
    if flow.vmax_cm_s is None:
        return ()
    scaled, unit, _ = scale_velocity_for_display(
        abs(float(flow.vmax_cm_s)),
        flow.mode or None,
        measurement_id=measurement_id,
    )
    text = f"{format_measurement(measurement_id, scaled, unit)} {unit}".strip()
    source = "measured" if flow.vmax_repeats else "derived"
    return (OriginInput(id="Vmax", value=text, source=source),)


def _flow_vti_inputs(flow: DopplerFlowResult) -> tuple[OriginInput, ...]:
    if flow.vti_cm is None:
        return ()
    measurement_id = flow_measurement_id(flow.site, "VTI")
    return (
        OriginInput(
            id="VTI",
            value=f"{format_measurement(measurement_id, abs(float(flow.vti_cm)), 'cm')} cm",
            source="derived",
        ),
    )


def doppler_flow_origin(
    doppler: DopplerResults,
    flow: DopplerFlowResult,
    kind: str,
) -> ValueOrigin:
    """Origin of one valve/flow row (``Vmax``, ``PGmax``, ``VTI``…).

    ``kind`` is the stable suffix of ``flow_measurement_id``; the row's
    published measurement id differs per site, so the caller passes the kind
    instead of parsing it back out of catalog ids.
    """
    site = flow.site
    peaks = tuple(peak for peak in doppler.peaks if flow_site_from_peak_label(peak.label) == site)
    traces = tuple(trace for trace in doppler.traces if flow_site_from_trace_label(trace.label) == site)
    et_markers = _flow_et_intervals(doppler, site)
    if kind in {"Vmax", "PGmax"}:
        markers = peaks or traces
        if not markers:
            return unrecorded_origin(METHOD_DOPPLER_AGGREGATE)
        if kind == "Vmax":
            value_inputs = _peak_inputs(markers, flow_measurement_id(site, "Vmax")) if peaks else ()
        else:
            value_inputs = _flow_peak_inputs(flow, flow_measurement_id(site, "Vmax"))
        return _origin_from_markers(markers, value_inputs)
    if kind == "VTI":
        return _origin_from_markers(traces, ())
    if kind in {"Vmean", "PGmean"}:
        markers = traces + et_markers
        if not markers:
            return unrecorded_origin(METHOD_DOPPLER_AGGREGATE)
        # Vmean = VTI / ET; PGmean is the integral of v(t)² over the same
        # window, so VTI is only a numeric input of Vmean.  In both cases the
        # traces themselves are named by ``sources``/``measurement_ids``.
        inputs = list(_flow_vti_inputs(flow)) if kind == "Vmean" else []
        et_ms = _flow_et_ms(doppler, site)
        if et_ms is not None:
            inputs.append(
                OriginInput(
                    id="ET",
                    value=f"{format_measurement('doppler.time', et_ms, 'ms')} ms",
                    source="measured",
                )
            )
        return _origin_from_markers(markers, tuple(inputs))
    return unrecorded_origin(METHOD_DOPPLER_AGGREGATE)


def strain_value_origin(
    strain: StrainReport,
    measurement_id: str,
    *,
    view: str = "",
) -> ValueOrigin:
    """Origin of a per-view GLS row or of the multi-view average (``GLS_AV``)."""
    lineage = dict(strain.lineage_by_view)
    values = dict(strain.gls_by_view)
    if view:
        source = lineage.get(view)
        if source is None or not source.recorded:
            return unrecorded_origin(METHOD_STRAIN)
        return derived_origin(
            METHOD_STRAIN,
            sources=(ClipSource(source.sop_instance_uid, source.frame_index),),
            measurement_ids=(source.measurement_id,),
        )
    sources: list[ClipSource] = []
    ids: list[str] = []
    inputs: list[OriginInput] = []
    for name in strain.views_valid or tuple(values):
        source = lineage.get(name)
        if source is None or not source.recorded:
            continue
        clip = ClipSource(source.sop_instance_uid, source.frame_index)
        if clip.has_clip and clip not in sources:
            sources.append(clip)
        if source.measurement_id and source.measurement_id not in ids:
            ids.append(source.measurement_id)
        value = values.get(name)
        if value is not None:
            inputs.append(OriginInput(id=f"GLS {name}", value=f"{value:.1f} %", source="derived"))
    if not sources and not ids:
        return unrecorded_origin(METHOD_STRAIN)
    return derived_origin(
        METHOD_STRAIN,
        sources=tuple(sources),
        measurement_ids=tuple(ids),
        inputs=tuple(inputs),
    )
