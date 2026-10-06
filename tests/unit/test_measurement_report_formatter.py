"""Tests for study measurement report formatting."""

from __future__ import annotations

from echo_personal_tool.domain.models import LinearMeasurement, MeasurementSnapshot
from echo_personal_tool.domain.models.measurements import DopplerFlowResult, DopplerResults
from echo_personal_tool.domain.services.measurement_report_formatter import (
    dedupe_linear_measurements_latest,
    format_measurement_report,
)


def test_report_dedupes_linear_by_latest_label() -> None:
    measurements = (
        LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=48.0),
        LinearMeasurement(label="LVEDD", pixel_length=110.0, millimeter_length=52.0),
        LinearMeasurement(label="IVSd", pixel_length=50.0, millimeter_length=9.0),
    )
    deduped = dedupe_linear_measurements_latest(measurements)
    assert len(deduped) == 2
    lvedd = next(item for item in deduped if item.label == "LVEDD")
    assert lvedd.millimeter_length == 52.0


def test_report_includes_deduped_linear_once() -> None:
    snapshot = MeasurementSnapshot(
        linear_measurements=(
            LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=48.0),
            LinearMeasurement(label="LVEDD", pixel_length=110.0, millimeter_length=52.0),
        ),
    )
    text = format_measurement_report(snapshot)
    assert text.count("КДР ЛЖ") == 1
    assert "52.0 mm" in text


def test_report_empty_snapshot() -> None:
    assert format_measurement_report(None) == "Нет измерений."


def test_report_marks_repeated_measurements() -> None:
    """D-23: the report shows the averaged value and how many measurements fed it."""
    snapshot = MeasurementSnapshot(
        doppler=DopplerResults(
            flow_results=(
                DopplerFlowResult(site="TR", vmax_cm_s=313.3, pgmax_mmhg=39.3, vmax_repeats=4),
                DopplerFlowResult(site="AV", vmax_cm_s=100.0, pgmax_mmhg=4.0, vmax_repeats=1),
            ),
        ),
    )

    text = format_measurement_report(snapshot)

    # Unknown mode reads fast jets in m/s (magnitude fallback, Э2).
    assert "TR Vmax: 3.13 m/s (n=4)" in text
    assert "TR PGmax: 39.3 mmHg" in text
    # A single measurement is not annotated.
    assert "AV Vmax: 1.00 m/s\n" in text


def test_report_marks_repeated_vti_traces() -> None:
    snapshot = MeasurementSnapshot(
        doppler=DopplerResults(flow_results=(DopplerFlowResult(site="AV", vti_cm=21.5, vti_repeats=3),)),
    )

    text = format_measurement_report(snapshot)

    assert "AV VTI: 21.5 cm (n=3)" in text
