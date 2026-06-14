"""Canonical LV endocardial Lamé open-arc warp profiles."""

from __future__ import annotations

import math
from dataclasses import dataclass

_MIN_SEMI_AXIS_PX = 1e-6


@dataclass(frozen=True)
class LameWarpProfile:
    """Piecewise asymmetric Lamé height multipliers along MA chord."""

    n_sept: float
    n_lat: float
    alpha_sept: float = 1.0
    alpha_lat: float = 1.0
    lift_scale: float = 1.0


LAME_A4C_ED = LameWarpProfile(
    n_sept=3.0, n_lat=2.1, alpha_sept=0.1, alpha_lat=1.0, lift_scale=1.0
)
LAME_A4C_ES = LameWarpProfile(
    n_sept=1.6, n_lat=1.6, alpha_sept=1.2, alpha_lat=0.9, lift_scale=1.0
)
LAME_A2C_ED = LameWarpProfile(
    n_sept=2.9, n_lat=3.1, alpha_sept=0.1, alpha_lat=1.0, lift_scale=0.98
)
LAME_A2C_ES = LameWarpProfile(
    n_sept=4.2, n_lat=4.5, alpha_sept=0.98, alpha_lat=1.0, lift_scale=0.96
)


def lame_profile_for_view_phase(view: str, phase: str) -> LameWarpProfile:
    """Return Lamé preset for view × phase; unknown → A4C ED."""
    view_key = view.upper()
    phase_key = phase.upper()
    is_a2c = view_key in {"A2C", "2C"}
    is_es = phase_key == "ES"
    if is_a2c and is_es:
        return LAME_A2C_ES
    if is_a2c:
        return LAME_A2C_ED
    if is_es:
        return LAME_A4C_ES
    return LAME_A4C_ED


def lame_lift_height(
    u: float,
    u_apex: float,
    ma_length: float,
    profile: LameWarpProfile,
) -> float:
    """Return h(u)/H multiplier ∈ [0, lift_scale] along MA parameter u."""
    if ma_length <= 0.0:
        return 0.0
    x = (u - u_apex) * ma_length
    if x <= 0.0:
        semi_axis = max(u_apex * ma_length / profile.alpha_sept, _MIN_SEMI_AXIS_PX)
        exponent = profile.n_sept
    else:
        semi_axis = max((1.0 - u_apex) * ma_length / profile.alpha_lat, _MIN_SEMI_AXIS_PX)
        exponent = profile.n_lat
    ratio = min(1.0, abs(x / semi_axis) ** exponent)
    lift = (1.0 - ratio) ** (1.0 / exponent)
    return profile.lift_scale * max(0.0, lift)


def _project_apex_param(
    apex: tuple[float, float],
    septal: tuple[float, float],
    lateral: tuple[float, float],
    ma_length: float,
) -> float:
    dx = lateral[0] - septal[0]
    dy = lateral[1] - septal[1]
    if ma_length <= 0.0:
        return 0.5
    t = ((apex[0] - septal[0]) * dx + (apex[1] - septal[1]) * dy) / (ma_length * ma_length)
    return max(0.0, min(1.0, t))


def warp_lame_open_arc(
    septal: tuple[float, float],
    lateral: tuple[float, float],
    apex: tuple[float, float],
    *,
    view: str = "A4C",
    phase: str = "ED",
    num_points: int = 81,
    profile: LameWarpProfile | None = None,
) -> list[tuple[float, float]]:
    """Sample open arc from septal to lateral via asymmetric Lamé lift along apex direction."""
    if num_points < 3:
        msg = "num_points must be at least 3"
        raise ValueError(msg)

    ma_dx = lateral[0] - septal[0]
    ma_dy = lateral[1] - septal[1]
    ma_length = math.hypot(ma_dx, ma_dy)
    if ma_length <= 0.0:
        msg = "mitral annulus length must be positive"
        raise ValueError(msg)

    warp_profile = profile or lame_profile_for_view_phase(view, phase)
    u_apex = _project_apex_param(apex, septal, lateral, ma_length)
    foot_x = (1.0 - u_apex) * septal[0] + u_apex * lateral[0]
    foot_y = (1.0 - u_apex) * septal[1] + u_apex * lateral[1]
    dir_x = apex[0] - foot_x
    dir_y = apex[1] - foot_y
    apex_height = math.hypot(dir_x, dir_y)
    if apex_height <= 0.0:
        msg = "apex must be off the mitral annulus line"
        raise ValueError(msg)

    dir_x /= apex_height
    dir_y /= apex_height
    warped: list[tuple[float, float]] = []
    for index in range(num_points):
        u = index / (num_points - 1)
        base_x = (1.0 - u) * septal[0] + u * lateral[0]
        base_y = (1.0 - u) * septal[1] + u * lateral[1]
        lift = lame_lift_height(u, u_apex, ma_length, warp_profile) * apex_height
        warped.append((base_x + lift * dir_x, base_y + lift * dir_y))
    warped[0] = septal
    warped[-1] = lateral
    return warped
