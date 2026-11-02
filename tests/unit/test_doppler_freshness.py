"""Doppler freshness of Vmax/VTI aggregates (QH-1b.2, slice 3b: Doppler family).

A Doppler result is only as current as the markers, traces and calibration
state it was computed from: edited/added/removed markers or traces and a
changed calibration invalidate it with stable reason codes. Legacy results
stay ``unverified`` instead of being guessed fresh.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.doppler import (
    DopplerIntervalMarker,
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.doppler_roi import DopplerCalibrationState, DopplerSpectrogramRoi
from echo_personal_tool.domain.models.result_provenance import (
    REASON_CALIBRATION_CHANGED,
    REASON_INPUT_CHANGED,
    REASON_INPUT_MISSING,
    REASON_LEGACY_NO_PROVENANCE,
    REASON_SOURCE_MISSING,
    Freshness,
)
from echo_personal_tool.domain.services.doppler_freshness import (
    DopplerBasis,
    doppler_basis_from_dto,
    evaluate_doppler_freshness,
)

pytestmark = pytest.mark.migration

_UID = "1.2.3.4"


def _dto() -> DopplerMeasurementDTO:
    return DopplerMeasurementDTO(
        peaks=(
            DopplerPeakMarker("TR Vmax", 100.0, -300.0, "tr", "CW"),
            DopplerPeakMarker("TR Vmax", 200.0, -310.0, "tr2", "CW"),
        ),
        intervals=(DopplerIntervalMarker("RVOT AT", 50.0, 150.0, "at"),),
        traces=(DopplerTrace("RVOT VTI", ((0.0, 0.0), (150.0, 100.0), (300.0, 0.0)), "rv"),),
    )


def _calibration(*, velocity_span_cm_s: float = 200.0) -> DopplerCalibrationState:
    roi = DopplerSpectrogramRoi(1, 2, 100, 80)
    return DopplerCalibrationState(roi, baseline_y_px=40, velocity_span_cm_s=velocity_span_cm_s)


def _basis(
    dto: DopplerMeasurementDTO | None = None, calibration: DopplerCalibrationState | None = None
) -> DopplerBasis:
    return doppler_basis_from_dto(
        dto if dto is not None else _dto(), _calibration() if calibration is None else calibration, _UID
    )


# ── pure evaluator ─────────────────────────────────────────────────────


def test_legacy_result_without_basis_is_unverified_not_fresh() -> None:
    verdict = evaluate_doppler_freshness(None, _basis())
    assert verdict.freshness == Freshness.UNVERIFIED.value
    assert verdict.reasons == (REASON_LEGACY_NO_PROVENANCE,)
    assert not verdict.is_fresh


def test_missing_current_basis_is_unavailable() -> None:
    verdict = evaluate_doppler_freshness(_basis(), None)
    assert verdict.freshness == Freshness.UNAVAILABLE.value
    assert verdict.reasons == (REASON_INPUT_MISSING,)


def test_identical_basis_is_fresh() -> None:
    assert evaluate_doppler_freshness(_basis(), _basis()).is_fresh


def test_edited_peak_velocity_is_stale() -> None:
    recorded = _basis()
    dto = _dto()
    edited_peaks = (DopplerPeakMarker("TR Vmax", 100.0, -320.0, "tr", "CW"), dto.peaks[1])
    current = doppler_basis_from_dto(dto.__class__(edited_peaks, dto.intervals, dto.traces), _calibration(), _UID)
    verdict = evaluate_doppler_freshness(recorded, current)
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_INPUT_CHANGED,)


def test_added_peak_is_stale() -> None:
    recorded = _basis()
    dto = _dto()
    extra = dto.peaks + (DopplerPeakMarker("TR Vmax", 300.0, -290.0, "tr3", "CW"),)
    current = doppler_basis_from_dto(dto.__class__(extra, dto.intervals, dto.traces), _calibration(), _UID)
    verdict = evaluate_doppler_freshness(recorded, current)
    assert verdict.reasons == (REASON_INPUT_CHANGED,)


def test_removed_trace_is_stale_with_source_missing() -> None:
    recorded = _basis()
    dto = _dto()
    current = doppler_basis_from_dto(dto.__class__(dto.peaks, dto.intervals, ()), _calibration(), _UID)
    verdict = evaluate_doppler_freshness(recorded, current)
    assert verdict.freshness == Freshness.STALE.value
    assert REASON_SOURCE_MISSING in verdict.reasons


def test_edited_trace_envelope_is_stale() -> None:
    recorded = _basis()
    dto = _dto()
    moved = (DopplerTrace("RVOT VTI", ((0.0, 0.0), (150.0, 110.0), (300.0, 0.0)), "rv"),)
    current = doppler_basis_from_dto(dto.__class__(dto.peaks, dto.intervals, moved), _calibration(), _UID)
    assert evaluate_doppler_freshness(recorded, current).reasons == (REASON_INPUT_CHANGED,)


def test_changed_calibration_is_stale_with_calibration_changed() -> None:
    verdict = evaluate_doppler_freshness(_basis(), _basis(calibration=_calibration(velocity_span_cm_s=300.0)))
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_CALIBRATION_CHANGED,)


def test_replaced_instance_is_stale() -> None:
    recorded = _basis()
    current = doppler_basis_from_dto(_dto(), _calibration(), "9.9.9.9")
    assert evaluate_doppler_freshness(recorded, current).reasons == (REASON_INPUT_CHANGED,)
