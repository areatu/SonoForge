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
#: Caliper labels of the PISA radius on a colour-flow frame (Э11б).
PISA_RADIUS_LABELS: dict[str, frozenset[str]] = {
    "pisa_r_mr": frozenset({"pisa mr", "pisa r mr", "pisa_mr"}),
    "pisa_r_ar": frozenset({"pisa ar", "pisa r ar", "pisa_ar"}),
}
#: Spectral inputs read from the study-wide Doppler results:
#: input id → (flow site, field, divisor to the input unit).
_DOPPLER_INPUTS: dict[str, tuple[str, str, float]] = {
    "lvot_vti": ("LVOT", "vti", 1.0),
    "av_vti": ("AV", "vti", 1.0),
    "lvot_vmax": ("LVOT", "vmax", 1.0),
    "av_vmax": ("AV", "vmax", 100.0),
    "mr_vti": ("MR", "vti", 1.0),
    "mr_vmax": ("MR", "vmax", 100.0),
    "ar_vti": ("AR", "vti", 1.0),
    "ar_vmax": ("AR", "vmax", 100.0),
}


@dataclass(frozen=True)
class HeartRateCandidate:
    bpm: float
    source: str  # SOURCE_DICOM | SOURCE_ESTIMATE
    detail: str = ""


def caliper_mean_cm(measurements: Iterable[LinearMeasurement], labels: frozenset[str]) -> tuple[float | None, int]:
    """Mean of the most recent calibrated calipers with one of *labels* (D-23 window), in cm, and their count."""
    values = [
        item.millimeter_length / 10.0
        for item in measurements
        if not item.doppler
        and item.millimeter_length is not None
        and item.millimeter_length > 0
        and item.label.casefold().strip() in labels
    ]
    return mean_of_last(values), len(values)


def lvot_diameter_cm(measurements: Iterable[LinearMeasurement]) -> tuple[float | None, int]:
    """Mean of the most recent LVOTd calipers (D-23 window), in cm, and their count."""
    return caliper_mean_cm(measurements, LVOT_DIAMETER_LABELS)


def _doppler_input(input_id: str, doppler: DopplerResults | None) -> InputValue:
    site, field_name, divisor = _DOPPLER_INPUTS[input_id]
    flow = doppler.flow(site) if doppler is not None else None
    if flow is None:
        return InputValue(input_id, None)
    if field_name == "vti":
        value = abs(flow.vti_cm) if flow.vti_cm is not None else None
        return _measured(input_id, value, source=SOURCE_MEASURED, repeats=flow.vti_repeats)
    value = abs(flow.vmax_cm_s) / divisor if flow.vmax_cm_s is not None else None
    return _measured(
        input_id,
        value,
        source=SOURCE_MEASURED,
        repeats=flow.vmax_repeats,
        detail="trace" if flow.vmax_repeats == 0 else "",
    )


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
    measurements = tuple(linear_measurements)
    diameter, diameter_n = lvot_diameter_cm(measurements)
    auto: dict[str, InputValue] = {
        "lvot_d": _measured("lvot_d", diameter, source=SOURCE_MEASURED, repeats=diameter_n),
    }
    for input_id in _DOPPLER_INPUTS:
        auto[input_id] = _doppler_input(input_id, doppler)
    for input_id, labels in PISA_RADIUS_LABELS.items():
        radius, radius_n = caliper_mean_cm(measurements, labels)
        auto[input_id] = _measured(input_id, radius, source=SOURCE_MEASURED, repeats=radius_n)
    for input_id in all_input_ids():
        spec = input_spec(input_id)
        if spec is not None and spec.manual_only:
            auto[input_id] = InputValue(input_id, None)
    auto.update(
        {
            "hr": (
                _measured("hr", heart_rate.bpm, source=heart_rate.source, detail=heart_rate.detail)
                if heart_rate is not None
                else InputValue("hr", None)
            ),
            "height": _measured("height", height_cm, source=SOURCE_PATIENT, detail=height_source),
            "weight": _measured("weight", weight_kg, source=SOURCE_PATIENT, detail=weight_source),
        }
    )
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
