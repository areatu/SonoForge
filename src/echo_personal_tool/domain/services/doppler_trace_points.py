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
    max_velocity_cm_s: float | None = 400.0,
    window_half: int = 3,
    k_mad: float = 3.0,
) -> tuple[tuple[float, float], ...]:
    """Remove sharp velocity spikes using a rolling median filter.

    For each point, a local median is computed over a sliding window of
    ``2 * window_half + 1`` points (or fewer at the edges).  Points whose
    absolute deviation from the local median exceeds ``k_mad`` times the
    local MAD (Median Absolute Deviation) are replaced by the median.

    All velocities are additionally clamped to ``±max_velocity_cm_s`` to
    filter extreme outliers (side-lobe artifacts, noise bursts).

    Returns a new sequence of ``(time_ms, velocity_cm_s)`` tuples.  The
    input order is preserved; the caller should ensure points are sorted
    by time when order matters.
    """
    if len(points) < 3:
        return tuple((float(t), float(v)) for t, v in points)

    if max_velocity_cm_s is None:
        max_velocity_cm_s = float("inf")
    clamped = [(float(t), max(-max_velocity_cm_s, min(max_velocity_cm_s, float(v)))) for t, v in points]
    velocities = np.array([v for _, v in clamped], dtype=np.float64)
    n = len(velocities)
    result = velocities.copy()

    for i in range(n):
        lo = max(0, i - window_half)
        hi = min(n, i + window_half + 1)
        window = velocities[lo:hi]
        med = float(np.median(window))
        mad = float(np.median(np.abs(window - med)))
        if mad < 1e-6:
            continue
        if abs(velocities[i] - med) > k_mad * mad:
            result[i] = med

    return tuple((clamped[i][0], float(result[i])) for i in range(n))
