"""Freshness of Doppler results (QH-1b.2, slice 3b: Doppler family).

A Doppler result (Vmax/VTI/repeats aggregates) is only as current as the
markers, traces and calibration state it was computed from. This module
compares the basis recorded with a result against the basis the study
provides now and returns the freshness state and reason codes defined in
:mod:`echo_personal_tool.domain.models.result_provenance`.

Rules (spec §5.2 matrix, rows "Допплер-повторы" and "Калибровка допплера"):

- no recorded basis (legacy result) → ``unverified``; the origin is not guessed;
- no current basis → ``unavailable``; the inputs cannot be re-resolved;
- same markers, traces, calibration and instance → ``fresh``;
- otherwise → ``stale`` with the reason(s): edited/added markers or traces
  (``input_changed``), a removed marker or trace (``source_missing``), or a
  changed calibration state (``calibration_changed``).

Marker identity is ``(label, measurement_id)`` with the measured values part
of the basis, so an in-place edit invalidates the result even though markers
— unlike contours — carry no content revision. Traces keep their full point
tuple: the basis is compared, not rendered, so exactness beats compactness
(the wiring slice decides how the basis is persisted).

Freshness is separate from QC: a ``fresh`` value is not thereby ``valid``.
The module is pure (no Qt, no I/O).
"""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO
from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState
from echo_personal_tool.domain.models.result_provenance import (
    REASON_CALIBRATION_CHANGED,
    REASON_INPUT_CHANGED,
    REASON_INPUT_MISSING,
    REASON_LEGACY_NO_PROVENANCE,
    REASON_SOURCE_MISSING,
    Freshness,
)


@dataclass(frozen=True)
class DopplerMarkerRef:
    """One peak or interval a Doppler result was computed from."""

    kind: str  # "peak" | "interval"
    label: str
    measurement_id: str
    values: tuple[float, ...]  # (time_ms, velocity_cm_s[, mode-hash]) | (start, end)
    mode: str = ""


@dataclass(frozen=True)
class DopplerTraceRef:
    """One VTI envelope a Doppler result was computed from."""

    label: str
    measurement_id: str
    mode: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class DopplerBasis:
    """The inputs a Doppler result was computed from."""

    instance_uid: str
    markers: tuple[DopplerMarkerRef, ...] = ()
    traces: tuple[DopplerTraceRef, ...] = ()
    calibration: DopplerCalibrationState | None = None


@dataclass(frozen=True)
class DopplerFreshness:
    """Freshness verdict for one Doppler result."""

    freshness: str
    reasons: tuple[str, ...] = ()

    @property
    def is_fresh(self) -> bool:
        return self.freshness == Freshness.FRESH.value


def doppler_basis_from_dto(
    dto: DopplerMeasurementDTO | None,
    calibration: DopplerCalibrationState | None,
    instance_uid: str = "",
) -> DopplerBasis:
    """Build the current Doppler basis from one instance's measurements."""
    markers: list[DopplerMarkerRef] = []
    traces: list[DopplerTraceRef] = []
    if dto is not None:
        for peak in dto.peaks:
            markers.append(
                DopplerMarkerRef("peak", peak.label, peak.measurement_id, (peak.time_ms, peak.velocity_cm_s), peak.mode)
            )
        for interval in dto.intervals:
            markers.append(
                DopplerMarkerRef(
                    "interval",
                    interval.label,
                    interval.measurement_id,
                    (interval.start_time_ms, interval.end_time_ms),
                )
            )
        for trace in dto.traces:
            traces.append(DopplerTraceRef(trace.label, trace.measurement_id, trace.mode, tuple(trace.points)))
    markers.sort(key=lambda ref: (ref.kind, ref.label, ref.measurement_id))
    traces.sort(key=lambda ref: (ref.label, ref.measurement_id))
    return DopplerBasis(
        instance_uid=instance_uid,
        markers=tuple(markers),
        traces=tuple(traces),
        calibration=calibration,
    )


def evaluate_doppler_freshness(recorded: DopplerBasis | None, current: DopplerBasis | None) -> DopplerFreshness:
    """Freshness of a result recorded with *recorded*, given the *current* basis."""
    if recorded is None:
        return DopplerFreshness(Freshness.UNVERIFIED.value, (REASON_LEGACY_NO_PROVENANCE,))
    if current is None:
        return DopplerFreshness(Freshness.UNAVAILABLE.value, (REASON_INPUT_MISSING,))
    if recorded == current:
        return DopplerFreshness(Freshness.FRESH.value)

    reasons: list[str] = []
    if recorded.instance_uid != current.instance_uid:
        reasons.append(REASON_INPUT_CHANGED)
    if recorded.calibration != current.calibration:
        reasons.append(REASON_CALIBRATION_CHANGED)
    before_markers = {(ref.kind, ref.label, ref.measurement_id): ref for ref in recorded.markers}
    after_markers = {(ref.kind, ref.label, ref.measurement_id): ref for ref in current.markers}
    for marker_key, old_marker in before_markers.items():
        new_marker = after_markers.get(marker_key)
        if new_marker is None:
            reasons.append(REASON_SOURCE_MISSING)
        elif new_marker != old_marker:
            reasons.append(REASON_INPUT_CHANGED)
    if any(marker_key not in before_markers for marker_key in after_markers):
        reasons.append(REASON_INPUT_CHANGED)
    before_traces = {(ref.label, ref.measurement_id): ref for ref in recorded.traces}
    after_traces = {(ref.label, ref.measurement_id): ref for ref in current.traces}
    for trace_key, old_trace in before_traces.items():
        new_trace = after_traces.get(trace_key)
        if new_trace is None:
            reasons.append(REASON_SOURCE_MISSING)
        elif new_trace != old_trace:
            reasons.append(REASON_INPUT_CHANGED)
    if any(trace_key not in before_traces for trace_key in after_traces):
        reasons.append(REASON_INPUT_CHANGED)
    if not reasons:
        reasons.append(REASON_INPUT_CHANGED)
    return DopplerFreshness(Freshness.STALE.value, tuple(dict.fromkeys(reasons)))
