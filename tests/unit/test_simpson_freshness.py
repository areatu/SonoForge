"""Simpson freshness of LV volumes/EF (QH-1b.2, slice 3: Simpson family).

A Simpson result is only as current as the contours and pixel spacing it was
computed from: edited/replaced/removed contours, changed calibration or a
changed method invalidate it, with stable reason codes. Legacy results stay
``unverified`` instead of being guessed fresh.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.result_provenance import (
    REASON_CALIBRATION_CHANGED,
    REASON_INPUT_CHANGED,
    REASON_INPUT_MISSING,
    REASON_LEGACY_NO_PROVENANCE,
    REASON_METHOD_CHANGED,
    REASON_SOURCE_MISSING,
    Freshness,
)
from echo_personal_tool.domain.services.simpson_freshness import (
    SimpsonBasis,
    evaluate_simpson_freshness,
    simpson_basis_from_contours,
)

pytestmark = pytest.mark.migration

_SPACING = (0.5, 0.5)


def _contour(
    view: str,
    phase: str,
    *,
    mid: str = "",
    revision: int = 0,
    chamber: str = "LV",
    review_pending: bool = False,
) -> Contour:
    return Contour(
        phase=phase,
        view=view,
        chamber=chamber,
        points=[(1.0, 2.0), (4.0, 9.0), (6.0, 2.0)],
        measurement_id=mid,
        revision=revision,
        review_pending=review_pending,
    )


def _basis(**kwargs) -> SimpsonBasis:
    contours = (
        _contour("A4C", "ed", mid="ed-a4c"),
        _contour("A4C", "es", mid="es-a4c"),
    )
    return simpson_basis_from_contours(contours, _SPACING, method="biplane", **kwargs)


# ── pure evaluator ─────────────────────────────────────────────────────


def test_legacy_result_without_basis_is_unverified_not_fresh() -> None:
    verdict = evaluate_simpson_freshness(None, _basis())
    assert verdict.freshness == Freshness.UNVERIFIED.value
    assert verdict.reasons == (REASON_LEGACY_NO_PROVENANCE,)
    assert not verdict.is_fresh


def test_missing_spacing_now_is_unavailable() -> None:
    verdict = evaluate_simpson_freshness(_basis(), simpson_basis_from_contours((), None))
    assert verdict.freshness == Freshness.UNAVAILABLE.value
    assert verdict.reasons == (REASON_INPUT_MISSING,)


def test_identical_basis_is_fresh() -> None:
    assert evaluate_simpson_freshness(_basis(), _basis()).is_fresh


def test_edited_contour_revision_is_stale() -> None:
    recorded = _basis()
    current = simpson_basis_from_contours(
        (
            _contour("A4C", "ed", mid="ed-a4c", revision=1),
            _contour("A4C", "es", mid="es-a4c"),
        ),
        _SPACING,
        method="biplane",
    )
    verdict = evaluate_simpson_freshness(recorded, current)
    assert verdict.freshness == Freshness.STALE.value
    assert verdict.reasons == (REASON_INPUT_CHANGED,)


def test_replaced_contour_identity_is_stale() -> None:
    recorded = _basis()
    current = simpson_basis_from_contours(
        (
            _contour("A4C", "ed", mid="ed-a4c-redrawn"),
            _contour("A4C", "es", mid="es-a4c"),
        ),
        _SPACING,
        method="biplane",
    )
    verdict = evaluate_simpson_freshness(recorded, current)
    assert verdict.reasons == (REASON_INPUT_CHANGED,)


def test_removed_contour_is_stale_with_source_missing() -> None:
    recorded = _basis()
    current = simpson_basis_from_contours((_contour("A4C", "ed", mid="ed-a4c"),), _SPACING, method="biplane")
    verdict = evaluate_simpson_freshness(recorded, current)
    assert verdict.freshness == Freshness.STALE.value
    assert REASON_SOURCE_MISSING in verdict.reasons


def test_changed_spacing_is_stale_with_calibration_changed() -> None:
    recorded = _basis()
    current = simpson_basis_from_contours(
        (
            _contour("A4C", "ed", mid="ed-a4c"),
            _contour("A4C", "es", mid="es-a4c"),
        ),
        (0.25, 0.25),
        method="biplane",
    )
    verdict = evaluate_simpson_freshness(recorded, current)
    assert verdict.reasons == (REASON_CALIBRATION_CHANGED,)


def test_changed_method_is_stale_with_method_changed() -> None:
    recorded = _basis()
    contours = (
        _contour("A4C", "ed", mid="ed-a4c"),
        _contour("A4C", "es", mid="es-a4c"),
    )
    current = simpson_basis_from_contours(contours, _SPACING, method="monoplane")
    verdict = evaluate_simpson_freshness(recorded, current)
    assert verdict.reasons == (REASON_METHOD_CHANGED,)


# ── basis builder ──────────────────────────────────────────────────────


def test_builder_mirrors_calculator_input_selection() -> None:
    basis = simpson_basis_from_contours(
        (
            _contour("A4C", "ed", mid="ed"),
            _contour("A4C", "es", mid="es"),
            _contour("A2C", "ed", mid="ed2"),
            _contour("A2C", "es", mid="es2"),
            _contour("A4C", "ed", mid="rv-ed", chamber="RV"),
            _contour("A4C", "es", mid="pending-es", review_pending=True),
            _contour("PLAX", "ed", mid="wrong-view"),
        ),
        _SPACING,
    )
    assert [(ref.view, ref.phase) for ref in basis.contours] == [
        ("A2C", "ed"),
        ("A2C", "es"),
        ("A4C", "ed"),
        ("A4C", "es"),
    ]


def test_builder_tracks_legacy_contours_without_measurement_id() -> None:
    recorded = simpson_basis_from_contours((_contour("A4C", "ed"),), _SPACING)
    edited = simpson_basis_from_contours((_contour("A4C", "ed", revision=1),), _SPACING)
    assert evaluate_simpson_freshness(recorded, recorded).is_fresh
    assert evaluate_simpson_freshness(recorded, edited).reasons == (REASON_INPUT_CHANGED,)
