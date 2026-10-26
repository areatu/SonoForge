"""Record-level provenance notes for all families (QH-1b.2, slices 3a–c).

One wording for panel, text report and PDF — S-11 single projection.

Each family has:
- evaluate_*_record_status(recorded, current) -> status | None
- *_record_note(status) -> str | None

Freshness stays separate from QC: fresh means the record and the study agree
on the basis, not that the number is clinically valid.

The helpers wrap the pure evaluators (simpson_freshness, doppler_freshness,
derived_freshness) with the legacy/unavailable handling used for BSA, so
legacy documents become unverified and missing inputs become unavailable
instead of silently fresh.
"""

from __future__ import annotations

from typing import Any

from echo_personal_tool.domain.models.result_provenance import (
    REASON_INPUT_CHANGED,
    Freshness,
)

# BSA re-export for a single import point (unified projection)
from echo_personal_tool.domain.services.bsa_provenance import (
    bsa_record_note as bsa_record_note,
)
from echo_personal_tool.domain.services.derived_freshness import evaluate_derived_freshness
from echo_personal_tool.domain.services.doppler_freshness import (
    DopplerBasis,
    evaluate_doppler_freshness,
)
from echo_personal_tool.domain.services.simpson_freshness import (
    SimpsonBasis,
    evaluate_simpson_freshness,
)
from echo_personal_tool.domain.translation import tr

_REASON_KEYS = {
    "input_changed": "provenance.reason_input",
    "input_missing": "provenance.reason_source_missing",
    "source_missing": "provenance.reason_source_missing",
    "calibration_changed": "provenance.reason_calibration",
    "method_changed": "provenance.reason_method",
    "manual_override": "provenance.bsa_reason_manual",
    "height_weight_changed": "provenance.bsa_reason_height_weight",
    "legacy_no_provenance": "provenance.reason_input",
}

_FRESH = Freshness.FRESH.value
_STALE = Freshness.STALE.value
_UNVERIFIED = Freshness.UNVERIFIED.value
_UNAVAILABLE = Freshness.UNAVAILABLE.value


def _reasons_text(reasons: tuple[str, ...]) -> str:
    return "; ".join(tr(_REASON_KEYS[code]) for code in reasons if code in _REASON_KEYS)


# ── Simpson ──────────────────────────────────────────────────────────────


def evaluate_simpson_record_status(recorded: SimpsonBasis | None, current: SimpsonBasis | None) -> object | None:
    """Freshness of the stored Simpson record against the open study, or None.

    None means nothing to report (no Simpson result anywhere). Legacy
    (recorded is None but current exists) -> unverified. Missing current
    spacing -> unavailable. Otherwise delegate to pure evaluator.
    """
    has_current = current is not None and current.pixel_spacing is not None
    has_recorded = recorded is not None and recorded.pixel_spacing is not None
    # No Simpson result in either place -> nothing to say
    if not has_current and not has_recorded:
        return None
    if recorded is None:
        return evaluate_simpson_freshness(None, current)
    if not has_current:
        # Current cannot recompute, but record had something -> unavailable
        from echo_personal_tool.domain.services.simpson_freshness import SimpsonFreshness

        return SimpsonFreshness(_UNAVAILABLE, (REASON_INPUT_CHANGED,))
    verdict = evaluate_simpson_freshness(recorded, current)
    return verdict


def simpson_record_note(status: object | None) -> str | None:
    if status is None:
        return None
    freshness = getattr(status, "freshness", None)
    if freshness == _FRESH or freshness is None:
        # SimpsonFreshness has is_fresh, but check explicitly
        if getattr(status, "is_fresh", False) if hasattr(status, "is_fresh") else freshness == _FRESH:
            return None
        if freshness == _FRESH:
            return None
    if freshness == _UNAVAILABLE:
        return tr("provenance.simpson_record_unavailable")
    if freshness == _UNVERIFIED:
        return tr("provenance.simpson_record_unverified")
    reasons = getattr(status, "reasons", ())
    reasons_text = _reasons_text(reasons)
    note = tr("provenance.simpson_record_stale")
    return f"{note} ({reasons_text})" if reasons_text else note


# ── Doppler ──────────────────────────────────────────────────────────────


def evaluate_doppler_record_status(recorded: DopplerBasis | None, current: DopplerBasis | None) -> object | None:
    has_current = current is not None and (current.markers or current.traces)
    has_recorded = recorded is not None and (recorded.markers or recorded.traces)
    if not has_current and not has_recorded:
        return None
    if recorded is None:
        return evaluate_doppler_freshness(None, current)
    if current is None or (not current.markers and not current.traces):
        from echo_personal_tool.domain.services.doppler_freshness import DopplerFreshness

        return DopplerFreshness(_UNAVAILABLE, (REASON_INPUT_CHANGED,))
    verdict = evaluate_doppler_freshness(recorded, current)
    return verdict


def doppler_record_note(status: object | None) -> str | None:
    if status is None:
        return None
    freshness = getattr(status, "freshness", None)
    if freshness == _FRESH:
        return None
    if hasattr(status, "is_fresh") and status.is_fresh:
        return None
    if freshness == _UNAVAILABLE:
        return tr("provenance.doppler_record_unavailable")
    if freshness == _UNVERIFIED:
        return tr("provenance.doppler_record_unverified")
    reasons = getattr(status, "reasons", ())
    reasons_text = _reasons_text(reasons)
    note = tr("provenance.doppler_record_stale")
    return f"{note} ({reasons_text})" if reasons_text else note


# ── Derived (calculators) ────────────────────────────────────────────────


def evaluate_derived_record_status(recorded: object | None, current: object | None) -> object | None:
    """Freshness of stored calculator results against current inputs."""
    # recorded is CalculationsSnapshot | None, current likewise
    if recorded is None and current is None:
        return None
    # No inputs at all -> nothing to report (both have no values)
    # We treat empty snapshots as not comparable; let evaluator decide.
    # If recorded is None but current has values -> unverified (legacy)
    if recorded is None:
        return evaluate_derived_freshness(None, current)  # type: ignore[arg-type]
    if current is None:
        from echo_personal_tool.domain.services.derived_freshness import DerivedFreshness

        return DerivedFreshness(_UNAVAILABLE, (REASON_INPUT_CHANGED,))
    verdict = evaluate_derived_freshness(recorded, current)  # type: ignore[arg-type]
    # If both snapshots have no used inputs, evaluator would say stale due to missing?
    # But if neither had values, we should return None to keep panel clean.
    # Check if both have no used inputs -> nothing to report
    try:
        recorded_used = getattr(recorded, "used_inputs", lambda: ())()
        current_used = getattr(current, "used_inputs", lambda: ())()
        if not recorded_used and not current_used:
            return None
    except Exception:  # noqa: S110 - best-effort inputs check, no logging needed
        pass
    # If fresh, no note
    if (
        getattr(verdict, "is_fresh", False)
        if hasattr(verdict, "is_fresh")
        else getattr(verdict, "freshness", None) == _FRESH
    ):
        if verdict.freshness == _FRESH:
            return None
    return verdict


def derived_record_note(status: object | None) -> str | None:
    if status is None:
        return None
    freshness = getattr(status, "freshness", None)
    if freshness == _FRESH:
        return None
    if hasattr(status, "is_fresh") and status.is_fresh:
        return None
    if freshness == _UNAVAILABLE:
        return tr("provenance.derived_record_unavailable")
    if freshness == _UNVERIFIED:
        return tr("provenance.derived_record_unverified")
    reasons = getattr(status, "reasons", ())
    reasons_text = _reasons_text(reasons)
    note = tr("provenance.derived_record_stale")
    return f"{note} ({reasons_text})" if reasons_text else note


# ── Unified helper ───────────────────────────────────────────────────────


def all_provenance_notes(
    snapshot: Any,
    *,
    include_unverified_simpson: bool = True,
) -> tuple[str, ...]:
    """Collect provenance warnings from a MeasurementSnapshot (S-11).

    Returns tuple of non-empty notes, in a stable order: BSA, Simpson,
    Doppler, Derived. Reports retain every warning by default. The image
    overlay may omit only the legacy Simpson ``UNVERIFIED`` notice, which is
    common when opening non-echo studies and cannot help assess the image.
    Stale or unavailable Simpson results remain visible.
    """
    notes: list[str] = []
    for field, helper in (
        ("bsa_record_status", bsa_record_note),
        ("simpson_record_status", simpson_record_note),
        ("doppler_record_status", doppler_record_note),
        ("derived_record_status", derived_record_note),
    ):
        status = getattr(snapshot, field, None)
        if (
            field == "simpson_record_status"
            and not include_unverified_simpson
            and getattr(status, "freshness", None) == _UNVERIFIED
        ):
            continue
        note = helper(status)
        if note:
            notes.append(note)
    return tuple(notes)
