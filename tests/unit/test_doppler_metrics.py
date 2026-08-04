"""Unit tests for Doppler metric calculations."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)


def test_compute_full_diastolic_scenario() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker(label="E", time_ms=100.0, velocity_cm_s=90.0),
            DopplerPeakMarker(label="A", time_ms=220.0, velocity_cm_s=45.0),
            DopplerPeakMarker(label="e_sept", time_ms=150.0, velocity_cm_s=10.0),
            DopplerPeakMarker(label="e_lat", time_ms=155.0, velocity_cm_s=14.0),
        ),
        intervals=(
            DopplerIntervalMarker(label="DT", start_time_ms=80.0, end_time_ms=180.0),
            DopplerIntervalMarker(label="IVRT", start_time_ms=40.0, end_time_ms=110.0),
        ),
        traces=(),
    )

    result = compute(dto)

    assert result.e_cm_s == 90.0
    assert result.a_cm_s == 45.0
    assert result.e_a_ratio == 2.0
    assert result.dt_ms == 100.0
    assert result.ivrt_ms == 70.0
    assert result.e_prime_sept_cm_s == 10.0
    assert result.e_prime_lat_cm_s == 14.0
    assert result.e_prime_avg_cm_s == 12.0
    assert result.e_over_e_prime == 7.5
    assert result.vti_cm is None
    assert result.vpeak_cm_s is None
    assert result.vmean_cm_s is None
    assert result.pgpeak_mmhg is None
    assert result.pgmean_mmhg is None


def test_compute_cw_scenario() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="vmax", time_ms=0.0, velocity_cm_s=300.0),),
        intervals=(DopplerIntervalMarker(label="AT", start_time_ms=200.0, end_time_ms=500.0),),
        traces=(
            DopplerTrace(
                label="vti",
                points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0)),
            ),
        ),
    )

    result = compute(dto)

    expected_vti = float(np.trapz([0.0, 200.0, 0.0], [0.0, 100.0, 200.0])) / 1000.0

    assert result.vpeak_cm_s == 300.0
    assert result.vti_cm == expected_vti
    assert result.pgpeak_mmhg == 36.0
    assert result.at_ms == 300.0
    assert result.vmean_cm_s == expected_vti / 0.3
    assert result.pgmean_mmhg == 4.0 * (result.vmean_cm_s / 100.0) ** 2


def test_compute_vti_averaged_across_multiple_traces() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(),
        intervals=(),
        traces=(
            DopplerTrace(label="vti", points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0))),
            DopplerTrace(label="vti", points=((300.0, 0.0), (400.0, 100.0), (500.0, 0.0))),
        ),
    )

    result = compute(dto)

    vti1 = float(np.trapz([0.0, 200.0, 0.0], [0.0, 100.0, 200.0])) / 1000.0
    vti2 = float(np.trapz([0.0, 100.0, 0.0], [300.0, 400.0, 500.0])) / 1000.0
    assert result.vti_cm == pytest.approx((vti1 + vti2) / 2.0)


@pytest.mark.parametrize(
    ("trace_label",),
    [
        ("VTI MV",),
        ("VTI MR",),
        ("VTI AV",),
        ("VTI AR",),
        ("VTI TR",),
        ("VTI PR",),
    ],
)
def test_compute_vti_recognizes_valve_specific_labels(trace_label: str) -> None:
    """VTI must be computed for the valve-specific trace labels used by the UI."""
    dto = DopplerMeasurementDTO(
        peaks=(),
        intervals=(),
        traces=(DopplerTrace(label=trace_label, points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0))),),
    )

    result = compute(dto)

    expected_vti = float(np.trapz([0.0, 200.0, 0.0], [0.0, 100.0, 200.0])) / 1000.0
    assert result.vti_cm == pytest.approx(expected_vti)


def test_compute_vti_units_are_cm_for_ms_times() -> None:
    """VTI must be in cm even though trace timestamps are in ms.

    A triangular envelope with base 200 ms and peak 200 cm/s has a true
    VTI of 0.5 * 0.2 s * 200 cm/s = 20 cm. The raw trapezoidal integral
    over ms timestamps is 1000x larger, so the implementation must divide
    by 1000.
    """
    dto = DopplerMeasurementDTO(
        peaks=(),
        intervals=(),
        traces=(DopplerTrace(label="vti", points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0))),),
    )

    result = compute(dto)

    assert result.vti_cm == pytest.approx(20.0)


def test_compute_vti_ignores_non_vti_trace_labels() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(),
        intervals=(),
        traces=(DopplerTrace(label="PeakEnvelope", points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0))),),
    )

    result = compute(dto)

    assert result.vti_cm is None


def test_compute_empty_dto_returns_all_none() -> None:
    result = compute(DopplerMeasurementDTO(peaks=(), intervals=(), traces=()))

    assert result.e_cm_s is None
    assert result.a_cm_s is None
    assert result.e_a_ratio is None
    assert result.dt_ms is None
    assert result.ivrt_ms is None
    assert result.at_ms is None
    assert result.e_prime_sept_cm_s is None
    assert result.e_prime_lat_cm_s is None
    assert result.e_prime_avg_cm_s is None
    assert result.e_over_e_prime is None
    assert result.vti_cm is None
    assert result.vpeak_cm_s is None
    assert result.vmean_cm_s is None
    assert result.pgpeak_mmhg is None
    assert result.pgmean_mmhg is None
