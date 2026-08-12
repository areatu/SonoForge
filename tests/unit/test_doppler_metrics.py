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

_np_trapezoid = getattr(np, "trapezoid", np.trapz)


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
        intervals=(
            DopplerIntervalMarker(label="AT", start_time_ms=200.0, end_time_ms=500.0),
            DopplerIntervalMarker(label="ET", start_time_ms=200.0, end_time_ms=500.0),
        ),
        traces=(
            DopplerTrace(
                label="vti",
                points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0)),
            ),
        ),
    )

    result = compute(dto)

    expected_vti = float(_np_trapezoid([0.0, 200.0, 0.0], [0.0, 100.0, 200.0])) / 1000.0

    assert result.vpeak_cm_s == 300.0
    assert result.vti_cm == expected_vti
    assert result.pgpeak_mmhg == 36.0
    assert result.at_ms == 300.0
    assert result.et_ms == 300.0
    assert result.vmean_cm_s == expected_vti / 0.3
    assert result.pgmean_mmhg == pytest.approx(4.0 * (200.0 / 100.0) ** 2 / 3.0)


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

    vti1 = float(_np_trapezoid([0.0, 200.0, 0.0], [0.0, 100.0, 200.0])) / 1000.0
    vti2 = float(_np_trapezoid([0.0, 100.0, 0.0], [300.0, 400.0, 500.0])) / 1000.0
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

    expected_vti = float(_np_trapezoid([0.0, 200.0, 0.0], [0.0, 100.0, 200.0])) / 1000.0
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


def test_compute_vpeak_from_trace_when_no_marker() -> None:
    """Vpeak falls back to max(|v|) across VTI traces when no Vmax marker is placed."""
    trace = DopplerTrace(
        label="VTI AV",
        points=((0.0, 50.0), (100.0, 120.0), (200.0, 80.0), (300.0, 30.0)),
    )
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))
    result = compute(dto)

    assert result.vpeak_cm_s == 120.0
    assert result.pgpeak_mmhg == pytest.approx(4.0 * (120.0 / 100.0) ** 2)


def test_compute_vpeak_uses_marker_over_trace() -> None:
    """Explicit Vmax marker takes priority over trace-derived Vpeak."""
    trace = DopplerTrace(
        label="VTI AV",
        points=((0.0, 50.0), (100.0, 120.0), (200.0, 80.0), (300.0, 30.0)),
    )
    peak = DopplerPeakMarker(label="Vmax", time_ms=100.0, velocity_cm_s=150.0)
    dto = DopplerMeasurementDTO(peaks=(peak,), intervals=(), traces=(trace,))
    result = compute(dto)

    assert result.vpeak_cm_s == 150.0
    assert result.pgpeak_mmhg == pytest.approx(4.0 * (150.0 / 100.0) ** 2)


def test_compute_vpeak_from_trace_negative_velocities() -> None:
    """For regurgitation traces Vpeak uses max(|v|) so negative flow is reported correctly."""
    trace = DopplerTrace(
        label="VTI AR",
        points=((0.0, -30.0), (100.0, -150.0), (200.0, -40.0)),
    )
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))
    result = compute(dto)

    assert result.vpeak_cm_s == 150.0


def test_compute_vmean_from_trace_duration_when_no_et() -> None:
    """Vmean falls back to VTI / trace duration when no ET interval marker is present."""
    trace = DopplerTrace(
        label="vti",
        points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0)),
    )
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))
    result = compute(dto)

    expected_vti = float(_np_trapezoid([0.0, 200.0, 0.0], [0.0, 100.0, 200.0])) / 1000.0
    expected_vmean = expected_vti / 0.2
    assert result.vmean_cm_s == pytest.approx(expected_vmean)
    assert result.pgmean_mmhg == pytest.approx(4.0 * (200.0 / 100.0) ** 2 / 3.0)


def test_compute_vmean_uses_et_over_trace_duration() -> None:
    """ET interval takes priority over trace duration for Vmean."""
    trace = DopplerTrace(
        label="vti",
        points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0)),
    )
    et = DopplerIntervalMarker(label="ET", start_time_ms=0.0, end_time_ms=300.0)
    dto = DopplerMeasurementDTO(peaks=(), intervals=(et,), traces=(trace,))
    result = compute(dto)

    expected_vti = float(_np_trapezoid([0.0, 200.0, 0.0], [0.0, 100.0, 200.0])) / 1000.0
    expected_vmean = expected_vti / 0.3
    assert result.vmean_cm_s == pytest.approx(expected_vmean)


def test_compute_pgmean_integrates_instantaneous_gradient_not_vmean_sq() -> None:
    """PGmean is the time-average of 4·v(t)², not 4·Vmean² (Bernoulli is nonlinear).

    A symmetric triangular envelope with peak 200 cm/s has mean v² = peak²/3,
    so PGmean = 4 × (2 m/s)² / 3 = 16/3 mmHg, higher than 4·(VTI/ET)².
    """
    trace = DopplerTrace(label="vti", points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0)))
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))
    result = compute(dto)

    assert result.pgmean_mmhg == pytest.approx(16.0 / 3.0)


def test_compute_pgmean_uses_et_window_when_fully_covered() -> None:
    """ET bounds (when fully inside the trace span) limit the gradient average."""
    trace = DopplerTrace(
        label="vti",
        points=((0.0, 0.0), (100.0, 0.0), (200.0, 200.0), (300.0, 0.0), (400.0, 0.0)),
    )
    et = DopplerIntervalMarker(label="ET", start_time_ms=100.0, end_time_ms=300.0)
    dto = DopplerMeasurementDTO(peaks=(), intervals=(et,), traces=(trace,))
    result = compute(dto)

    assert result.pgmean_mmhg == pytest.approx(16.0 / 3.0)


def test_compute_pgmean_falls_back_to_full_trace_when_et_not_covered() -> None:
    """ET that lies outside the trace span does not restrict the gradient average."""
    trace = DopplerTrace(label="vti", points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0)))
    et = DopplerIntervalMarker(label="ET", start_time_ms=400.0, end_time_ms=600.0)
    dto = DopplerMeasurementDTO(peaks=(), intervals=(et,), traces=(trace,))
    result = compute(dto)

    assert result.vmean_cm_s == pytest.approx(20.0 / 0.2)
    assert result.pgmean_mmhg == pytest.approx(16.0 / 3.0)


def test_compute_pgmean_from_negative_regurgitation_trace() -> None:
    """v² makes the instantaneous gradient positive for regurgitation traces."""
    trace = DopplerTrace(label="VTI TR", points=((0.0, 0.0), (100.0, -400.0), (200.0, 0.0)))
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))
    result = compute(dto)

    expected_vti = float(_np_trapezoid([0.0, -400.0, 0.0], [0.0, 100.0, 200.0])) / 1000.0
    assert result.vmean_cm_s == pytest.approx(abs(expected_vti) / 0.2)
    assert result.pgmean_mmhg == pytest.approx(4.0 * (400.0 / 100.0) ** 2 / 3.0)


def test_compute_vmean_none_when_trace_has_insufficient_points() -> None:
    """Vmean from trace requires at least 2 points to compute duration."""
    trace = DopplerTrace(label="vti", points=((0.0, 100.0),))
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))
    result = compute(dto)

    assert result.vmean_cm_s is None
    assert result.pgmean_mmhg is None


def test_compute_vpeak_none_when_traces_are_empty() -> None:
    """Vpeak is None when there are no traces and no markers."""
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=())
    result = compute(dto)

    assert result.vpeak_cm_s is None
    assert result.pgpeak_mmhg is None


def test_compute_vmean_none_when_vti_is_zero() -> None:
    """Vmean is None when VTI is zero or negative."""
    trace = DopplerTrace(label="vti", points=((0.0, 0.0), (200.0, 0.0)))
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))
    result = compute(dto)

    assert result.vmean_cm_s is None
    assert result.pgmean_mmhg is None


def test_compute_trace_label_case_insensitive_for_vpeak() -> None:
    """Vpeak from trace matches labels case-insensitively."""
    trace = DopplerTrace(label="vti mv", points=((0.0, 0.0), (100.0, 140.0), (200.0, 0.0)))
    dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))
    result = compute(dto)

    assert result.vpeak_cm_s == 140.0


def test_compute_trace_label_valve_prefix_ignored_for_vpeak() -> None:
    """Vpeak from trace works with valve-specific VTI labels."""
    for label in ("VTI MV", "VTI MR", "VTI AV", "VTI AR", "VTI TR", "VTI PR"):
        trace = DopplerTrace(
            label=label,
            points=((0.0, 0.0), (100.0, 160.0), (200.0, 0.0)),
        )
        dto = DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))
        result = compute(dto)
        assert result.vpeak_cm_s == 160.0, f"Failed for {label}"
