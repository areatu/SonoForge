"""Continuity-equation hemodynamics (Э11а): LVOT area, SV, CO, AVA, DVI.

Pure functions, no Qt.  Every function returns ``None`` when an input is
missing or not physically meaningful (zero/negative) — a calculation never
substitutes a "typical" value for an absent measurement (project rule,
``docs/HELP_RU.md``).

Units are explicit in every parameter name.  Formulas follow:

* Quiñones MA et al. Recommendations for quantification of Doppler
  echocardiography. J Am Soc Echocardiogr 2002;15:167–184 — LVOT CSA, SV, CO.
* Baumgartner H et al. Recommendations on the echocardiographic assessment of
  aortic valve stenosis: a focused update from the EACVI and the ASE.
  J Am Soc Echocardiogr 2017;30:372–392 — continuity AVA (VTI and Vmax forms),
  velocity ratio (DVI), AVA indexed to BSA, SVi.
"""

from __future__ import annotations

import math


def _positive(*values: float | None) -> bool:
    return all(value is not None and math.isfinite(value) and value > 0.0 for value in values)


def lvot_area_cm2(lvot_diameter_cm: float | None) -> float | None:
    """LVOT cross-sectional area, cm²: ``π · (D/2)²`` (circular LVOT assumed)."""
    if not _positive(lvot_diameter_cm):
        return None
    radius = lvot_diameter_cm / 2.0
    return math.pi * radius * radius


def stroke_volume_ml(lvot_area: float | None, lvot_vti_cm: float | None) -> float | None:
    """Stroke volume, mL: ``LVOT area (cm²) × LVOT VTI (cm)`` (1 cm³ = 1 mL)."""
    if not _positive(lvot_area, lvot_vti_cm):
        return None
    return lvot_area * lvot_vti_cm


def cardiac_output_l_min(stroke_volume: float | None, heart_rate_bpm: float | None) -> float | None:
    """Cardiac output, L/min: ``SV (mL) × HR (bpm) / 1000``."""
    if not _positive(stroke_volume, heart_rate_bpm):
        return None
    return stroke_volume * heart_rate_bpm / 1000.0


def indexed_to_bsa(value: float | None, bsa_m2: float | None) -> float | None:
    """Any quantity divided by body surface area (SVi, CI, AVAi)."""
    if not _positive(value, bsa_m2):
        return None
    return value / bsa_m2


def ava_continuity_cm2(
    lvot_area: float | None,
    lvot_flow: float | None,
    av_flow: float | None,
) -> float | None:
    """Continuity AVA, cm²: ``LVOT area × LVOT flow / AV flow``.

    ``lvot_flow`` and ``av_flow`` are either both VTIs (cm) — the reference
    method — or both peak velocities **in the same unit** (simplified Vmax
    form).  The caller is responsible for unit consistency.
    """
    if not _positive(lvot_area, lvot_flow, av_flow):
        return None
    return lvot_area * lvot_flow / av_flow


def dimensionless_index(lvot_flow: float | None, av_flow: float | None) -> float | None:
    """Velocity ratio / DVI: ``LVOT VTI / AV VTI`` or ``LVOT Vmax / AV Vmax``.

    Independent of the LVOT diameter, so it carries no squared diameter error.
    Both arguments must be in the same unit.
    """
    if not _positive(lvot_flow, av_flow):
        return None
    return lvot_flow / av_flow
