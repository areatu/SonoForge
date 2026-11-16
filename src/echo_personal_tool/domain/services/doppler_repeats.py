"""Repeat measurements of one Doppler parameter (decision D-23).

A sonographer measures the same parameter (for example ``TR Vmax``) on several
consecutive beats, and the protocol reports the mean of the last three. Before
D-23 (2026-10-05) a repeated measurement replaced the previous one, so the
average could not be formed at all.

This module owns the numbers of that rule. The merge, the calculations, the
storage semantics and the report all read them from here, so they cannot drift
apart:

* :data:`REPORT_WINDOW` — how many most recent measurements enter the mean;
* :data:`MAX_REPEATS_PER_PARAMETER` — the storage/merge bound, so a stuck
  pointer or an over-eager auto-trace cannot grow a study without bound.

A measurement identity (``measurement_id``) is not a medical identifier: it
only lets the merge tell a deliberate repeat of the same parameter from a
re-commit of the same overlay state.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar

#: Number of most recent measurements of one parameter that enter the mean.
REPORT_WINDOW = 3

#: Hard cap of stored repeats per parameter.  The merge keeps the newest ones.
MAX_REPEATS_PER_PARAMETER = 10

T = TypeVar("T")


def new_measurement_id() -> str:
    """Return a fresh identity for one measurement marker."""
    return uuid.uuid4().hex[:16]


def mean_of_last(values: Iterable[float], *, window: int = REPORT_WINDOW) -> float | None:
    """Mean of the *window* most recent values, or ``None`` when there are none."""
    recent = [float(value) for value in values][-window:]
    if not recent:
        return None
    return sum(recent) / len(recent)


def report_sample_count(count: int, *, window: int = REPORT_WINDOW) -> int:
    """Number of repeats that actually contribute to a reported mean.

    Storage may retain more than the report window (up to
    :data:`MAX_REPEATS_PER_PARAMETER`), but the displayed ``n`` must describe
    the measurements used in the mean, not every older measurement still
    available for review.
    """
    return min(max(int(count), 0), max(int(window), 0))


@dataclass(frozen=True)
class RepeatStatistics:
    """Accepted, excluded and selected values behind one averaged parameter.

    ``selected`` is the tail of ``accepted`` that enters the report window; it
    is never a second arithmetic path.  ``sd`` is the sample standard
    deviation (``n - 1``), because the beats are a sample of the patient's
    cycles, and ``cv_percent`` is ``sd / mean * 100``.  Both stay ``None``
    for fewer than two selected values, and CV is also ``None`` when the mean
    is zero (a relative spread of zero has no meaning).
    """

    accepted: tuple[float, ...] = ()
    excluded: tuple[float, ...] = ()
    selected: tuple[float, ...] = ()

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)

    @property
    def n(self) -> int:
        return len(self.selected)

    @property
    def mean(self) -> float | None:
        if not self.selected:
            return None
        return sum(self.selected) / len(self.selected)

    @property
    def sd(self) -> float | None:
        if len(self.selected) < 2:
            return None
        mean = self.mean
        if mean is None:
            return None
        variance = sum((value - mean) ** 2 for value in self.selected) / (len(self.selected) - 1)
        return math.sqrt(max(variance, 0.0))

    @property
    def cv_percent(self) -> float | None:
        mean = self.mean
        sd = self.sd
        if mean is None or sd is None or mean == 0:
            return None
        return sd / abs(mean) * 100.0


def repeat_statistics(
    values: Sequence[float],
    accepted: Sequence[bool] | None = None,
    *,
    window: int = REPORT_WINDOW,
) -> RepeatStatistics:
    """Split values into accepted/excluded and select the report window.

    ``accepted=None`` means every stored value is accepted, which is the wire
    behavior of documents written before issue 559.  Selection only ever
    removes values: the mean of the selected values is exactly the mean the
    report already showed for an all-accepted legacy record.
    """
    numbers = tuple(float(value) for value in values)
    flags = tuple(bool(flag) for flag in accepted) if accepted is not None else (True,) * len(numbers)
    if len(flags) != len(numbers):
        raise ValueError("accepted flags must match values")
    accepted_values = tuple(value for value, flag in zip(numbers, flags) if flag)
    excluded_values = tuple(value for value, flag in zip(numbers, flags) if not flag)
    limit = max(int(window), 0)
    selected = accepted_values[-limit:] if limit else ()
    return RepeatStatistics(accepted=accepted_values, excluded=excluded_values, selected=selected)


def select_last_accepted(
    items: Sequence[T],
    *,
    accepted_of: Callable[[T], bool],
    window: int = REPORT_WINDOW,
) -> tuple[T, ...]:
    """The accepted tail of *items* that enters the report window."""
    accepted = [item for item in items if accepted_of(item)]
    limit = max(int(window), 0)
    return tuple(accepted[-limit:]) if limit else ()


def keep_newest_per_label(
    markers: Sequence[T],
    *,
    label_of: Callable[[T], str],
    limit: int = MAX_REPEATS_PER_PARAMETER,
) -> tuple[T, ...]:
    """Drop the oldest repeats so every label keeps at most *limit* markers.

    ``markers`` preserves placement order, so the newest markers are at the
    tail; the returned tuple keeps that order.
    """
    kept: dict[str, int] = {}
    result: list[T] = []
    for marker in reversed(markers):
        label = label_of(marker)
        seen = kept.get(label, 0)
        if seen >= limit:
            continue
        kept[label] = seen + 1
        result.append(marker)
    result.reverse()
    return tuple(result)


def merge_newest_wins(
    existing: Sequence[T],
    incoming: Sequence[T],
    *,
    identity_of: Callable[[T], tuple[str, str]],
    label_of: Callable[[T], str],
    limit: int = MAX_REPEATS_PER_PARAMETER,
) -> tuple[T, ...]:
    """Union of two marker tuples keyed by identity.

    A marker whose identity is already present (the same measurement edited and
    re-committed) replaces the stored one in place; anything else is appended
    as a new repeat.  A marker without an identity keeps the historical
    replace-by-label behavior, which is exactly how version 1 documents were
    interpreted.
    """
    result: list[T] = list(existing)
    index = {identity_of(marker): position for position, marker in enumerate(result)}
    for marker in incoming:
        key = identity_of(marker)
        position = index.get(key)
        if position is None:
            index[key] = len(result)
            result.append(marker)
        else:
            result[position] = marker
    return keep_newest_per_label(result, label_of=label_of, limit=limit)
