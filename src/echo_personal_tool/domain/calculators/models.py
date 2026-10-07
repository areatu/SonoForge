"""Value objects of the calculator engine (Э11).

Everything here is a frozen dataclass of plain tuples/scalars so a
:class:`CalculationsSnapshot` compares with ``==`` — the viewer only refreshes
when the measurement snapshot actually changes.

Localized text is never stored here: warnings and provenance are *codes*
rendered by the presentation/report layer, so switching the interface
language re-translates the panel and the protocol without a recompute.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Where an input value came from.  ``missing`` means "no value": calculators
#: never substitute a typical value for an absent input.
SOURCE_MEASURED = "measured"  # study measurement (caliper / Doppler marker / trace)
SOURCE_DICOM = "dicom"  # DICOM header tag of a contributing clip
SOURCE_ESTIMATE = "estimate"  # automatic estimate (cine heart-rate tool)
SOURCE_PATIENT = "patient"  # patient height/weight of the study session
SOURCE_DERIVED = "derived"  # computed from other inputs (BSA from height/weight)
SOURCE_MANUAL = "manual"  # typed by the user
SOURCE_MISSING = "missing"

INPUT_SOURCES: tuple[str, ...] = (
    SOURCE_MEASURED,
    SOURCE_DICOM,
    SOURCE_ESTIMATE,
    SOURCE_PATIENT,
    SOURCE_DERIVED,
    SOURCE_MANUAL,
    SOURCE_MISSING,
)


@dataclass(frozen=True)
class InputValue:
    """One resolved calculator input with its provenance.

    ``value`` is in the display unit of the input spec (cm, cm/s, m/s, bpm…).
    ``auto_value``/``auto_source`` keep what the study would provide when the
    user overrides it manually, so the panel can offer "back to measured".
    ``repeats`` is the number of stored measurements behind a measured value
    (the value itself is the mean of the most recent ones, D-23).
    ``detail`` is a short non-localized qualifier (e.g. ``"trace"`` when a
    Vmax came from the VTI envelope, ``"Du Bois"`` for BSA).
    """

    id: str
    value: float | None
    source: str = SOURCE_MISSING
    repeats: int = 0
    detail: str = ""
    auto_value: float | None = None
    auto_source: str = SOURCE_MISSING

    @property
    def available(self) -> bool:
        return self.value is not None and self.source != SOURCE_MISSING

    @property
    def overridden(self) -> bool:
        """Manual value typed over something the study already provides."""
        return self.source == SOURCE_MANUAL and self.auto_value is not None


@dataclass(frozen=True)
class CalcWarning:
    """A plausibility/consistency warning, rendered by code.

    ``code`` values: ``out_of_range`` (input outside its plausible range;
    ``input_id`` set), ``dvi_above_one`` (LVOT flow above AV flow — labels or
    modes are probably swapped), ``ava_methods_diverge`` (VTI and Vmax AVA
    differ by more than 25 %).
    """

    code: str
    input_id: str = ""
    value: float | None = None


@dataclass(frozen=True)
class OutputValue:
    id: str
    label: str
    value: float | None
    unit: str
    decimals: int
    formula: str
    #: Inputs this output still needs (empty when computed).
    missing: tuple[str, ...] = ()

    @property
    def computed(self) -> bool:
        return self.value is not None

    def formatted(self) -> str:
        return "—" if self.value is None else f"{self.value:.{self.decimals}f}"


@dataclass(frozen=True)
class CalculatorResult:
    calculator_id: str
    outputs: tuple[OutputValue, ...] = ()
    warnings: tuple[CalcWarning, ...] = ()

    @property
    def has_values(self) -> bool:
        return any(output.computed for output in self.outputs)

    def output(self, output_id: str) -> OutputValue | None:
        return next((item for item in self.outputs if item.id == output_id), None)


@dataclass(frozen=True)
class CalculationsSnapshot:
    """All calculators evaluated over one set of inputs."""

    inputs: tuple[InputValue, ...] = ()
    results: tuple[CalculatorResult, ...] = ()
    #: ``True`` for the standalone (manual numbers, no study) mode; such a
    #: snapshot never enters a study report.
    standalone: bool = False

    @property
    def has_values(self) -> bool:
        return any(result.has_values for result in self.results)

    def input(self, input_id: str) -> InputValue | None:
        return next((item for item in self.inputs if item.id == input_id), None)

    def result(self, calculator_id: str) -> CalculatorResult | None:
        return next((item for item in self.results if item.calculator_id == calculator_id), None)

    def used_inputs(self) -> tuple[InputValue, ...]:
        """Inputs that contributed to at least one computed output."""
        used: set[str] = set()
        from echo_personal_tool.domain.calculators.registry import calculator_spec

        for result in self.results:
            spec = calculator_spec(result.calculator_id)
            if spec is None:
                continue
            for output in result.outputs:
                if not output.computed:
                    continue
                output_spec = spec.output(output.id)
                if output_spec is not None:
                    used.update(spec.input_closure(output_spec.id))
        return tuple(item for item in self.inputs if item.id in used and item.available)
