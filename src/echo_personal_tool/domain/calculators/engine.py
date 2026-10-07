"""Evaluate the calculator registry over a set of resolved inputs (Э11)."""

from __future__ import annotations

from collections.abc import Mapping

from echo_personal_tool.domain.calculators.models import (
    CalculationsSnapshot,
    CalculatorResult,
    CalcWarning,
    InputValue,
    OutputValue,
)
from echo_personal_tool.domain.calculators.registry import (
    CALCULATORS,
    CalculatorSpec,
    all_input_ids,
    input_spec,
)

#: Relative disagreement between AVA (VTI) and AVA (Vmax) that is worth a
#: warning: the Vmax form ignores the flow-profile shape, a large gap usually
#: means LVOT and AV signals come from different beats or rhythms.
AVA_DIVERGENCE_THRESHOLD = 0.25


def is_out_of_range(input_id: str, value: float | None) -> bool:
    spec = input_spec(input_id)
    if spec is None or value is None:
        return False
    low, high = spec.plausible
    return value < low or value > high


def _evaluate_calculator(spec: CalculatorSpec, inputs: Mapping[str, InputValue]) -> CalculatorResult:
    values: dict[str, float] = {
        input_id: float(item.value) for input_id, item in inputs.items() if item.available and item.value is not None
    }
    outputs: list[OutputValue] = []
    for output in spec.outputs:
        value: float | None = None
        if all(dependency in values for dependency in output.requires):
            value = output.compute(values)
        if value is not None:
            values[output.id] = value
            missing: tuple[str, ...] = ()
        else:
            missing = tuple(item for item in spec.input_closure(output.id) if item not in values)
        outputs.append(
            OutputValue(
                id=output.id,
                label=output.label,
                value=value,
                unit=output.unit,
                decimals=output.decimals,
                formula=output.formula,
                missing=missing,
            )
        )

    warnings: list[CalcWarning] = []
    for input_id in spec.input_ids:
        item = inputs.get(input_id)
        if item is not None and item.available and is_out_of_range(input_id, item.value):
            warnings.append(CalcWarning("out_of_range", input_id=input_id, value=item.value))
    for dvi_id in ("dvi_vti", "dvi_vmax"):
        dvi = values.get(dvi_id)
        if dvi is not None and dvi > 1.0:
            warnings.append(CalcWarning("dvi_above_one", input_id=dvi_id, value=dvi))
            break
    ava_vti = values.get("ava_vti")
    ava_vmax = values.get("ava_vmax")
    if ava_vti is not None and ava_vmax is not None:
        gap = abs(ava_vti - ava_vmax) / max(ava_vti, ava_vmax)
        if gap > AVA_DIVERGENCE_THRESHOLD:
            warnings.append(CalcWarning("ava_methods_diverge", value=gap))
    return CalculatorResult(calculator_id=spec.id, outputs=tuple(outputs), warnings=tuple(warnings))


def evaluate(inputs: Mapping[str, InputValue], *, standalone: bool = False) -> CalculationsSnapshot:
    """Run every registered calculator; missing inputs leave outputs empty."""
    ordered = tuple(
        inputs[input_id] if input_id in inputs else InputValue(input_id, None) for input_id in all_input_ids()
    )
    results = tuple(_evaluate_calculator(spec, inputs) for spec in CALCULATORS)
    return CalculationsSnapshot(inputs=ordered, results=results, standalone=standalone)
