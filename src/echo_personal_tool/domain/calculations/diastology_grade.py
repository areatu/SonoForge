"""ASE 2016 diastolic function grading (simplified algorithm).

Plan А.10 (issue #648): the criteria table below is the single source of
truth for the grade (this module) and for the assessment display (the А.10
workflow, the calculator card and the report section), so the thresholds
cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Numeric grade codes returned by :func:`grade_diastolic_code`.
GRADE_NORMAL = 0
GRADE_INDETERMINATE = 1
GRADE_ABNORMAL = 2
GRADE_INSUFFICIENT = 3

#: ASE 2016 simplified-algorithm thresholds. Velocities are compared by
#: magnitude: storage keeps the signed calibration truth (below-baseline jets
#: read negative), so a TR jet of -312 cm/s still meets the > 280 cm/s
#: criterion (Э2 sign normalization).
E_OVER_E_PRIME_LIMIT = 14.0
E_PRIME_SEPT_MIN_CM_S = 7.0
E_PRIME_LAT_MIN_CM_S = 10.0
LAV_INDEX_LIMIT_ML_M2 = 34.0
TR_VMAX_LIMIT_CM_S = 280.0

#: Criterion ids in the fixed ASE display order.
CRITERION_E_OVER_E_PRIME = "e_over_e_prime"
CRITERION_E_PRIME = "e_prime"
CRITERION_LAV_INDEX = "lav_index"
CRITERION_TR_VMAX = "tr_vmax"

#: The four simplified inputs; a missing one is reported, never substituted.
ASE_INPUT_ORDER: tuple[str, ...] = (
    CRITERION_E_OVER_E_PRIME,
    CRITERION_E_PRIME,
    CRITERION_LAV_INDEX,
    CRITERION_TR_VMAX,
)


@dataclass(frozen=True)
class DiastolicCriterion:
    """One simplified-algorithm criterion row: value, verdict, threshold.

    ``limit`` is the language-neutral display form of the threshold (numbers
    and units only — «> 14», «< 7 cm/s»), so every consumer renders the same
    rule while its own localization supplies the wording around it.
    """

    id: str
    value: float
    met: bool
    limit: str


def diastolic_criteria(
    *,
    e_over_e_prime: float | None = None,
    lav_index_ml_m2: float | None = None,
    tr_vmax_cm_s: float | None = None,
    e_prime_sept_cm_s: float | None = None,
    e_prime_lat_cm_s: float | None = None,
) -> tuple[DiastolicCriterion, ...]:
    """The four simplified criteria as rows in ASE display order.

    Absent inputs produce no row (the caller reports them as missing); the
    septal e′ is preferred over the lateral one exactly like the grade below.
    """
    rows: list[DiastolicCriterion] = []
    if e_over_e_prime is not None:
        rows.append(
            DiastolicCriterion(
                CRITERION_E_OVER_E_PRIME,
                float(e_over_e_prime),
                abs(e_over_e_prime) > E_OVER_E_PRIME_LIMIT,
                f"> {E_OVER_E_PRIME_LIMIT:g}",
            )
        )
    if e_prime_sept_cm_s is not None:
        rows.append(
            DiastolicCriterion(
                CRITERION_E_PRIME,
                float(e_prime_sept_cm_s),
                abs(e_prime_sept_cm_s) < E_PRIME_SEPT_MIN_CM_S,
                f"< {E_PRIME_SEPT_MIN_CM_S:g} cm/s",
            )
        )
    elif e_prime_lat_cm_s is not None:
        rows.append(
            DiastolicCriterion(
                CRITERION_E_PRIME,
                float(e_prime_lat_cm_s),
                abs(e_prime_lat_cm_s) < E_PRIME_LAT_MIN_CM_S,
                f"< {E_PRIME_LAT_MIN_CM_S:g} cm/s",
            )
        )
    if lav_index_ml_m2 is not None:
        rows.append(
            DiastolicCriterion(
                CRITERION_LAV_INDEX,
                float(lav_index_ml_m2),
                lav_index_ml_m2 > LAV_INDEX_LIMIT_ML_M2,
                f"> {LAV_INDEX_LIMIT_ML_M2:g} mL/m²",
            )
        )
    if tr_vmax_cm_s is not None:
        rows.append(
            DiastolicCriterion(
                CRITERION_TR_VMAX,
                float(tr_vmax_cm_s),
                abs(tr_vmax_cm_s) > TR_VMAX_LIMIT_CM_S,
                f"> {TR_VMAX_LIMIT_CM_S:g} cm/s",
            )
        )
    return tuple(rows)


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

    Simplified majority-rule assessment over the criteria of
    :func:`diastolic_criteria`:

    - E/e' > 14
    - septal e' < 7 cm/s (or lateral e' < 10 cm/s)
    - LAVi > 34 mL/m²
    - TR Vmax > 280 cm/s (2.8 m/s)

    Codes: 0 = Normal, 1 = Indeterminate, 2 = Abnormal, 3 = Insufficient data,
    None = no data at all. ``age_years`` is accepted for signature stability
    but the simplified algorithm does not use it.

    Velocity inputs are compared by magnitude: storage keeps the signed
    calibration truth (below-baseline jets read negative), so a TR jet of
    -312 cm/s still meets the > 280 cm/s criterion (Э2 sign normalization).
    """
    rows = diastolic_criteria(
        e_over_e_prime=e_over_e_prime,
        lav_index_ml_m2=lav_index_ml_m2,
        tr_vmax_cm_s=tr_vmax_cm_s,
        e_prime_sept_cm_s=e_prime_sept_cm_s,
        e_prime_lat_cm_s=e_prime_lat_cm_s,
    )
    if not rows:
        return None

    positive = sum(1 for row in rows if row.met)
    total = len(rows)

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
