"""Integrated, transparent MR/AR severity grading from available parameters.

The per-parameter thresholds follow the ASE/SCMR native regurgitation
reference set shipped with SonoForge (``resources/references``), and
:data:`PARAMETER_GRADERS` is the single copy the UI colours the parameter rows
with, so a row's colour and its contribution to the grade never disagree.

The integrated grade is the lower median of the available ordinal grades: this
avoids escalating a discordant case from a single severe criterion. It is
decision support, not a substitute for clinical adjudication; every individual
parameter stays visible next to it, and a missing parameter simply does not
vote (``None`` is not «mild»).

AR is graded by vena contracta, EROA, RVol *and* the two jet-to-LVOT ratios the
comparison tools measure (jet area / LVOT area and jet width / LVOT width), so
a study without PISA data can still be graded.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from math import floor
from statistics import median

# Ordinal: 1 mild, 2 moderate, 3 severe. Boundaries follow the reference data
# (``resources/references/references_structured.yaml``).


def mr_grade_from_vc_mm(value: float | None) -> int | None:
    if value is None or value < 0:
        return None
    return 1 if value < 3.0 else 2 if value < 7.0 else 3


def ar_grade_from_vc_mm(value: float | None) -> int | None:
    if value is None or value < 0:
        return None
    return 1 if value < 3.0 else 2 if value < 6.0 else 3


def mr_grade_from_eroa_cm2(value: float | None) -> int | None:
    if value is None or value < 0:
        return None
    return 1 if value < 0.20 else 2 if value < 0.40 else 3


def ar_grade_from_eroa_cm2(value: float | None) -> int | None:
    if value is None or value < 0:
        return None
    return 1 if value < 0.10 else 2 if value < 0.30 else 3


def grade_from_rvol_ml(value: float | None) -> int | None:
    if value is None or value < 0:
        return None
    return 1 if value < 30.0 else 2 if value < 60.0 else 3


def grade_from_rf_percent(value: float | None) -> int | None:
    if value is None or value < 0:
        return None
    return 1 if value < 30.0 else 2 if value < 50.0 else 3


def ar_grade_from_jet_area_ratio_percent(value: float | None) -> int | None:
    """Grade the measured regurgitant jet area / LVOT area percentage."""
    if value is None or value < 0:
        return None
    return 1 if value < 5.0 else 2 if value < 60.0 else 3


def ar_grade_from_jet_width_ratio_percent(value: float | None) -> int | None:
    """Grade the measured jet width / LVOT width percentage."""
    if value is None or value < 0:
        return None
    return 1 if value < 25.0 else 2 if value < 65.0 else 3


#: Calculator output id → grader of that parameter.  The presentation colours
#: the parameter rows with the same boundaries the integrated grade uses, so the
#: user reads one consistent set of thresholds instead of two drifting copies.
PARAMETER_GRADERS: dict[str, Callable[[float | None], int | None]] = {
    "eroa_mr": mr_grade_from_eroa_cm2,
    "rvol_mr": grade_from_rvol_ml,
    "vc_mr": mr_grade_from_vc_mm,
    "rf_mr": grade_from_rf_percent,
    "eroa_ar": ar_grade_from_eroa_cm2,
    "rvol_ar": grade_from_rvol_ml,
    "vc_ar": ar_grade_from_vc_mm,
    "rf_ar": grade_from_rf_percent,
    "jet_area_ratio_ar": ar_grade_from_jet_area_ratio_percent,
    "jet_diameter_ratio_ar": ar_grade_from_jet_width_ratio_percent,
    "grade_mr": lambda value: int(value) if value is not None and int(value) in (1, 2, 3) else None,
    "grade_ar": lambda value: int(value) if value is not None and int(value) in (1, 2, 3) else None,
}


def parameter_grade(output_id: str, value: float | None) -> int | None:
    """Ordinal severity of one parameter, or ``None`` when it has no band."""
    grader = PARAMETER_GRADERS.get(output_id)
    if grader is None or value is None:
        return None
    return grader(float(value))


def integrated_grade(grades: Iterable[int | None]) -> float | None:
    """Lower median of available criteria; None when no parameter is available."""
    available = sorted(int(value) for value in grades if value in (1, 2, 3))
    if not available:
        return None
    return float(floor(median(available)))


def mr_integrated_grade(eroa_cm2: float | None, rvol_ml: float | None, vc_mm: float | None) -> float | None:
    return integrated_grade(
        (
            mr_grade_from_eroa_cm2(eroa_cm2),
            grade_from_rvol_ml(rvol_ml),
            mr_grade_from_vc_mm(vc_mm),
        )
    )


def ar_integrated_grade(
    eroa_cm2: float | None,
    rvol_ml: float | None,
    vc_mm: float | None,
    jet_area_ratio_percent: float | None,
    jet_width_ratio_percent: float | None = None,
) -> float | None:
    return integrated_grade(
        (
            ar_grade_from_eroa_cm2(eroa_cm2),
            grade_from_rvol_ml(rvol_ml),
            ar_grade_from_vc_mm(vc_mm),
            ar_grade_from_jet_area_ratio_percent(jet_area_ratio_percent),
            ar_grade_from_jet_width_ratio_percent(jet_width_ratio_percent),
        )
    )
