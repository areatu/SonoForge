"""Unit tests for Doppler domain models."""

from __future__ import annotations

import dataclasses

import pytest

from echo_personal_tool.domain.models import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)


def test_doppler_peak_marker_creation() -> None:
    marker = DopplerPeakMarker(label="E", time_ms=120.0, velocity_cm_s=85.5)

    assert marker.label == "E"
    assert marker.time_ms == 120.0
    assert marker.velocity_cm_s == 85.5


def test_doppler_interval_marker_creation() -> None:
    marker = DopplerIntervalMarker(label="DT", start_time_ms=100.0, end_time_ms=250.0)

    assert marker.label == "DT"
    assert marker.start_time_ms == 100.0
    assert marker.end_time_ms == 250.0


def test_doppler_trace_creation() -> None:
    trace = DopplerTrace(
        label="VTI",
        points=((0.0, 10.0), (50.0, 20.0), (100.0, 5.0)),
    )

    assert trace.label == "VTI"
    assert trace.points == ((0.0, 10.0), (50.0, 20.0), (100.0, 5.0))


def test_doppler_measurement_dto_empty() -> None:
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=())

    assert dto.peaks == ()
    assert dto.intervals == ()
    assert dto.traces == ()


def test_doppler_measurement_dto_populated() -> None:
    peak = DopplerPeakMarker(label="A", time_ms=200.0, velocity_cm_s=60.0)
    interval = DopplerIntervalMarker(label="IVRT", start_time_ms=300.0, end_time_ms=380.0)
    trace = DopplerTrace(label="VTI", points=((0.0, 0.0), (10.0, 15.0)))

    dto = DopplerMeasurementDTO(
        peaks=(peak,),
        intervals=(interval,),
        traces=(trace,),
    )

    assert dto.peaks == (peak,)
    assert dto.intervals == (interval,)
    assert dto.traces == (trace,)


@pytest.mark.parametrize(
    "instance",
    [
        DopplerPeakMarker(label="Vmax", time_ms=0.0, velocity_cm_s=100.0),
        DopplerIntervalMarker(label="AT", start_time_ms=0.0, end_time_ms=50.0),
        DopplerTrace(label="VTI", points=((0.0, 0.0),)),
        DopplerMeasurementDTO(peaks=(), intervals=(), traces=()),
    ],
)
def test_doppler_models_are_frozen(instance: object) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        instance.label = "mutated"  # type: ignore[attr-defined]
