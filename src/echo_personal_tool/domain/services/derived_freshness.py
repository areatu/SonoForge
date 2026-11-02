"""Freshness of derived calculator results (QH-1b.2, slice 3c: derived family).

A derived result (PASP, AVA, CO, …) is only as current as the resolved
inputs it was computed from. This module compares the input snapshot
recorded with a result against the inputs the study resolves now and returns
the freshness state and reason codes defined in
:mod:`echo_personal_tool.domain.models.result_provenance`.

Rules (spec §5.2 matrix, rows "Manual input/override" and "Допплер-повторы"):

- no recorded snapshot (legacy result) → ``unverified``; the origin is not guessed;
- same contributing input values, sources and details → ``fresh``; a source
  change that leaves every contributing number unchanged does not change the
  result;
- otherwise → ``stale`` with the reason(s): changed value or detail
  (``input_changed``), a newly applied or removed manual override
  (``manual_override``), or a previously available input gone missing
  (``source_missing``).

Only inputs that contributed to at least one computed output (on either
side) are compared: touching an unrelated input does not invalidate a
result. Value comparison uses the same 1e-9 relative tolerance as the BSA
evaluator so a pure re-resolution is not reported as a change.

Freshness is separate from QC: a ``fresh`` value is not thereby ``valid``.
The module is pure (no Qt, no I/O).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from echo_personal_tool.domain.calculators.models import (
    SOURCE_MANUAL,
    CalculationsSnapshot,
    InputValue,
)
from echo_personal_tool.domain.models.result_provenance import (
    REASON_INPUT_CHANGED,
    REASON_LEGACY_NO_PROVENANCE,
    REASON_MANUAL_OVERRIDE,
    REASON_SOURCE_MISSING,
    Freshness,
)

#: Two input values closer than this are the same number for every display.
_REL_TOL = 1e-9


@dataclass(frozen=True)
class DerivedFreshness:
    """Freshness verdict for the derived results of one snapshot."""

    freshness: str
    reasons: tuple[str, ...] = ()

    @property
    def is_fresh(self) -> bool:
        return self.freshness == Freshness.FRESH.value


def evaluate_derived_freshness(
    recorded: CalculationsSnapshot | None,
    current: CalculationsSnapshot,
) -> DerivedFreshness:
    """Freshness of results recorded with *recorded*, given the *current* snapshot."""
    if recorded is None:
        return DerivedFreshness(Freshness.UNVERIFIED.value, (REASON_LEGACY_NO_PROVENANCE,))
    before = {item.id: item for item in recorded.used_inputs()}
    after = {item.id: item for item in current.used_inputs()}
    reasons: list[str] = []
    for input_id in sorted(set(before) | set(after)):
        old = before.get(input_id)
        new = after.get(input_id)
        if old is None or not old.available:
            if new is not None and new.available:
                reasons.append(REASON_INPUT_CHANGED)
            continue
        if new is None or not new.available:
            reasons.append(REASON_SOURCE_MISSING)
        elif not _same_input(old, new):
            if SOURCE_MANUAL in (old.source, new.source):
                reasons.append(REASON_MANUAL_OVERRIDE)
            else:
                reasons.append(REASON_INPUT_CHANGED)
    if not reasons:
        return DerivedFreshness(Freshness.FRESH.value)
    return DerivedFreshness(Freshness.STALE.value, tuple(dict.fromkeys(reasons)))


def _same_input(first: InputValue, second: InputValue) -> bool:
    if (first.source, first.detail) != (second.source, second.detail):
        return False
    if first.value is None or second.value is None:
        return first.value is None and second.value is None
    return math.isclose(first.value, second.value, rel_tol=_REL_TOL, abs_tol=0.0)
