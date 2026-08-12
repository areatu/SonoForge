"""ASE 2016 diastolic function grading (simplified algorithm)."""

from __future__ import annotations


def grade_diastolic_function(
    *,
    e_over_e_prime: float | None,
    lav_index_ml_m2: float | None,
    tr_vmax_cm_s: float | None,
    e_prime_sept_cm_s: float | None = None,
    e_prime_lat_cm_s: float | None = None,
    age_years: float | None = None,
) -> str | None:
    """Return ASE 2016-style category label from available indices.

    Simplified majority-rule criteria-based assessment:
    - E/e' > 14
    - septal e' < 7 cm/s (or lateral e' < 10 cm/s)
    - LAVi > 34 mL/m²
    - TR Vmax > 280 cm/s (2.8 m/s)

    Returns Normal / Indeterminate / Abnormal / Insufficient data / None.
    """
    criteria = []

    if e_over_e_prime is not None:
        criteria.append(e_over_e_prime > 14.0)

    if e_prime_sept_cm_s is not None:
        criteria.append(e_prime_sept_cm_s < 7.0)
    elif e_prime_lat_cm_s is not None:
        criteria.append(e_prime_lat_cm_s < 10.0)

    if lav_index_ml_m2 is not None:
        criteria.append(lav_index_ml_m2 > 34.0)

    if tr_vmax_cm_s is not None:
        criteria.append(tr_vmax_cm_s > 280.0)

    if not criteria:
        return None

    positive = sum(criteria)
    total = len(criteria)

    if total < 3:
        return None
    if positive / total > 0.5:
        return "Abnormal"
    if positive / total < 0.5:
        return "Normal"
    return "Indeterminate"
