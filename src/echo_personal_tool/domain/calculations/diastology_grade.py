"""ASE 2016 diastolic function grading (simplified algorithm)."""

from __future__ import annotations

#: Numeric grade codes returned by :func:`grade_diastolic_code`.
GRADE_NORMAL = 0
GRADE_INDETERMINATE = 1
GRADE_ABNORMAL = 2
GRADE_INSUFFICIENT = 3


def grade_diastolic_code(
    *,
    e_over_e_prime: float | None = None,
    lav_index_ml_m2: float | None = None,
    tr_vmax_cm_s: float | None = None,
    e_prime_sept_cm_s: float | None = None,
    e_prime_lat_cm_s: float | None = None,
    age_years: float | None = None,
) -> int | None:
    """Return ASE 2016-style category as a numeric code.

    Simplified majority-rule criteria-based assessment:
    - E/e' > 14
    - septal e' < 7 cm/s (or lateral e' < 10 cm/s)
    - LAVi > 34 mL/m²
    - TR Vmax > 280 cm/s (2.8 m/s)

    Codes: 0 = Normal, 1 = Indeterminate, 2 = Abnormal, 3 = Insufficient data,
    None = no data at all.

    Velocity inputs are compared by magnitude: storage keeps the signed
    calibration truth (below-baseline jets read negative), so a TR jet of
    -312 cm/s still meets the > 280 cm/s criterion (Э2 sign normalization).
    """
    criteria = []

    if e_over_e_prime is not None:
        criteria.append(abs(e_over_e_prime) > 14.0)

    if e_prime_sept_cm_s is not None:
        criteria.append(abs(e_prime_sept_cm_s) < 7.0)
    elif e_prime_lat_cm_s is not None:
        criteria.append(abs(e_prime_lat_cm_s) < 10.0)

    if lav_index_ml_m2 is not None:
        criteria.append(lav_index_ml_m2 > 34.0)

    if tr_vmax_cm_s is not None:
        criteria.append(abs(tr_vmax_cm_s) > 280.0)

    if not criteria:
        return None

    positive = sum(criteria)
    total = len(criteria)

    if total < 3:
        return GRADE_INSUFFICIENT
    if positive / total > 0.5:
        return GRADE_ABNORMAL
    if positive / total < 0.5:
        return GRADE_NORMAL
    return GRADE_INDETERMINATE


def grade_diastolic_label(code: int | None, *, language: str = "en") -> str:
    """Human-readable label for a :func:`grade_diastolic_code` result."""
    labels = {
        "en": {
            GRADE_NORMAL: "Normal",
            GRADE_INDETERMINATE: "Indeterminate",
            GRADE_ABNORMAL: "Abnormal",
            GRADE_INSUFFICIENT: "Insufficient data",
            None: "",
        },
        "ru": {
            GRADE_NORMAL: "Норма",
            GRADE_INDETERMINATE: "Неопределено",
            GRADE_ABNORMAL: "Нарушение ДФ",
            GRADE_INSUFFICIENT: "Недостаточно данных",
            None: "",
        },
    }
    return labels.get(language, labels["en"]).get(code, "")


def grade_diastolic_function(
    *,
    e_over_e_prime: float | None = None,
    lav_index_ml_m2: float | None = None,
    tr_vmax_cm_s: float | None = None,
    e_prime_sept_cm_s: float | None = None,
    e_prime_lat_cm_s: float | None = None,
    age_years: float | None = None,
    language: str = "en",
) -> str | None:
    """Return ASE 2016-style category label from available indices.

    Simplified majority-rule criteria-based assessment:
    - E/e' > 14
    - septal e' < 7 cm/s (or lateral e' < 10 cm/s)
    - LAVi > 34 mL/m²
    - TR Vmax > 280 cm/s (2.8 m/s)

    Returns the Normal / Indeterminate / Abnormal label (English by default;
    use :func:`grade_diastolic_label` for UI localization) or ``None`` when
    fewer than three criteria are available (insufficient data / no data).

    Velocity inputs are compared by magnitude: storage keeps the signed
    calibration truth (below-baseline jets read negative), so a TR jet of
    -312 cm/s still meets the > 280 cm/s criterion (Э2 sign normalization).
    """
    code = grade_diastolic_code(
        e_over_e_prime=e_over_e_prime,
        lav_index_ml_m2=lav_index_ml_m2,
        tr_vmax_cm_s=tr_vmax_cm_s,
        e_prime_sept_cm_s=e_prime_sept_cm_s,
        e_prime_lat_cm_s=e_prime_lat_cm_s,
        age_years=age_years,
    )
    if code not in (GRADE_NORMAL, GRADE_INDETERMINATE, GRADE_ABNORMAL):
        return None
    return grade_diastolic_label(code, language=language)
