"""Unit tests for Doppler metric calculations."""

from __future__ import annotations

import numpy as np

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
        peaks=(
            DopplerPeakMarker(label="vmax", time_ms=0.0, velocity_cm_s=300.0),
        ),
        intervals=(
            DopplerIntervalMarker(label="AT", start_time_ms=200.0, end_time_ms=500.0),
        ),
        traces=(
            DopplerTrace(
                label="vti",
                points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0)),
            ),
        ),
    )

    result = compute(dto)

    expected_vti = float(np.trapz([0.0, 200.0, 0.0], [0.0, 100.0, 200.0]))

    assert result.vpeak_cm_s == 300.0
    assert result.vti_cm == expected_vti
    assert result.pgpeak_mmhg == 36.0
    assert result.at_ms == 300.0
    assert result.vmean_cm_s == expected_vti / 0.3
    assert result.pgmean_mmhg == 4.0 * (result.vmean_cm_s / 100.0) ** 2


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
