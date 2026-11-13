"""Compute surrogate vessel indices from manual PSV/EDV values."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class VesselMetrics:
    ri: float | None
    sd: float | None
    mv_approx: float | None
    valid: bool


def compute_vessel_metrics(psv_cm_s: float, edv_cm_s: float) -> VesselMetrics:
    """Vessel indices from manual PSV/EDV values.

    A non-finite input (NaN, ±∞) cannot define a measurement: every derived
    value stays ``None`` and ``valid`` is false.  A negative EDV is not
    rejected — reversed diastolic flow is real — but S/D is only defined for a
    positive denominator; RI remains the signed resistance index (#549).
    """
    finite_inputs = math.isfinite(psv_cm_s) and math.isfinite(edv_cm_s)
    valid = finite_inputs and psv_cm_s > 0 and edv_cm_s <= psv_cm_s
    if not valid:
        return VesselMetrics(ri=None, sd=None, mv_approx=None, valid=False)
    ri = (psv_cm_s - edv_cm_s) / psv_cm_s
    sd = psv_cm_s / edv_cm_s if edv_cm_s > 0 else None
    mv_approx = (psv_cm_s + 2 * edv_cm_s) / 3.0
    derived = tuple(value for value in (ri, sd, mv_approx) if value is not None)
    if not all(math.isfinite(value) for value in derived):
        return VesselMetrics(ri=None, sd=None, mv_approx=None, valid=False)
    return VesselMetrics(ri=ri, sd=sd, mv_approx=mv_approx, valid=True)
