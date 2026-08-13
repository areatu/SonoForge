"""Helpers for manual Doppler VTI trace point lists."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def finalize_vti_trace_points(
    points: Sequence[tuple[float, float]],
    *,
    min_dt_ms: float = 2.0,
) -> tuple[tuple[float, float], ...]:
    """Sort envelope samples by time, decimate, keep onset/offset on baseline."""
    if len(points) < 3:
        return tuple((float(t), float(v)) for t, v in points)

    onset = (float(points[0][0]), float(points[0][1]))
    offset = (float(points[-1][0]), float(points[-1][1]))
    middle = sorted(
        ((float(t), float(v)) for t, v in points[1:-1]),
        key=lambda item: item[0],
    )

    filtered: list[tuple[float, float]] = [onset]
    for time_ms, velocity_cm_s in middle:
        if time_ms <= filtered[-1][0]:
            continue
        if time_ms - filtered[-1][0] < min_dt_ms:
            continue
        filtered.append((time_ms, velocity_cm_s))

    if offset[0] <= filtered[-1][0]:
        offset = (filtered[-1][0] + min_dt_ms, offset[1])
    filtered.append(offset)
    return tuple(filtered)


def filter_velocity_spikes(
    points: Sequence[tuple[float, float]],
    *,
    max_velocity_cm_s: float = 400.0,
    spike_threshold_cm_s: float = 100.0,
) -> tuple[tuple[float, float], ...]:
    """Remove sharp velocity spikes from an envelope by smoothing to neighbors.

    A point is flagged as a spike when **both** its absolute difference to the
    preceding point and its absolute difference to the following point exceed
    ``spike_threshold_cm_s``. The spike is then replaced by the arithmetic
    mean of those two neighbors — the "smoothing to neighboring points before
    and after the peak" described in the spec.

    All velocities are additionally clamped to ``±max_velocity_cm_s`` to
    filter extreme outliers (side-lobe artifacts, noise bursts).

    Returns a new sequence of ``(time_ms, velocity_cm_s)`` tuples. The input
    order is preserved; the caller should ensure points are sorted by time
    when order matters.
    """
    if len(points) < 3:
        return tuple((float(t), float(v)) for t, v in points)

    clamped = [(float(t), max(-max_velocity_cm_s, min(max_velocity_cm_s, float(v)))) for t, v in points]
    velocities = np.array([v for _, v in clamped], dtype=np.float64)
    n = len(velocities)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n - 1):
        if (
            abs(velocities[i] - velocities[i - 1]) > spike_threshold_cm_s
            and abs(velocities[i] - velocities[i + 1]) > spike_threshold_cm_s
        ):
            mask[i] = True
    for i in range(n):
        if mask[i]:
            clamped[i] = (clamped[i][0], (velocities[i - 1] + velocities[i + 1]) / 2.0)
    return tuple(clamped)
