"""Ventricular dP/dt from the ascending limb of a regurgitant CW jet (Э11).

Pure functions, no Qt.  The user measures the time the jet velocity needs to
rise between two fixed velocities; by the simplified Bernoulli equation that
interval corresponds to a fixed pressure rise, so ``dP/dt = ΔP / Δt``.

* LV, mitral regurgitation, 1 → 3 m/s: ``ΔP = 4·3² − 4·1² = 32 mmHg``.
  Bargiggia GS et al. Circulation 1989;80:1287–1292.
* RV, tricuspid regurgitation, 1 → 2 m/s: ``ΔP = 4·2² − 4·1² = 12 mmHg``.
  Rudski LG et al. J Am Soc Echocardiogr 2010;23:685–713.

Every function returns ``None`` when the interval is missing or not positive.
"""

from __future__ import annotations

import math

#: Pressure rise between 1 and 3 m/s of the MR jet (LV dP/dt), mmHg.
LV_DPDT_DELTA_P_MMHG = 4.0 * 3.0**2 - 4.0 * 1.0**2
#: Pressure rise between 1 and 2 m/s of the TR jet (RV dP/dt), mmHg.
RV_DPDT_DELTA_P_MMHG = 4.0 * 2.0**2 - 4.0 * 1.0**2


def dpdt_mmhg_s(delta_p_mmhg: float, interval_ms: float | None) -> float | None:
    """Mean rate of pressure rise, mmHg/s, over *interval_ms* milliseconds."""
    if interval_ms is None or not math.isfinite(interval_ms) or interval_ms <= 0.0:
        return None
    return delta_p_mmhg / (interval_ms / 1000.0)


def lv_dpdt_mmhg_s(mr_interval_ms: float | None) -> float | None:
    """LV dP/dt from the MR jet: 32 mmHg over the 1 → 3 m/s interval."""
    return dpdt_mmhg_s(LV_DPDT_DELTA_P_MMHG, mr_interval_ms)


def rv_dpdt_mmhg_s(tr_interval_ms: float | None) -> float | None:
    """RV dP/dt from the TR jet: 12 mmHg over the 1 → 2 m/s interval."""
    return dpdt_mmhg_s(RV_DPDT_DELTA_P_MMHG, tr_interval_ms)
