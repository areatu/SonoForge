"""Canonical LV endocardial arc warp profiles for MBS-lite."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArcWarpProfile:
    """Parameters for sinusoidal dome warp over the mitral annulus chord."""

    apex_lift_scale: float = 1.0
    peak_bias: float = 0.0


ARC_WARP_A4C = ArcWarpProfile()
ARC_WARP_A2C = ArcWarpProfile(apex_lift_scale=0.98, peak_bias=0.06)


def warp_profile_for_view(view: str) -> ArcWarpProfile:
    """Return dome warp profile for the requested projection."""
    if view.upper() in {"A2C", "2C"}:
        return ARC_WARP_A2C
    return ARC_WARP_A4C
