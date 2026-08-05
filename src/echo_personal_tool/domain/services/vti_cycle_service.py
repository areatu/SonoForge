"""ECG-cycle-constrained VTI computation from a Doppler envelope."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle


@dataclass(frozen=True)
class CycleVti:
    """VTI measured within a single cardiac cycle."""

    cycle: CardiacCycle
    vti_cm: float
    onset_ms: float
    offset_ms: float


def envelope_points_in_cycle(
    envelope: tuple[tuple[float, float], ...],
    cycle: CardiacCycle,
    *,
    min_points: int = 3,
) -> tuple[tuple[float, float], ...]:
    """Return envelope ``(time_ms, velocity_cm_s)`` samples inside the cycle."""
    points = [point for point in envelope if cycle.start_ms <= point[0] <= cycle.end_ms]
    if len(points) < min_points:
        return ()
    return tuple(points)


def vti_from_points(points: Sequence[tuple[float, float]]) -> float:
    """Trapezoidal integral of a ``(time_ms, velocity_cm_s)`` envelope.

    Uses the same ms-time convention as ``doppler_metrics`` so values are
    comparable to manually traced VTIs. Trace timestamps are milliseconds,
    so the raw integral of (cm/s) over (ms) is 1000x too large; dividing by
    1000 yields centimetres.
    """
    times = np.asarray([p[0] for p in points], dtype=np.float64)
    velocities = np.asarray([p[1] for p in points], dtype=np.float64)
    return float(np.trapezoid(velocities, times)) / 1000.0


def vti_in_cycle(
    envelope: tuple[tuple[float, float], ...],
    cycle: CardiacCycle,
    *,
    min_points: int = 3,
) -> float | None:
    """Return the VTI of the envelope clipped to one cycle, or ``None``."""
    points = envelope_points_in_cycle(envelope, cycle, min_points=min_points)
    if not points:
        return None
    return vti_from_points(points)


def vti_for_cycles(
    envelope: tuple[tuple[float, float], ...],
    cycles: Sequence[CardiacCycle],
    *,
    min_points: int = 3,
) -> list[CycleVti]:
    """Compute per-cycle VTI for every cycle with enough envelope coverage."""
    results: list[CycleVti] = []
    for cycle in cycles:
        vti = vti_in_cycle(envelope, cycle, min_points=min_points)
        if vti is None:
            continue
        results.append(
            CycleVti(
                cycle=cycle,
                vti_cm=vti,
                onset_ms=cycle.start_ms,
                offset_ms=cycle.end_ms,
            )
        )
    return results
