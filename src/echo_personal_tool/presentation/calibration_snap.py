"""Snap Y coordinate to nearest depth scale tick during calibration."""

from __future__ import annotations


def snap_y_to_nearest_tick(
    y: float,
    ticks: list[float],
    *,
    radius_px: float = 8.0,
) -> float:
    if not ticks:
        return y
    best = min(ticks, key=lambda t: abs(t - y))
    if abs(best - y) <= radius_px:
        return best
    return y
