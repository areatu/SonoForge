"""Domain model for a manual vessel Doppler measurement (PSV/EDV)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VesselMeasurement:
    psv_cm_s: float
    edv_cm_s: float
    ri: float | None
    sd: float | None
    mv_approx: float
    sop_instance_uid: str
    frame_index: int
    calibration_id: str | None = None
    cycle_source: str = "manual"
    averaged_cycles: int = 1
    #: Stable measurement ID for provenance (QH-1b.1). Empty for legacy docs.
    measurement_id: str = ""
    #: Content revision, incremented on each edit (QH-1b.1).
    revision: int = 0
