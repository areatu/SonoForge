"""PISA (proximal isovelocity surface area) for valvular regurgitation (Э11б).

Pure functions, no Qt.  Every function returns ``None`` when an input is
missing or not physically meaningful — a calculation never substitutes a
"typical" value (no simplified ``r²/2`` shortcut that silently assumes
Va = 40 cm/s and Vmax = 5 m/s).

Units are explicit in every parameter name.  Formulas follow:

* Zoghbi WA et al. Recommendations for noninvasive evaluation of native
  valvular regurgitation: a report from the ASE developed with the SCMR.
  J Am Soc Echocardiogr 2017;30:303–371 — hemispheric PISA flow rate, EROA,
  regurgitant volume and fraction for MR and AR.
* Lancellotti P et al. Recommendations for the echocardiographic assessment of
  native valvular regurgitation: an executive summary from the EACVI.
  Eur Heart J Cardiovasc Imaging 2013;14:611–644 — same method, RF definitions.
"""

from __future__ import annotations

import math


def _positive(*values: float | None) -> bool:
    return all(value is not None and math.isfinite(value) and value > 0.0 for value in values)


def pisa_flow_rate_ml_s(radius_cm: float | None, aliasing_velocity_cm_s: float | None) -> float | None:
    """Peak regurgitant flow rate, mL/s: ``2π · r² · Va`` (hemispheric shell)."""
    if not _positive(radius_cm, aliasing_velocity_cm_s):
        return None
    return 2.0 * math.pi * radius_cm * radius_cm * aliasing_velocity_cm_s


def eroa_cm2(flow_rate_ml_s: float | None, jet_vmax_cm_s: float | None) -> float | None:
    """Effective regurgitant orifice area, cm²: flow rate / peak jet velocity (CW)."""
    if not _positive(flow_rate_ml_s, jet_vmax_cm_s):
        return None
    return flow_rate_ml_s / jet_vmax_cm_s


def regurgitant_volume_ml(eroa: float | None, jet_vti_cm: float | None) -> float | None:
    """Regurgitant volume, mL: EROA × VTI of the regurgitant jet (CW)."""
    if not _positive(eroa, jet_vti_cm):
        return None
    return eroa * jet_vti_cm


def regurgitant_fraction_mr_percent(rvol_ml: float | None, forward_sv_ml: float | None) -> float | None:
    """MR fraction, %: ``RVol / (RVol + SV_LVOT)``.

    The LVOT stroke volume is the *forward* flow in MR, so the total LV stroke
    volume through the mitral valve is their sum.  Valid without significant
    aortic regurgitation.
    """
    if not _positive(rvol_ml, forward_sv_ml):
        return None
    return 100.0 * rvol_ml / (rvol_ml + forward_sv_ml)


def regurgitant_fraction_ar_percent(rvol_ml: float | None, lvot_sv_ml: float | None) -> float | None:
    """AR fraction, %: ``RVol / SV_LVOT``.

    In AR the LVOT stroke volume carries forward *and* regurgitant flow, so it
    is the total.  A result above 100 % means inconsistent inputs and is
    returned as is (the engine warns) rather than clamped.
    """
    if not _positive(rvol_ml, lvot_sv_ml):
        return None
    return 100.0 * rvol_ml / lvot_sv_ml
