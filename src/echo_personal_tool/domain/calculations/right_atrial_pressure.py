"""Right atrial pressure (RAP / ДПЖ) from the inferior vena cava (НПВ).

ASE right-heart guideline: the IVC diameter and its respiratory
collapsibility estimate the RA pressure category — 3 / 8 / 15 mmHg.
The M-mode pair (expiration, inspiration) supplies both inputs at
once; the 2D diameter alone is not enough, the collapse is required.
"""

from __future__ import annotations

import math


def _finite(*values: float | None) -> bool:
    return all(value is not None and math.isfinite(value) for value in values)


def ivc_collapse_percent(expiration_mm: float | None, inspiration_mm: float | None) -> float | None:
    """Respiratory collapse of the IVC, %: ``(exp − insp) / exp · 100``.

    ``None`` unless both diameters are finite positive numbers.
    """
    if not _finite(expiration_mm, inspiration_mm):
        return None
    assert expiration_mm is not None and inspiration_mm is not None
    if expiration_mm <= 0 or inspiration_mm < 0:
        return None
    return (expiration_mm - inspiration_mm) / expiration_mm * 100.0


def rap_from_ivc(diameter_cm: float | None, collapse_percent: float | None) -> int | None:
    """RA pressure category, mmHg, from IVC size and collapse.

    * ``≤ 2.1 cm`` and ``> 50 %`` collapse → 3 (normal),
    * ``> 2.1 cm`` and ``< 50 %`` collapse → 15 (high),
    * every other pattern → 8 (intermediate).

    ``None`` when either input is missing or out of range.
    """
    if not _finite(diameter_cm, collapse_percent):
        return None
    assert diameter_cm is not None and collapse_percent is not None
    if diameter_cm <= 0 or not 0.0 <= collapse_percent <= 100.0:
        return None
    if diameter_cm <= 2.1 and collapse_percent > 50.0:
        return 3
    if diameter_cm > 2.1 and collapse_percent < 50.0:
        return 15
    return 8


def rap_from_ivc_pair(
    expiration_mm: float | None, inspiration_mm: float | None
) -> tuple[float | None, int | None]:
    """``(collapse_percent, rap_mmhg)`` from the M-mode expiration/inspiration pair.

    The expiratory diameter is the distended one, so it feeds the size
    criterion; the inspiratory one supplies the collapse.
    """
    collapse = ivc_collapse_percent(expiration_mm, inspiration_mm)
    diameter_cm = expiration_mm / 10.0 if _finite(expiration_mm) else None
    return collapse, rap_from_ivc(diameter_cm, collapse)
