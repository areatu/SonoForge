"""Multi-beat averaging for cycle-dependent Doppler measurements."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MultiBeatAverage:
    """Averaged measurement over a set of cardiac cycles."""

    mean: float
    values: tuple[float, ...]
    count: int


def beat_average(
    values: Sequence[float],
    *,
    max_beats: int = 3,
) -> MultiBeatAverage | None:
    """Average up to *max_beats* measurement values (first N in order)."""
    if not values:
        return None
    selected = tuple(float(value) for value in values[:max_beats])
    return MultiBeatAverage(
        mean=sum(selected) / len(selected),
        values=selected,
        count=len(selected),
    )
