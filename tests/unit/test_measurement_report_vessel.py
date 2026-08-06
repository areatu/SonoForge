"""Tests for vessel section in measurement report."""

from __future__ import annotations

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.domain.services.measurement_report_formatter import (
    format_measurement_report,
)


def _m() -> VesselMeasurement:
    return VesselMeasurement(
        psv_cm_s=178.4,
        edv_cm_s=62.1,
        ri=0.65,
        sd=2.87,
        mv_approx=100.9,
        sop_instance_uid="A",
        frame_index=1,
    )


def test_report_contains_vessel_section():
    snapshot = MeasurementSnapshot(vessel_measurements=(_m(),))
    report = format_measurement_report(snapshot)
    assert "PSV" in report
    assert "EDV" in report
    assert "RI" in report
    assert "S/D" in report


def test_report_empty_without_vessel():
    report = format_measurement_report(MeasurementSnapshot())
    assert "PSV" not in report
