"""Freshness of BSA-dependent results (QH-1b.2, slice 1: calculators/BSA).

A BSA-indexed value (LVEDVi, SV/BSA, AVAi, …) is only as current as the BSA it
was divided by. This module compares the basis recorded with a result against
the basis the study provides now and returns the freshness state and reason
codes defined in :mod:`echo_personal_tool.domain.models.result_provenance`.

Rules (spec §5.2 matrix, row "Рост/вес/BSA" and manual override):

- no recorded basis (legacy result) → ``unverified``; the origin is not guessed;
- no BSA now (height/weight missing and no manual value) → ``unavailable``;
- same BSA value (relative tolerance 1e-9) → ``fresh``; a source change that
  leaves the number unchanged does not change the result;
- otherwise → ``stale`` with the reason(s): manual override, height/weight
  change, or a generic input change.

Freshness is separate from QC: a ``fresh`` value is not thereby ``valid``.
The module is pure (no Qt, no I/O).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from echo_personal_tool.domain.models.result_provenance import (
    BSA_SOURCE_MANUAL,
    REASON_HEIGHT_WEIGHT_CHANGED,
    REASON_INPUT_CHANGED,
    REASON_INPUT_MISSING,
    REASON_LEGACY_NO_PROVENANCE,
    REASON_MANUAL_OVERRIDE,
    BsaBasis,
    Freshness,
)

#: Two BSA values closer than this are the same number for every display.
_REL_TOL = 1e-9


@dataclass(frozen=True)
class BsaFreshness:
    """Freshness verdict for one BSA-dependent result."""

    freshness: str
    reasons: tuple[str, ...] = ()

    @property
    def is_fresh(self) -> bool:
        return self.freshness == Freshness.FRESH.value


def evaluate_bsa_freshness(recorded: BsaBasis | None, current: BsaBasis | None) -> BsaFreshness:
    """Freshness of a result recorded with *recorded*, given the *current* BSA basis."""
    if recorded is None:
        return BsaFreshness(Freshness.UNVERIFIED.value, (REASON_LEGACY_NO_PROVENANCE,))
    if current is None or current.value is None:
        return BsaFreshness(Freshness.UNAVAILABLE.value, (REASON_INPUT_MISSING,))
    if recorded.value is not None and math.isclose(recorded.value, current.value, rel_tol=_REL_TOL, abs_tol=0.0):
        return BsaFreshness(Freshness.FRESH.value)

    reasons: list[str] = []
    if BSA_SOURCE_MANUAL in (recorded.source, current.source):
        reasons.append(REASON_MANUAL_OVERRIDE)
    if (recorded.height_cm, recorded.weight_kg) != (current.height_cm, current.weight_kg):
        reasons.append(REASON_HEIGHT_WEIGHT_CHANGED)
    if not reasons:
        reasons.append(REASON_INPUT_CHANGED)
    return BsaFreshness(Freshness.STALE.value, tuple(reasons))
