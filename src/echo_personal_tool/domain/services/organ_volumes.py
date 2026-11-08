"""Organ volumes from three linear dimensions (general ultrasound).

The owner's rule for non-cardiac studies: a volume is measured the way ordinary
ultrasound scanners do it — three orthogonal dimensions and an ellipsoid
coefficient.  The coefficient is organ-specific, so it lives here rather than
in one formula used for every organ:

* thyroid lobes — 0.479 (Brunn's coefficient, the one thyroid volume
  references are built on);
* kidney, urinary bladder and the generic «объём по трём измерениям» tool —
  0.523 (the ellipsoid constant, ``π / 6``).

Dimensions enter in millimetres (the application's default linear unit) and the
result is millilitres: ``1 mL = 1000 mm³``.  The module is pure domain — no Qt,
no report vocabulary — so the report, the panel and the tests share one formula.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Ellipsoid coefficient ``π / 6``; kidney, bladder and the generic organ tool.
VOLUME_COEFFICIENT_ELLIPSOID = 0.523
#: Brunn's coefficient of thyroid lobe volume.
VOLUME_COEFFICIENT_THYROID = 0.479
#: Cubic millimetres in one millilitre.
MM3_PER_ML = 1000.0


def volume_ml(dimensions_mm: Sequence[float], *, coefficient: float) -> float | None:
    """Ellipsoid volume of three dimensions in millimetres, in millilitres.

    ``None`` when the caller does not have all three dimensions (an unfilled
    triplet must not read as a zero volume).
    """
    if len(dimensions_mm) != 3:
        raise ValueError(f"exactly three dimensions are required, got {len(dimensions_mm)}")
    values = tuple(float(value) for value in dimensions_mm)
    if any(value <= 0.0 for value in values):
        return None
    return coefficient * values[0] * values[1] * values[2] / MM3_PER_ML


def bladder_volume_ml(length_mm: float, width_mm: float, depth_mm: float) -> float | None:
    """Urinary bladder volume: ellipsoid over length, width and depth."""
    return volume_ml((length_mm, width_mm, depth_mm), coefficient=VOLUME_COEFFICIENT_ELLIPSOID)


def thyroid_lobe_volume_ml(length_mm: float, width_mm: float, thickness_mm: float) -> float | None:
    """Volume of one thyroid lobe: Brunn's formula over sagittal, width and AP."""
    return volume_ml((length_mm, width_mm, thickness_mm), coefficient=VOLUME_COEFFICIENT_THYROID)


def organ_volume_ml(first_mm: float, second_mm: float, third_mm: float) -> float | None:
    """Generic «объём по трём измерениям» of a non-cardiac organ (ellipsoid)."""
    return volume_ml(
        (first_mm, second_mm, third_mm),
        coefficient=VOLUME_COEFFICIENT_ELLIPSOID,
    )
