"""Mitral valve area in mitral stenosis (Э11в).

Pure functions, no Qt.  Every function returns ``None`` when an input is
missing or not physically meaningful — no typical value is substituted (the
funnel angle α and the aliasing velocity must be supplied by the user).

Formulas follow Baumgartner H et al. Echocardiographic assessment of valve
stenosis: EAE/ASE recommendations for clinical practice.
J Am Soc Echocardiogr 2009;22:1–23:

* MVA by pressure half-time (Hatle): ``220 / PHT`` — empirical constant.
* MVA by PISA: ``2π · r² · (α/180°) · Va / Vmax`` — hemispheric shell
  corrected for the funnel angle of the mitral leaflets.
"""

from __future__ import annotations

import math

#: Empirical constant of the Hatle formula (cm²·ms).
HATLE_CONSTANT = 220.0


def _positive(*values: float | None) -> bool:
    return all(value is not None and math.isfinite(value) and value > 0.0 for value in values)


def mva_pht_cm2(pht_ms: float | None) -> float | None:
    """Mitral valve area, cm²: ``220 / PHT`` (PHT in ms)."""
    if not _positive(pht_ms):
        return None
    return HATLE_CONSTANT / pht_ms


def mva_pisa_cm2(
    radius_cm: float | None,
    aliasing_velocity_cm_s: float | None,
    peak_velocity_cm_s: float | None,
    angle_deg: float | None,
) -> float | None:
    """Mitral valve area by PISA, cm²: ``2π r² · α/180 · Va / Vmax``.

    ``angle_deg`` is the angle between the mitral leaflets on the atrial side
    (funnel angle α); 180° reduces to the flat-orifice form.
    """
    if not _positive(radius_cm, aliasing_velocity_cm_s, peak_velocity_cm_s, angle_deg):
        return None
    if angle_deg > 180.0:
        return None
    flow = 2.0 * math.pi * radius_cm * radius_cm * aliasing_velocity_cm_s
    return flow * (angle_deg / 180.0) / peak_velocity_cm_s
