"""Domain models for Doppler measurements."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DopplerPeakMarker:
    """One measured peak velocity.

    ``measurement_id`` identifies the *measurement act*, not the patient: it
    lets repeated measurements of the same parameter live side by side in one
    document (decision D-23) while an edit of an existing marker updates it in
    place.  Legacy records written before D-23 have an empty id and keep the
    old replace-by-label behavior.
    """

    label: str
    time_ms: float
    velocity_cm_s: float
    measurement_id: str = ""


@dataclass(frozen=True)
class DopplerIntervalMarker:
    label: str
    start_time_ms: float
    end_time_ms: float
    measurement_id: str = ""


@dataclass(frozen=True)
class DopplerTrace:
    label: str
    points: tuple[tuple[float, float], ...]
    measurement_id: str = ""


@dataclass(frozen=True)
class DopplerMeasurementDTO:
    peaks: tuple[DopplerPeakMarker, ...]
    intervals: tuple[DopplerIntervalMarker, ...]
    traces: tuple[DopplerTrace, ...]
