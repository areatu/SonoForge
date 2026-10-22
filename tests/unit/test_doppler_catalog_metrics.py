"""Regressions for valve-specific Doppler labels and timing tools."""

from __future__ import annotations

import pytest

from echo_personal_tool.application.study_measurement_session import merge_doppler_dtos
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.doppler_catalog import canonical_peak_label
from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)


def test_legacy_peak_aliases_are_canonicalized_to_vmax() -> None:
    assert canonical_peak_label("Vpeak") == "AV Vmax"
    assert canonical_peak_label("AVpeak") == "AV Vmax"
    assert canonical_peak_label("TRpeak") == "TR Vmax"
    assert canonical_peak_label("AR peak") == "AR Vmax"


def test_repeated_same_peak_is_averaged_over_last_three() -> None:
    """D-23: repeated beats of one parameter average instead of replacing."""
    markers = [
        DopplerPeakMarker(label="TR Vmax", time_ms=10.0, velocity_cm_s=280.0, measurement_id="a"),
        DopplerPeakMarker(label="TR Vmax", time_ms=20.0, velocity_cm_s=330.0, measurement_id="b"),
        DopplerPeakMarker(label="TR Vmax", time_ms=30.0, velocity_cm_s=320.0, measurement_id="c"),
        DopplerPeakMarker(label="TR Vmax", time_ms=40.0, velocity_cm_s=310.0, measurement_id="d"),
    ]
    dto = DopplerMeasurementDTO(peaks=tuple(markers), intervals=(), traces=())

    result = compute(dto)

    # Only the last three of the four measurements enter the mean.
    expected = (330.0 + 320.0 + 310.0) / 3.0
    assert result.tr_vmax_cm_s == pytest.approx(expected)
    assert result.flow("TR").vmax_cm_s == pytest.approx(expected)
    assert result.flow("TR").vmax_repeats == 4
    assert result.flow("TR").pgmax_mmhg == pytest.approx(4.0 * (expected / 100.0) ** 2)


def test_merge_replaces_legacy_alias_with_new_canonical_measurement() -> None:
    existing = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="AVpeak", time_ms=10.0, velocity_cm_s=300.0),),
        intervals=(),
        traces=(),
    )
    incoming = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker(label="AV Vmax", time_ms=20.0, velocity_cm_s=410.0),),
        intervals=(),
        traces=(),
    )

    merged = merge_doppler_dtos(existing, incoming)

    assert len(merged.peaks) == 1
    assert merged.peaks[0].velocity_cm_s == 410.0


def test_flow_sites_keep_independent_vmax_and_vti_values() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker(label="AV Vmax", time_ms=10.0, velocity_cm_s=400.0),
            DopplerPeakMarker(label="LVOT Vmax", time_ms=20.0, velocity_cm_s=100.0),
            DopplerPeakMarker(label="AR Vmax", time_ms=30.0, velocity_cm_s=-350.0),
        ),
        intervals=(),
        traces=(
            DopplerTrace(label="LVOT VTI", points=((0.0, 0.0), (100.0, 200.0), (200.0, 0.0))),
            DopplerTrace(label="RVOT VTI", points=((0.0, 0.0), (100.0, 100.0), (200.0, 0.0))),
        ),
    )

    result = compute(dto)

    assert result.flow("AV").vmax_cm_s == 400.0
    assert result.flow("LVOT").vmax_cm_s == 100.0
    assert result.flow("LVOT").vti_cm == pytest.approx(20.0)
    assert result.flow("AR").vmax_cm_s == 350.0
    assert result.flow("RVOT").vti_cm == pytest.approx(10.0)


def test_pht_and_rvot_acceleration_time_are_computed_separately() -> None:
    dto = DopplerMeasurementDTO(
        peaks=(),
        intervals=(
            DopplerIntervalMarker(label="MV PHT", start_time_ms=100.0, end_time_ms=170.0),
            DopplerIntervalMarker(label="PR PHT", start_time_ms=200.0, end_time_ms=320.0),
            DopplerIntervalMarker(label="RVOT AT", start_time_ms=400.0, end_time_ms=485.0),
        ),
        traces=(),
    )

    result = compute(dto)

    assert result.mv_pht_ms == 70.0
    assert result.pr_pht_ms == 120.0
    assert result.rvot_at_ms == 85.0
