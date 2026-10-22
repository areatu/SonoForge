"""Teichholz LV function calculation from M-mode calipers."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.body_surface import bsa_du_bois_m2
from echo_personal_tool.domain.calculations.lvm import lvm_grams
from echo_personal_tool.domain.calculations.rwt import relative_wall_thickness
from echo_personal_tool.domain.calculations.teichholz import volume_ml
from echo_personal_tool.domain.models.mmode import TeichholzMModeResult


def compute_teichholz_from_mmode(
    ivsd_mm: float,
    lvidd_mm: float,
    lvpwd_mm: float,
    *,
    lvesd_mm: float | None = None,
    height_cm: float | None = None,
    weight_kg: float | None = None,
) -> TeichholzMModeResult:
    """Compute Teichholz LV function from M-mode calipers.

    Parameters
    ----------
    ivsd_mm : float
        Interventricular septum thickness (diastolic), mm.
    lvidd_mm : float
        LV internal diameter (diastolic), mm.
    lvpwd_mm : float
        LV posterior wall thickness (diastolic), mm.
    lvesd_mm : float | None
        LV internal diameter (systolic), mm. If provided, ESV and EF are computed.
    height_cm : float | None
        Patient height for LVMI calculation.
    weight_kg : float | None
        Patient weight for LVMI calculation.
    """
    edv_ml = volume_ml(lvidd_mm)

    esv_ml = None
    lvef_percent = None
    if lvesd_mm is not None and lvesd_mm > 0:
        esv_ml = volume_ml(lvesd_mm)
        lvef_percent = (edv_ml - esv_ml) / edv_ml * 100.0

    rwt = relative_wall_thickness(lvpwd_mm, lvidd_mm)
    lvm = lvm_grams(ivsd_mm, lvidd_mm, lvpwd_mm)

    lvmi = None
    if lvm is not None and height_cm is not None and weight_kg is not None:
        bsa = bsa_du_bois_m2(height_cm, weight_kg)
        if bsa is not None and bsa > 0:
            lvmi = lvm / bsa

    return TeichholzMModeResult(
        ivsd_mm=ivsd_mm,
        lvidd_mm=lvidd_mm,
        lvpwd_mm=lvpwd_mm,
        edv_ml=edv_ml,
        esv_ml=esv_ml,
        lvef_percent=lvef_percent,
        rwt=rwt,
        lvm_g=lvm,
        lvmi_g_m2=lvmi,
    )
