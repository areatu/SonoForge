"""Derived freshness of engine results (QH-1b.2, slice 3c: derived family).

A derived result (PASP, AVA, CO, …) is only as current as the resolved
inputs behind it: changed values, applied/removed manual overrides and newly
missing inputs invalidate it with stable reason codes, while touching an
unrelated input does not. Legacy results without a recorded snapshot stay
``unverified`` instead of being guessed fresh.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.application.calculator_inputs import resolve_study_inputs
from echo_personal_tool.domain.calculators.engine import evaluate
from echo_personal_tool.domain.calculators.models import CalculationsSnapshot
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerPeakMarker
from echo_personal_tool.domain.models.result_provenance import (
    REASON_INPUT_CHANGED,
    REASON_LEGACY_NO_PROVENANCE,
    REASON_MANUAL_OVERRIDE,
    REASON_SOURCE_MISSING,
    Freshness,
)
from echo_personal_tool.domain.services.derived_freshness import evaluate_derived_freshness

pytestmark = pytest.mark.migration


def _dto(*, tr_vmax_cm_s: float = 300.0) -> DopplerMeasurementDTO:
    from echo_personal_tool.domain.calculations.doppler_metrics import compute

    dto = DopplerMeasurementDTO(
        peaks=(DopplerPeakMarker("TR Vmax", 100.0, -tr_vmax_cm_s, "tr", "CW"),),
        intervals=(),
        traces=(),
    )
    return compute(dto)


def _snapshot(
    *, tr_vmax_cm_s: float = 300.0, rap: float | None = 8.0, extra_manual: dict | None = None
) -> CalculationsSnapshot:
    manual: dict = dict(extra_manual or {})
    if rap is not None:
        manual["rap"] = rap
    return evaluate(resolve_study_inputs(doppler=_dto(tr_vmax_cm_s=tr_vmax_cm_s), manual=manual))


def _pasp(snapshot: CalculationsSnapshot) -> float | None:
    result = snapshot.result("pulmonary_pressure")
    output = result.output("pasp") if result is not None else None
    return output.value if output is not None else None


# ── pure evaluator ─────────────────────────────────────────────────────


def test_legacy_result_without_snapshot_is_unverified_not_fresh() -> None:
    verdict = evaluate_derived_freshness(None, _snapshot())
    assert verdict.freshness == Freshness.UNVERIFIED.value
    assert verdict.reasons == (REASON_LEGACY_NO_PROVENANCE,)
    assert not verdict.is_fresh


def test_identical_resolution_is_fresh() -> None:
    assert _pasp(_snapshot()) == pytest.approx(44.0)
    assert evaluate_derived_freshness(_snapshot(), _snapshot()).is_fresh


def test_changed_doppler_input_is_stale() -> None:
    recorded = _snapshot(tr_vmax_cm_s=300.0)
    current = _snapshot(tr_vmax_cm_s=320.0)
    assert _pasp(current) != pytest.approx(_pasp(recorded))
    verdict = evaluate_derived_freshness(recorded, current)
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_INPUT_CHANGED,)


def test_changed_manual_override_is_stale_with_manual_override() -> None:
    verdict = evaluate_derived_freshness(_snapshot(rap=8.0), _snapshot(rap=10.0))
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_MANUAL_OVERRIDE,)


def test_removed_manual_input_is_stale_with_source_missing() -> None:
    assert _pasp(_snapshot()) == pytest.approx(44.0)
    assert _pasp(_snapshot(rap=None)) is None
    verdict = evaluate_derived_freshness(_snapshot(), _snapshot(rap=None))
    assert verdict.freshness == Freshness.STALE.value
    assert REASON_SOURCE_MISSING in verdict.reasons


def test_unrelated_manual_input_keeps_results_fresh() -> None:
    recorded = _snapshot()
    current = _snapshot(extra_manual={"hr": 72.0})
    assert _pasp(current) == pytest.approx(_pasp(recorded))
    assert evaluate_derived_freshness(recorded, current).is_fresh
