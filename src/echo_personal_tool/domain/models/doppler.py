"""Domain models for Doppler measurements."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DopplerPeakMarker:
    label: str
    time_ms: float
    velocity_cm_s: float


@dataclass(frozen=True)
class DopplerIntervalMarker:
    label: str
    start_time_ms: float
    end_time_ms: float


@dataclass(frozen=True)
class DopplerTrace:
    label: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class DopplerMeasurementDTO:
    peaks: tuple[DopplerPeakMarker, ...]
    intervals: tuple[DopplerIntervalMarker, ...]
    traces: tuple[DopplerTrace, ...]
