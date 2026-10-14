"""Dependency map and invalidation rules for derived results (QH-1b.1).

Spec §5.2 matrix:

| Изменение | Обязательная реакция |
| Контур/ED/ES/ROI или исходное измерение | Инвалидировать зависящие Simpson/strain/vessel/calculator results, не весь study без необходимости |
| Pixel/velocity/time calibration своего source | Инвалидировать только зависимые физические величины; не трогать независимый source |
| Рост/вес/BSA | Обновить BSA-зависимые индексы; не инвалидировать независимые raw volumes |
| Manual input/override/выбранный набор повторов | Пересчитать соответствующие калькуляторы/агрегаты с сохранением источника ввода |
| Algorithm/model/значимый config | Старый result остаётся историческим либо требует явного пересчёта; автоматический expensive reanalysis не обязателен |
| Неполный/несовместимый restore | Не активировать производное число, требующее отсутствующего входа |
| Late worker callback | Принять только при совпадении captured context/generation/input revisions; иначе discard без dirty/write |

This module is pure — no Qt, no I/O — and defines the contract for QH-1b.2
invalidation. QH-1b.1 only introduces DTO + map + tests; actual invalidation
wiring lives in application layer later.

Design:
- Input kinds are stable strings (allowlisted).
- Result families are stable strings (allowlisted).
- DEPENDENCY_MAP: input_kind -> set[result_family] that must be invalidated.
- CALIBRATION_KINDS: which calibration changes affect which families per-source.
- For per-source isolation, callers must pass source_instance_uid.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Input kinds (allowlisted) ────────────────────────────────────────────

INPUT_CONTOUR = "contour"
INPUT_ED_ES = "ed_es"
INPUT_ROI = "roi"
INPUT_LINEAR = "linear"
INPUT_DOPPLER = "doppler"
INPUT_VESSEL = "vessel"
INPUT_STRAIN_RAW = "strain_raw"

CALIB_PIXEL = "pixel_spacing"
CALIB_TIME = "time_spacing"
CALIB_VELOCITY = "velocity"
CALIB_DOPPLER_ROI = "doppler_roi"
CALIB_MMODE = "mmode"

INPUT_HEIGHT = "height"
INPUT_WEIGHT = "weight"
INPUT_BSA = "bsa"

INPUT_MANUAL_OVERRIDE = "manual_override"
INPUT_REPEAT_SELECTION = "repeat_selection"

INPUT_ALGORITHM = "algorithm"
INPUT_MODEL = "model"
INPUT_CONFIG = "config"

INPUT_SOURCE_MISSING = "source_missing"
INPUT_LATE_CALLBACK = "late_callback"

ALL_INPUT_KINDS = frozenset(
    {
        INPUT_CONTOUR,
        INPUT_ED_ES,
        INPUT_ROI,
        INPUT_LINEAR,
        INPUT_DOPPLER,
        INPUT_VESSEL,
        INPUT_STRAIN_RAW,
        CALIB_PIXEL,
        CALIB_TIME,
        CALIB_VELOCITY,
        CALIB_DOPPLER_ROI,
        CALIB_MMODE,
        INPUT_HEIGHT,
        INPUT_WEIGHT,
        INPUT_BSA,
        INPUT_MANUAL_OVERRIDE,
        INPUT_REPEAT_SELECTION,
        INPUT_ALGORITHM,
        INPUT_MODEL,
        INPUT_CONFIG,
        INPUT_SOURCE_MISSING,
        INPUT_LATE_CALLBACK,
    }
)


# ── Result families (allowlisted) ────────────────────────────────────────

RESULT_SIMPSON = "simpson"
RESULT_TEICHHOLZ = "teichholz"
RESULT_LVEF = "lvef"
RESULT_LA_VOLUME = "la_volume"
RESULT_CHAMBER_SIMPSON = "chamber_simpson"
RESULT_STRAIN = "strain"
RESULT_STRAIN_REPORT = "strain_report"
RESULT_DOPPLER = "doppler"
RESULT_VESSEL = "vessel_calc"
RESULT_CALCULATIONS = "calculations"
RESULT_PLANIMETER = "planimeter"
RESULT_INDEXED = "indexed"
RESULT_RV_FAC = "rv_fac"
RESULT_RWT = "rwt"
RESULT_LVM = "lvm"

ALL_RESULT_FAMILIES = frozenset(
    {
        RESULT_SIMPSON,
        RESULT_TEICHHOLZ,
        RESULT_LVEF,
        RESULT_LA_VOLUME,
        RESULT_CHAMBER_SIMPSON,
        RESULT_STRAIN,
        RESULT_STRAIN_REPORT,
        RESULT_DOPPLER,
        RESULT_VESSEL,
        RESULT_CALCULATIONS,
        RESULT_PLANIMETER,
        RESULT_INDEXED,
        RESULT_RV_FAC,
        RESULT_RWT,
        RESULT_LVM,
    }
)


# ── Dependency map ───────────────────────────────────────────────────────
# Which result families must become STALE when a given input kind changes.
# This is the contract for QH-1b.2 invalidation; QH-1b.1 only defines and tests it.

DEPENDENCY_MAP: dict[str, set[str]] = {
    # Contour/ED/ES/ROI or source measurement -> dependent Simpson/strain/vessel/calculator
    INPUT_CONTOUR: {
        RESULT_SIMPSON,
        RESULT_LVEF,
        RESULT_LA_VOLUME,
        RESULT_CHAMBER_SIMPSON,
        RESULT_STRAIN,
        RESULT_STRAIN_REPORT,
        RESULT_PLANIMETER,
        RESULT_RV_FAC,
        RESULT_CALCULATIONS,
    },
    INPUT_ED_ES: {
        RESULT_SIMPSON,
        RESULT_LVEF,
        RESULT_LA_VOLUME,
        RESULT_CHAMBER_SIMPSON,
        RESULT_STRAIN,
        RESULT_STRAIN_REPORT,
        RESULT_CALCULATIONS,
    },
    INPUT_ROI: {
        RESULT_STRAIN,
        RESULT_STRAIN_REPORT,
        RESULT_CALCULATIONS,
    },
    INPUT_LINEAR: {
        RESULT_TEICHHOLZ,
        RESULT_LVEF,
        RESULT_LA_VOLUME,
        RESULT_RWT,
        RESULT_LVM,
        RESULT_INDEXED,
        RESULT_CALCULATIONS,
    },
    INPUT_DOPPLER: {
        RESULT_DOPPLER,
        RESULT_CALCULATIONS,
    },
    INPUT_VESSEL: {
        RESULT_VESSEL,
        RESULT_CALCULATIONS,
    },
    INPUT_STRAIN_RAW: {
        RESULT_STRAIN,
        RESULT_STRAIN_REPORT,
        RESULT_CALCULATIONS,
    },
    # Calibration of own source -> only dependent physical quantities of that source
    CALIB_PIXEL: {
        RESULT_SIMPSON,
        RESULT_TEICHHOLZ,
        RESULT_LVEF,
        RESULT_LA_VOLUME,
        RESULT_CHAMBER_SIMPSON,
        RESULT_PLANIMETER,
        RESULT_RV_FAC,
        RESULT_RWT,
        RESULT_LVM,
        RESULT_INDEXED,
        RESULT_CALCULATIONS,
    },
    CALIB_TIME: {
        RESULT_DOPPLER,
        RESULT_CALCULATIONS,
    },
    CALIB_VELOCITY: {
        RESULT_DOPPLER,
        RESULT_VESSEL,
        RESULT_CALCULATIONS,
    },
    CALIB_DOPPLER_ROI: {
        RESULT_DOPPLER,
        RESULT_CALCULATIONS,
    },
    CALIB_MMODE: {
        RESULT_TEICHHOLZ,
        RESULT_CALCULATIONS,
    },
    # Height/weight/BSA -> BSA-dependent indexes only
    INPUT_HEIGHT: {RESULT_INDEXED, RESULT_CALCULATIONS},
    INPUT_WEIGHT: {RESULT_INDEXED, RESULT_CALCULATIONS},
    INPUT_BSA: {RESULT_INDEXED, RESULT_CALCULATIONS},
    # Manual input/override/selected repeats -> calculators/aggregates
    INPUT_MANUAL_OVERRIDE: {RESULT_CALCULATIONS, RESULT_INDEXED},
    INPUT_REPEAT_SELECTION: {RESULT_DOPPLER, RESULT_CALCULATIONS},
    # Algorithm/model/config -> old result historical, requires explicit recalc
    INPUT_ALGORITHM: {
        RESULT_SIMPSON,
        RESULT_LVEF,
        RESULT_STRAIN,
        RESULT_STRAIN_REPORT,
        RESULT_DOPPLER,
        RESULT_CALCULATIONS,
    },
    INPUT_MODEL: {RESULT_STRAIN, RESULT_STRAIN_REPORT},
    INPUT_CONFIG: {
        RESULT_SIMPSON,
        RESULT_LVEF,
        RESULT_STRAIN,
        RESULT_STRAIN_REPORT,
        RESULT_DOPPLER,
        RESULT_CALCULATIONS,
    },
    # Incomplete/incompatible restore -> do not activate derived requiring missing input
    INPUT_SOURCE_MISSING: {
        RESULT_SIMPSON,
        RESULT_LVEF,
        RESULT_STRAIN,
        RESULT_STRAIN_REPORT,
        RESULT_DOPPLER,
        RESULT_CALCULATIONS,
        RESULT_INDEXED,
    },
    # Late worker callback -> discard if context/generation/revision mismatch
    INPUT_LATE_CALLBACK: set(),  # special handling, not via map
}


@dataclass(frozen=True)
class DependencyChange:
    """One significant change that may invalidate derived results."""

    kind: str
    measurement_id: str = ""
    source_instance_uid: str = ""
    revision: int = 0
    # For calibration changes, the calibration kind is in `kind`
    # For algorithm/model/config, method_id is in `measurement_id`


def affected_families(change: DependencyChange) -> set[str]:
    """Return result families that must become STALE for this change.

    Per-source isolation: if change has source_instance_uid, caller must filter
    results by that source; this function returns families regardless, but the
    invalidation in QH-1b.2 will check source matching.
    """
    if change.kind not in ALL_INPUT_KINDS:
        raise ValueError(f"Unknown input kind: {change.kind}")
    return set(DEPENDENCY_MAP.get(change.kind, set()))


def is_calibration_kind(kind: str) -> bool:
    return kind in {CALIB_PIXEL, CALIB_TIME, CALIB_VELOCITY, CALIB_DOPPLER_ROI, CALIB_MMODE}


def requires_per_source_isolation(kind: str) -> bool:
    """True when invalidation must be per-source, not whole study."""
    return is_calibration_kind(kind) or kind in {
        INPUT_CONTOUR,
        INPUT_ED_ES,
        INPUT_ROI,
        INPUT_LINEAR,
        INPUT_DOPPLER,
        INPUT_VESSEL,
    }


def should_discard_late_callback(
    *, captured_generation: int, current_generation: int, captured_revision: int, current_revision: int
) -> bool:
    """Late worker callback rule (spec §5.2 matrix, last row).

    Accept only when captured context/generation/input revisions match;
    otherwise discard without dirty/write.
    """
    return captured_generation != current_generation or captured_revision != current_revision
