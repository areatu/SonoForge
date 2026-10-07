"""Resolve calculator inputs from a study, with provenance (Э11).

Precedence for every input: a value typed by the user wins, then the study
(measurements, DICOM header, automatic estimate).  An input nothing provides
stays *missing* — no typical values are ever substituted.

The resolver is a pure function over plain values, so it is tested without
Qt or a running controller; :class:`CalculatorInputStore` keeps the manual
values per study (in memory: like the Э11 standalone values they are not part
of the measurement-storage schema yet).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from echo_personal_tool.domain.calculations.body_surface import bsa_du_bois_m2
from echo_personal_tool.domain.calculators.engine import evaluate
from echo_personal_tool.domain.calculators.models import (
    SOURCE_DERIVED,
    SOURCE_ESTIMATE,
    SOURCE_MANUAL,
    SOURCE_MEASURED,
    SOURCE_MISSING,
    SOURCE_PATIENT,
    CalculationsSnapshot,
    InputValue,
)
from echo_personal_tool.domain.calculators.registry import all_input_ids, input_spec
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import DopplerResults
from echo_personal_tool.domain.services.doppler_repeats import mean_of_last

#: Caliper labels that measure the LVOT diameter (menu: ``LVOTd``).
LVOT_DIAMETER_LABELS = frozenset({"lvotd", "lvot d", "lvot"})


@dataclass(frozen=True)
class HeartRateCandidate:
    bpm: float
    source: str  # SOURCE_DICOM | SOURCE_ESTIMATE
    detail: str = ""


def lvot_diameter_cm(measurements: Iterable[LinearMeasurement]) -> tuple[float | None, int]:
    """Mean of the most recent LVOTd calipers (D-23 window), in cm, and their count."""
    values = [
        item.millimeter_length / 10.0
        for item in measurements
        if not item.doppler
        and item.millimeter_length is not None
        and item.millimeter_length > 0
        and item.label.casefold().strip() in LVOT_DIAMETER_LABELS
    ]
    return mean_of_last(values), len(values)


def _measured(input_id: str, value: float | None, *, source: str, repeats: int = 0, detail: str = "") -> InputValue:
    if value is None or value <= 0:
        return InputValue(input_id, None)
    return InputValue(input_id, float(value), source=source, repeats=repeats, detail=detail)


def _apply_manual(auto: InputValue, manual: Mapping[str, float]) -> InputValue:
    value = manual.get(auto.id)
    if value is None:
        return auto
    return InputValue(
        auto.id,
        float(value),
        source=SOURCE_MANUAL,
        auto_value=auto.value,
        auto_source=auto.source if auto.value is not None else SOURCE_MISSING,
    )


def _bsa(height: InputValue, weight: InputValue) -> InputValue:
    if height.value is None or weight.value is None:
        return InputValue("bsa", None)
    bsa = bsa_du_bois_m2(height.value, weight.value)
    if bsa is None:
        return InputValue("bsa", None)
    return InputValue("bsa", bsa, source=SOURCE_DERIVED, detail="Du Bois")


def resolve_study_inputs(
    *,
    doppler: DopplerResults | None,
    linear_measurements: Iterable[LinearMeasurement] = (),
    height_cm: float | None = None,
    weight_kg: float | None = None,
    height_source: str = "",
    weight_source: str = "",
    heart_rate: HeartRateCandidate | None = None,
    manual: Mapping[str, float] | None = None,
) -> dict[str, InputValue]:
    """Inputs for every calculator from study-wide measurements."""
    manual = manual or {}
    lvot = doppler.flow("LVOT") if doppler is not None else None
    av = doppler.flow("AV") if doppler is not None else None

    diameter, diameter_n = lvot_diameter_cm(linear_measurements)
    auto: dict[str, InputValue] = {
        "lvot_d": _measured("lvot_d", diameter, source=SOURCE_MEASURED, repeats=diameter_n),
        "lvot_vti": _measured(
            "lvot_vti",
            abs(lvot.vti_cm) if lvot and lvot.vti_cm is not None else None,
            source=SOURCE_MEASURED,
            repeats=lvot.vti_repeats if lvot else 0,
        ),
        "av_vti": _measured(
            "av_vti",
            abs(av.vti_cm) if av and av.vti_cm is not None else None,
            source=SOURCE_MEASURED,
            repeats=av.vti_repeats if av else 0,
        ),
        "lvot_vmax": _measured(
            "lvot_vmax",
            abs(lvot.vmax_cm_s) if lvot and lvot.vmax_cm_s is not None else None,
            source=SOURCE_MEASURED,
            repeats=lvot.vmax_repeats if lvot else 0,
            detail="trace" if lvot and lvot.vmax_repeats == 0 else "",
        ),
        "av_vmax": _measured(
            "av_vmax",
            abs(av.vmax_cm_s) / 100.0 if av and av.vmax_cm_s is not None else None,
            source=SOURCE_MEASURED,
            repeats=av.vmax_repeats if av else 0,
            detail="trace" if av and av.vmax_repeats == 0 else "",
        ),
        "hr": (
            _measured("hr", heart_rate.bpm, source=heart_rate.source, detail=heart_rate.detail)
            if heart_rate is not None
            else InputValue("hr", None)
        ),
        "height": _measured("height", height_cm, source=SOURCE_PATIENT, detail=height_source),
        "weight": _measured("weight", weight_kg, source=SOURCE_PATIENT, detail=weight_source),
    }
    resolved = {input_id: _apply_manual(value, manual) for input_id, value in auto.items()}
    resolved["bsa"] = _apply_manual(_bsa(resolved["height"], resolved["weight"]), manual)
    return resolved


def resolve_standalone_inputs(manual: Mapping[str, float]) -> dict[str, InputValue]:
    """Standalone mode: numbers typed from the scanner screen, nothing else."""
    resolved: dict[str, InputValue] = {}
    for input_id in all_input_ids():
        if input_id == "bsa":
            continue
        value = manual.get(input_id)
        resolved[input_id] = (
            InputValue(input_id, float(value), source=SOURCE_MANUAL)
            if value is not None
            else InputValue(input_id, None)
        )
    resolved["bsa"] = _apply_manual(_bsa(resolved["height"], resolved["weight"]), manual)
    return resolved


def evaluate_standalone(manual: Mapping[str, float]) -> CalculationsSnapshot:
    return evaluate(resolve_standalone_inputs(manual), standalone=True)


def sanitize_manual_value(input_id: str, value: float | None) -> float | None:
    """Validate a typed value against the editor bounds; ``None`` clears it."""
    if value is None:
        return None
    spec = input_spec(input_id)
    if spec is None:
        raise KeyError(input_id)
    low, high = spec.editor_range
    if not (low <= value <= high):
        raise ValueError(f"{input_id}={value} outside {low}..{high}")
    return float(value)


@dataclass
class CalculatorInputStore:
    """Manual calculator values per study, plus the latest cine HR estimate."""

    _manual: dict[str, dict[str, float]] = field(default_factory=dict)
    _hr_estimate: dict[str, HeartRateCandidate] = field(default_factory=dict)

    def manual(self, study_uid: str | None) -> dict[str, float]:
        return dict(self._manual.get(study_uid or "", {}))

    def set_manual(self, study_uid: str | None, input_id: str, value: float | None) -> bool:
        """Set or clear one value; returns whether anything changed."""
        key = study_uid or ""
        value = sanitize_manual_value(input_id, value)
        current = self._manual.get(key, {})
        if value is None:
            if input_id not in current:
                return False
            updated = {k: v for k, v in current.items() if k != input_id}
        else:
            if current.get(input_id) == value:
                return False
            updated = {**current, input_id: value}
        if updated:
            self._manual[key] = updated
        else:
            self._manual.pop(key, None)
        return True

    def hr_estimate(self, study_uid: str | None) -> HeartRateCandidate | None:
        return self._hr_estimate.get(study_uid or "")

    def set_hr_estimate(self, study_uid: str | None, bpm: float, method: str) -> None:
        if bpm > 0:
            self._hr_estimate[study_uid or ""] = HeartRateCandidate(float(bpm), SOURCE_ESTIMATE, method)

    def clear_study(self, study_uid: str | None) -> None:
        self._manual.pop(study_uid or "", None)
        self._hr_estimate.pop(study_uid or "", None)
