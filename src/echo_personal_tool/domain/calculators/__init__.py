"""Clinical calculators (Э11): declarative registry + pure evaluation engine."""

from echo_personal_tool.domain.calculators.engine import evaluate, is_out_of_range
from echo_personal_tool.domain.calculators.models import (
    CalculationsSnapshot,
    CalculatorResult,
    CalcWarning,
    InputValue,
    OutputValue,
)
from echo_personal_tool.domain.calculators.registry import (
    CALCULATORS,
    INPUTS,
    CalculatorSpec,
    InputSpec,
    OutputSpec,
    all_input_ids,
    calculator_spec,
    input_owners,
    input_spec,
    output_owners,
    primary_input_ids,
    primary_output_ids,
)

__all__ = [
    "CALCULATORS",
    "INPUTS",
    "CalcWarning",
    "CalculationsSnapshot",
    "CalculatorResult",
    "CalculatorSpec",
    "InputSpec",
    "InputValue",
    "OutputSpec",
    "OutputValue",
    "all_input_ids",
    "calculator_spec",
    "evaluate",
    "input_owners",
    "input_spec",
    "output_owners",
    "primary_input_ids",
    "primary_output_ids",
    "is_out_of_range",
]
