"""Tests for relative wall thickness (RWT / ОТС)."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.rwt import (
    from_linear_measurements,
    relative_wall_thickness,
)
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement


def test_relative_wall_thickness_formula() -> None:
    assert relative_wall_thickness(8.0, 40.0) == 0.4


def test_from_linear_measurements_requires_lvedd_and_lvpwd() -> None:
    measurements = (
        LinearMeasurement(
            label="IVSd",
            pixel_length=10.0,
            millimeter_length=8.0,
            frame_index=0,
            start=(0.0, 0.0),
            end=(10.0, 0.0),
        ),
        LinearMeasurement(
            label="LVEDD",
            pixel_length=40.0,
            millimeter_length=40.0,
            frame_index=0,
            start=(0.0, 0.0),
            end=(40.0, 0.0),
        ),
        LinearMeasurement(
            label="LVPWd",
            pixel_length=8.0,
            millimeter_length=8.0,
            frame_index=0,
            start=(0.0, 0.0),
            end=(8.0, 0.0),
        ),
    )
    assert from_linear_measurements(measurements) == 0.4
