"""BSA freshness of calculator and indexed results (QH-1b.2, slice 1).

Covers the spec §5.2 rows "Рост/вес/BSA" (only BSA-dependent indexes change;
raw volumes do not) and "Manual input/override" (calculators are recomputed,
the source of the input is kept), plus the legacy/unavailable states.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.application.calculator_inputs import resolve_study_inputs
from echo_personal_tool.domain.calculations.body_surface import (
    bsa_du_bois_m2,
    compute_indexed_measurements,
)
from echo_personal_tool.domain.calculators.engine import evaluate
from echo_personal_tool.domain.calculators.models import SOURCE_MANUAL
from echo_personal_tool.domain.models import (
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.models.result_provenance import (
    BSA_SOURCE_DERIVED,
    BSA_SOURCE_MANUAL,
    BSA_SOURCE_MISSING,
    REASON_HEIGHT_WEIGHT_CHANGED,
    REASON_INPUT_CHANGED,
    REASON_INPUT_MISSING,
    REASON_LEGACY_NO_PROVENANCE,
    REASON_MANUAL_OVERRIDE,
    BsaBasis,
    Freshness,
)
from echo_personal_tool.domain.services.bsa_freshness import evaluate_bsa_freshness

pytestmark = pytest.mark.migration


def _basis(height: float = 170.0, weight: float = 70.0, source: str = BSA_SOURCE_DERIVED) -> BsaBasis:
    bsa = bsa_du_bois_m2(height, weight)
    return BsaBasis(bsa, source, height, weight)


def _study_calculations(*, height=170.0, weight=70.0, manual=None):
    inputs = resolve_study_inputs(
        doppler=None,
        height_cm=height,
        weight_kg=weight,
        height_source="dicom",
        weight_source="dicom",
        manual=manual or {},
    )
    return evaluate(inputs)


# ── pure evaluator ───────────────────────────────────────────────────────


def test_legacy_result_without_basis_is_unverified_not_fresh() -> None:
    verdict = evaluate_bsa_freshness(None, _basis())
    assert verdict.freshness == Freshness.UNVERIFIED.value
    assert verdict.reasons == (REASON_LEGACY_NO_PROVENANCE,)
    assert not verdict.is_fresh


def test_no_bsa_now_is_unavailable() -> None:
    verdict = evaluate_bsa_freshness(_basis(), BsaBasis(None, BSA_SOURCE_MISSING, None, None))
    assert verdict.freshness == Freshness.UNAVAILABLE.value
    assert verdict.reasons == (REASON_INPUT_MISSING,)


def test_same_bsa_is_fresh() -> None:
    verdict = evaluate_bsa_freshness(_basis(), _basis())
    assert verdict.freshness == Freshness.FRESH.value
    assert verdict.reasons == ()
    assert verdict.is_fresh


def test_same_number_from_other_source_stays_fresh() -> None:
    # A manual value equal to the derived one does not change any displayed number.
    recorded = _basis()
    current = BsaBasis(recorded.value, BSA_SOURCE_MANUAL, 170.0, 70.0)
    assert evaluate_bsa_freshness(recorded, current).freshness == Freshness.FRESH.value


def test_height_change_makes_result_stale_with_height_weight_reason() -> None:
    verdict = evaluate_bsa_freshness(_basis(height=170.0), _basis(height=172.0))
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_HEIGHT_WEIGHT_CHANGED,)


def test_weight_change_makes_result_stale() -> None:
    verdict = evaluate_bsa_freshness(_basis(weight=70.0), _basis(weight=75.0))
    assert verdict.freshness == Freshness.STALE.value
    assert REASON_HEIGHT_WEIGHT_CHANGED in verdict.reasons


def test_manual_override_over_derived_is_stale_with_manual_reason() -> None:
    current = BsaBasis(2.2, BSA_SOURCE_MANUAL, 170.0, 70.0)
    verdict = evaluate_bsa_freshness(_basis(), current)
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_MANUAL_OVERRIDE,)


def test_cleared_manual_override_is_stale_with_manual_reason() -> None:
    recorded = BsaBasis(2.2, BSA_SOURCE_MANUAL, 170.0, 70.0)
    verdict = evaluate_bsa_freshness(recorded, _basis())
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_MANUAL_OVERRIDE,)


def test_recorded_without_bsa_becomes_stale_once_height_weight_are_set() -> None:
    recorded = BsaBasis(None, BSA_SOURCE_MISSING, None, None)
    verdict = evaluate_bsa_freshness(recorded, _basis())
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_HEIGHT_WEIGHT_CHANGED,)


def test_generic_input_change_uses_input_changed_reason() -> None:
    # Same height/weight and source, but a different number: nothing named, so generic.
    recorded = BsaBasis(2.0, BSA_SOURCE_DERIVED, 170.0, 70.0)
    current = BsaBasis(2.1, BSA_SOURCE_DERIVED, 170.0, 70.0)
    verdict = evaluate_bsa_freshness(recorded, current)
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_INPUT_CHANGED,)


def test_tiny_float_noise_is_not_a_change() -> None:
    recorded = _basis()
    current = BsaBasis(recorded.value * (1 + 1e-12), BSA_SOURCE_DERIVED, 170.0, 70.0)
    assert evaluate_bsa_freshness(recorded, current).freshness == Freshness.FRESH.value


# ── calculator snapshot records its BSA basis ───────────────────────────


def test_calculations_snapshot_records_derived_basis() -> None:
    calculations = _study_calculations()
    assert calculations.bsa_basis is not None
    assert calculations.bsa_basis.source == BSA_SOURCE_DERIVED
    assert calculations.bsa_basis.value == pytest.approx(bsa_du_bois_m2(170.0, 70.0))
    assert calculations.bsa_basis.height_cm == 170.0
    assert calculations.bsa_basis.weight_kg == 70.0


def test_calculations_snapshot_records_manual_basis_over_derived() -> None:
    calculations = _study_calculations(manual={"bsa": 2.1})
    assert calculations.bsa_basis is not None
    assert calculations.bsa_basis.source == BSA_SOURCE_MANUAL
    assert calculations.bsa_basis.value == pytest.approx(2.1)
    assert calculations.input("bsa").source == SOURCE_MANUAL  # precedence unchanged


def test_calculations_snapshot_without_height_weight_has_missing_basis() -> None:
    calculations = _study_calculations(height=None, weight=None)
    assert calculations.bsa_basis is not None
    assert calculations.bsa_basis.value is None
    assert calculations.bsa_basis.source == BSA_SOURCE_MISSING


def test_calculator_bsa_is_stale_after_height_change() -> None:
    before = _study_calculations(height=170.0)
    after = _study_calculations(height=180.0)
    verdict = evaluate_bsa_freshness(before.bsa_basis, after.bsa_basis)
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_HEIGHT_WEIGHT_CHANGED,)


def test_calculator_bsa_becomes_stale_when_manual_bsa_typed_and_is_recomputed() -> None:
    before = _study_calculations()
    after = _study_calculations(manual={"bsa": 2.1})
    verdict = evaluate_bsa_freshness(before.bsa_basis, after.bsa_basis)
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_MANUAL_OVERRIDE,)


def test_calculator_bsa_unchanged_when_only_unrelated_input_changes() -> None:
    # Inputs that do not feed BSA must not invalidate the BSA basis.
    before = _study_calculations()
    inputs = resolve_study_inputs(
        doppler=None,
        height_cm=170.0,
        weight_kg=70.0,
        height_source="dicom",
        weight_source="dicom",
        manual={"lvot_d": 2.0},
    )
    after = evaluate(inputs)
    assert evaluate_bsa_freshness(before.bsa_basis, after.bsa_basis).freshness == Freshness.FRESH.value


# ── indexed results: only BSA-dependent indexes are affected ───────────


def _snapshot(edv_ml: float) -> MeasurementSnapshot:
    return MeasurementSnapshot(
        lvef=LvefResult(a4c=LvViewMetrics(edv_ml=edv_ml, esv_ml=45.0), lvef_percent=62.5),
    )


def test_indexed_result_records_derived_basis() -> None:
    indexed = compute_indexed_measurements(_snapshot(120.0), height_cm=170.0, weight_kg=70.0)
    assert indexed is not None
    assert indexed.bsa_basis == BsaBasis(indexed.bsa_m2, BSA_SOURCE_DERIVED, 170.0, 70.0)


def test_height_change_stales_indexed_basis_but_not_raw_volume() -> None:
    old = compute_indexed_measurements(_snapshot(120.0), height_cm=170.0, weight_kg=70.0)
    new = compute_indexed_measurements(_snapshot(120.0), height_cm=180.0, weight_kg=70.0)
    assert old is not None and new is not None
    # The indexed value is stale …
    assert evaluate_bsa_freshness(old.bsa_basis, new.bsa_basis).freshness == Freshness.STALE.value
    # … and the raw volume itself is the same number in both snapshots.
    assert old.simpson_edvi_ml_m2 != new.simpson_edvi_ml_m2


def test_raw_volume_change_does_not_stale_bsa_basis() -> None:
    # A new EDV (e.g. a corrected contour) changes the index but not the BSA it uses.
    old = compute_indexed_measurements(_snapshot(120.0), height_cm=170.0, weight_kg=70.0)
    new = compute_indexed_measurements(_snapshot(140.0), height_cm=170.0, weight_kg=70.0)
    assert old is not None and new is not None
    assert evaluate_bsa_freshness(old.bsa_basis, new.bsa_basis).freshness == Freshness.FRESH.value
