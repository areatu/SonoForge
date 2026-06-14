"""ASE 2016 diastolic function grading (simplified algorithm)."""

from __future__ import annotations


def grade_diastolic_function(
    *,
    e_over_e_prime: float | None,
    lav_index_ml_m2: float | None,
    tr_vmax_cm_s: float | None,
    age_years: float | None = None,
) -> str | None:
    """Return ASE 2016-style grade label from available indices.

    Simplified rules when full dataset is incomplete:
    - E/e' > 14 → abnormal (Grade II+ if LAVi elevated)
    - E/e' 9–14 → indeterminate / Grade I
    - E/e' < 9 with normal LAVi → normal
    """
    if e_over_e_prime is None:
        return None

    lav_elevated = lav_index_ml_m2 is not None and lav_index_ml_m2 > 34.0
    tr_elevated = tr_vmax_cm_s is not None and tr_vmax_cm_s > 280.0

    if e_over_e_prime >= 14.0:
        if lav_elevated or tr_elevated:
            return "Grade II (abnormal)"
        return "Grade I (elevated E/e')"
    if e_over_e_prime >= 9.0:
        return "Grade I (indeterminate)"
    if lav_elevated:
        return "Grade I (normal E/e', elevated LAVi)"
    return "Normal"
