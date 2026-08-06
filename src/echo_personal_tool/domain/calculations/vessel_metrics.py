"""Compute surrogate vessel indices from manual PSV/EDV values."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VesselMetrics:
    ri: float | None
    sd: float | None
    mv_approx: float | None
    valid: bool


def compute_vessel_metrics(psv_cm_s: float, edv_cm_s: float) -> VesselMetrics:
    valid = psv_cm_s > 0 and edv_cm_s <= psv_cm_s
    ri = (psv_cm_s - edv_cm_s) / psv_cm_s if valid else None
    sd = psv_cm_s / edv_cm_s if valid and edv_cm_s > 0 else None
    mv_approx = (psv_cm_s + 2 * edv_cm_s) / 3.0 if valid else None
    return VesselMetrics(ri=ri, sd=sd, mv_approx=mv_approx, valid=valid)
