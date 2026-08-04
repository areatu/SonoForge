"""Tests for VesselMeasurement model and snapshot field."""

from __future__ import annotations

from dataclasses import fields

from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement


def test_vessel_measurement_fields() -> None:
    m = VesselMeasurement(
        psv_cm_s=178.4,
        edv_cm_s=62.1,
        ri=0.65,
        sd=2.87,
        mv_approx=100.9,
        sop_instance_uid="1.2.3",
        frame_index=5,
    )
    assert m.psv_cm_s == 178.4
    assert m.calibration_id is None


def test_vessel_measurement_cycle_source_default_manual() -> None:
    m = VesselMeasurement(
        psv_cm_s=1.0,
        edv_cm_s=1.0,
        ri=None,
        sd=None,
        mv_approx=0.0,
        sop_instance_uid="1",
        frame_index=0,
    )
    assert m.cycle_source == "manual"


def test_vessel_measurement_cycle_source_custom() -> None:
    m = VesselMeasurement(
        psv_cm_s=1.0,
        edv_cm_s=1.0,
        ri=None,
        sd=None,
        mv_approx=0.0,
        sop_instance_uid="1",
        frame_index=0,
        cycle_source="ecg",
    )
    assert m.cycle_source == "ecg"


def test_vessel_measurement_averaged_cycles_default() -> None:
    m = VesselMeasurement(
        psv_cm_s=1.0,
        edv_cm_s=1.0,
        ri=None,
        sd=None,
        mv_approx=0.0,
        sop_instance_uid="1",
        frame_index=0,
    )
    assert m.averaged_cycles == 1


def test_vessel_measurement_averaged_cycles_custom() -> None:
    m = VesselMeasurement(
        psv_cm_s=1.0,
        edv_cm_s=1.0,
        ri=None,
        sd=None,
        mv_approx=0.0,
        sop_instance_uid="1",
        frame_index=0,
        averaged_cycles=3,
    )
    assert m.averaged_cycles == 3


def test_snapshot_has_vessel_measurements_field() -> None:
    field_names = {f.name for f in fields(MeasurementSnapshot)}
    assert "vessel_measurements" in field_names


def test_snapshot_default_empty() -> None:
    assert MeasurementSnapshot().vessel_measurements == ()
