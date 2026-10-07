"""Localized wording for calculator provenance and warnings (Э11).

Shared by the calculator panel and the study report, so the protocol footnote
and the panel say exactly the same thing about where a number came from.
"""

from __future__ import annotations

from echo_personal_tool.domain.calculators.models import (
    SOURCE_DERIVED,
    SOURCE_DICOM,
    SOURCE_ESTIMATE,
    SOURCE_MANUAL,
    SOURCE_MEASURED,
    SOURCE_PATIENT,
    CalculationsSnapshot,
    CalcWarning,
    InputValue,
)
from echo_personal_tool.domain.calculators.registry import calculator_spec, input_spec
from echo_personal_tool.domain.services.doppler_repeats import REPORT_WINDOW
from echo_personal_tool.infrastructure.i18n import tr


def format_input_value(item: InputValue) -> str:
    """``2.00`` for LVOTd, ``70`` for HR — in the input's display unit."""
    spec = input_spec(item.id)
    if item.value is None:
        return ""
    decimals = spec.decimals if spec is not None else 2
    return f"{item.value:.{decimals}f}"


def input_label(input_id: str) -> str:
    spec = input_spec(input_id)
    if spec is None:
        return input_id
    if input_id in ("height", "weight"):
        return tr(spec.name_key)
    return spec.label


def source_text(item: InputValue) -> str:
    """Short provenance, e.g. ``measured, n=3`` / ``DICOM`` / ``manual``."""
    source = item.source
    if source == SOURCE_MEASURED:
        if item.detail == "trace":
            return tr("calc.source.measured_trace")
        if item.repeats > 1:
            # Repeated measurements enter as the mean of the newest ones (D-23).
            return tr("calc.source.measured_n", n=str(min(item.repeats, REPORT_WINDOW)))
        return tr("calc.source.measured")
    if source == SOURCE_DICOM:
        return tr("calc.source.dicom")
    if source == SOURCE_ESTIMATE:
        return tr("calc.source.estimate")
    if source == SOURCE_PATIENT:
        return tr("calc.source.patient_manual") if item.detail == "manual" else tr("calc.source.patient")
    if source == SOURCE_DERIVED:
        return tr("calc.source.derived_bsa")
    if source == SOURCE_MANUAL:
        return tr("calc.source.manual")
    return tr("calc.source.missing")


def warning_text(warning: CalcWarning) -> str:
    if warning.code == "out_of_range":
        spec = input_spec(warning.input_id)
        if spec is None:
            return ""
        low, high = spec.plausible
        return tr(
            "calc.warning.out_of_range",
            label=input_label(warning.input_id),
            low=f"{low:g}",
            high=f"{high:g}",
            unit=spec.unit,
        )
    if warning.code == "dvi_above_one":
        return tr("calc.warning.dvi_above_one")
    if warning.code == "ava_methods_diverge":
        percent = f"{(warning.value or 0.0) * 100:.0f}"
        return tr("calc.warning.ava_methods_diverge", percent=percent)
    return warning.code


def inputs_summary(calculations: CalculationsSnapshot) -> str:
    """One line listing the inputs behind the computed outputs with provenance."""
    parts: list[str] = []
    for item in calculations.used_inputs():
        spec = input_spec(item.id)
        unit = f" {spec.unit}" if spec is not None and spec.unit else ""
        parts.append(f"{input_label(item.id)} {format_input_value(item)}{unit} ({source_text(item)})")
    return "; ".join(parts)


def missing_text(missing: tuple[str, ...]) -> str:
    return tr("calc.missing", inputs=", ".join(input_label(item) for item in missing))


def report_notes(calculations: CalculationsSnapshot) -> tuple[str, ...]:
    """Footnotes of the report's calculations group: inputs, assumptions, warnings, RUO."""
    notes: list[str] = []
    summary = inputs_summary(calculations)
    if summary:
        notes.append(tr("calc.report.inputs", inputs=summary))
    for result in calculations.results:
        if not result.has_values:
            continue
        spec = calculator_spec(result.calculator_id)
        if spec is not None:
            notes.append(f"{tr(spec.title_key)}: {tr(spec.assumptions_key)}")
        for warning in result.warnings:
            text = warning_text(warning)
            line = tr("calc.report.warning", text=text)
            if text and line not in notes:
                notes.append(line)
    notes.append(tr("calc.ruo"))
    return tuple(notes)
