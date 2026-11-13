"""Simplified Bernoulli pressure gradient."""

from __future__ import annotations

import math


def pressure_gradient_mmhg(velocity_cm_s: float) -> float | None:
    """Simplified Bernoulli: PG = 4 * v^2 with v in m/s.

    A non-finite velocity cannot produce a printable gradient; returning
    ``None`` keeps NaN/∞ from becoming a result row (#549).
    """
    if not math.isfinite(velocity_cm_s):
        return None
    v_m_s = velocity_cm_s / 100.0
    return 4.0 * v_m_s * v_m_s
