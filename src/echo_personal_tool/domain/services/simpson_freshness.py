"""Freshness of Simpson LV results (QH-1b.2, slice 3: Simpson family).

A Simpson result (EDV/ESV/EF) is only as current as the contours and the
pixel spacing it was computed from. This module compares the basis recorded
with a result against the basis the study provides now and returns the
freshness state and reason codes defined in
:mod:`echo_personal_tool.domain.models.result_provenance`.

Rules (spec §5.2 matrix, row "Контуры/калибровка"):

- no recorded basis (legacy result) → ``unverified``; the origin is not guessed;
- no pixel spacing now → ``unavailable``; volumes cannot be recomputed;
- same contour identities, revisions, spacing and method → ``fresh``;
- otherwise → ``stale`` with the reason(s): edited/replaced contours
  (``input_changed``), a removed contour (``source_missing``), changed pixel
  spacing (``calibration_changed``), or a changed method (``method_changed``).

Contour identity is ``(view, phase, measurement_id)`` with the QH-1b.1 content
``revision``; legacy contours without a ``measurement_id`` are still tracked
by view/phase, so an edit (revision bump) invalidates the result.

Freshness is separate from QC: a ``fresh`` value is not thereby ``valid``.
The module is pure (no Qt, no I/O).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

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

#: Two spacings closer than this are the same calibration for every display.
_REL_TOL = 1e-9

_VALID_PHASES = ("ed", "es")
_VALID_VIEWS = ("A4C", "A2C")


@dataclass(frozen=True)
class SimpsonContourRef:
    """One contour a Simpson result was computed from."""

    view: str
    phase: str
    measurement_id: str
    revision: int


@dataclass(frozen=True)
class SimpsonBasis:
    """The inputs a Simpson result was computed from.

    ``contours`` holds one ref per (view, phase), sorted; ``method`` is the
    calculator method label (``biplane``/``monoplane``/``""`` when unknown).
    """

    contours: tuple[SimpsonContourRef, ...] = ()
    pixel_spacing: tuple[float, float] | None = None
    method: str = ""


@dataclass(frozen=True)
class SimpsonFreshness:
    """Freshness verdict for one Simpson result."""

    freshness: str
    reasons: tuple[str, ...] = ()

    @property
    def is_fresh(self) -> bool:
        return self.freshness == Freshness.FRESH.value


def simpson_basis_from_contours(
    contours: tuple[Contour, ...],
    pixel_spacing: tuple[float, float] | None,
    method: str = "",
) -> SimpsonBasis:
    """Build the current Simpson basis from the study's contours.

    Selection mirrors the calculator input: LV contours only, pending review
    excluded, one ref per (view, phase) with the last contour winning.
    """
    refs: dict[tuple[str, str], SimpsonContourRef] = {}
    for contour in contours:
        if contour.chamber.upper() != "LV":
            continue
        if contour.review_pending:
            continue
        phase = contour.phase.casefold()
        view = contour.view.casefold().upper()
        if phase not in _VALID_PHASES or view not in _VALID_VIEWS:
            continue
        refs[(view, phase)] = SimpsonContourRef(view, phase, contour.measurement_id, contour.revision)
    ordered = tuple(refs[key] for key in sorted(refs))
    return SimpsonBasis(contours=ordered, pixel_spacing=pixel_spacing, method=method)


def evaluate_simpson_freshness(recorded: SimpsonBasis | None, current: SimpsonBasis | None) -> SimpsonFreshness:
    """Freshness of a result recorded with *recorded*, given the *current* basis."""
    if recorded is None:
        return SimpsonFreshness(Freshness.UNVERIFIED.value, (REASON_LEGACY_NO_PROVENANCE,))
    if current is None or current.pixel_spacing is None:
        return SimpsonFreshness(Freshness.UNAVAILABLE.value, (REASON_INPUT_MISSING,))
    if recorded == current:
        return SimpsonFreshness(Freshness.FRESH.value)

    reasons: list[str] = []
    if recorded.method != current.method:
        reasons.append(REASON_METHOD_CHANGED)
    if not _same_spacing(recorded.pixel_spacing, current.pixel_spacing):
        reasons.append(REASON_CALIBRATION_CHANGED)
    before = {(ref.view, ref.phase): ref for ref in recorded.contours}
    after = {(ref.view, ref.phase): ref for ref in current.contours}
    for key, old in before.items():
        new = after.get(key)
        if new is None:
            reasons.append(REASON_SOURCE_MISSING)
        elif (new.measurement_id, new.revision) != (old.measurement_id, old.revision):
            reasons.append(REASON_INPUT_CHANGED)
    if not reasons:
        reasons.append(REASON_INPUT_CHANGED)
    return SimpsonFreshness(Freshness.STALE.value, tuple(dict.fromkeys(reasons)))


def _same_spacing(first: tuple[float, float] | None, second: tuple[float, float] | None) -> bool:
    if first is None or second is None:
        return first is None and second is None
    return all(math.isclose(a, b, rel_tol=_REL_TOL, abs_tol=0.0) for a, b in zip(first, second))
