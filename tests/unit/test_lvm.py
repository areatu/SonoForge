"""Tests for LVM cube calculation."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.lvm import from_linear_measurements, lvm_grams
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement


def test_lvm_grams_cube_formula() -> None:
    result = lvm_grams(ivsd_mm=10.0, lvedd_mm=50.0, lvpwd_mm=10.0)
    assert 170.0 < result < 190.0


def test_from_linear_measurements_requires_three_labels() -> None:
    measurements = (
        LinearMeasurement(label="IVSd", pixel_length=20.0, millimeter_length=10.0),
        LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),
    )
    assert from_linear_measurements(measurements, spacing_calibrated=True) is None

    measurements = (
        *measurements,
        LinearMeasurement(label="LVPWd", pixel_length=20.0, millimeter_length=10.0),
    )
    assert from_linear_measurements(measurements, spacing_calibrated=True) is not None


def test_uncalibrated_calipers_do_not_become_grams() -> None:
    measurements = tuple(
        LinearMeasurement(label, pixel_length=50.0, millimeter_length=value)
        for label, value in (("IVSD", 10.0), ("LVEDD", 50.0), ("LVPWD", 9.0))
    )

    assert from_linear_measurements(measurements) is None
    assert from_linear_measurements(measurements, spacing_calibrated=True) is not None
