"""Teichholz and ejection-fraction formulas (pure arithmetic, no domain models).

The calculator registry needs the formulas but not the models that
:mod:`echo_personal_tool.domain.calculations.teichholz` builds from calipers.
Keeping them in a leaf module stops the registry, the result models and the
caliper adapter from forming an import cycle (#328); ``teichholz`` re-exports
every name for existing callers.
"""

from __future__ import annotations

import math


def volume_ml(dimension_mm: float) -> float:
    """Teichholz cube formula. dimension in mm, returns mL."""
    l_cm = dimension_mm / 10.0
    if not math.isfinite(l_cm) or l_cm <= 0:
        raise ValueError("dimension must be positive and finite")
    return (7.0 / (2.4 + l_cm)) * (l_cm**3)


def volume_from_cm_ml(dimension_cm: float | None) -> float | None:
    """Teichholz volume, mL, for a diameter in cm; ``None`` for a missing/non-positive one."""
    if dimension_cm is None or not math.isfinite(dimension_cm) or not dimension_cm > 0:
        return None
    return volume_ml(dimension_cm * 10.0)


def fractional_shortening_percent(lvedd_cm: float | None, lvesd_cm: float | None) -> float | None:
    """Fractional shortening, %: ``(LVEDD − LVESD) / LVEDD × 100``.

    ``None`` when LVESD is not smaller than LVEDD (labels swapped / wrong phase).
    """
    if (
        lvedd_cm is None
        or lvesd_cm is None
        or not math.isfinite(lvedd_cm)
        or not math.isfinite(lvesd_cm)
        or not lvedd_cm > 0
        or not lvesd_cm > 0
        or lvesd_cm >= lvedd_cm
    ):
        return None
    return (lvedd_cm - lvesd_cm) / lvedd_cm * 100.0


def ejection_fraction_percent(edv_ml: float | None, esv_ml: float | None) -> float | None:
    """EF, %: ``(EDV − ESV) / EDV × 100``; ``None`` when ESV is not smaller than EDV."""
    if (
        edv_ml is None
        or esv_ml is None
        or not math.isfinite(edv_ml)
        or not math.isfinite(esv_ml)
        or not edv_ml > 0
        or not esv_ml > 0
        or esv_ml >= edv_ml
    ):
        return None
    return (edv_ml - esv_ml) / edv_ml * 100.0
