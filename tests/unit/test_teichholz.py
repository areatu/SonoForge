"""Unit tests for Teichholz volume calculations."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.teichholz import (
    from_linear_measurements,
    volume_ml,
)
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement


def test_volume_ml_lvedd_50mm() -> None:
    assert volume_ml(50.0) == pytest.approx(118.243, rel=1e-3)


def test_volume_ml_lvesd_35mm() -> None:
    assert volume_ml(35.0) == pytest.approx(50.869, rel=1e-3)


def test_volume_ml_zero_raises() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        volume_ml(0.0)


def test_volume_ml_negative_raises() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        volume_ml(-10.0)


def test_from_linear_measurements_computes_lvef() -> None:
    measurements = (
        LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),
        LinearMeasurement(label="LVESD", pixel_length=70.0, millimeter_length=35.0),
    )

    result = from_linear_measurements(measurements)

    assert result is not None
    assert result.edv_ml == pytest.approx(118.243, rel=1e-3)
    assert result.esv_ml == pytest.approx(50.869, rel=1e-3)
    assert result.lvef_percent == pytest.approx(
        (118.243 - 50.869) / 118.243 * 100.0,
        rel=1e-3,
    )


def test_from_linear_measurements_case_insensitive_labels() -> None:
    measurements = (
        LinearMeasurement(label="lvedd", pixel_length=100.0, millimeter_length=50.0),
        LinearMeasurement(label="lvesd", pixel_length=70.0, millimeter_length=35.0),
    )

    result = from_linear_measurements(measurements)

    assert result is not None
    assert result.edv_ml == pytest.approx(118.243, rel=1e-3)
    assert result.esv_ml == pytest.approx(50.869, rel=1e-3)


def test_from_linear_measurements_missing_lvedd_returns_none() -> None:
    measurements = (
        LinearMeasurement(label="LVESD", pixel_length=70.0, millimeter_length=35.0),
    )

    assert from_linear_measurements(measurements) is None


def test_from_linear_measurements_missing_lvesd_returns_none() -> None:
    measurements = (
        LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),
    )

    assert from_linear_measurements(measurements) is None


def test_from_linear_measurements_skips_missing_millimeter_length() -> None:
    measurements = (
        LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=None),
        LinearMeasurement(label="LVESD", pixel_length=70.0, millimeter_length=35.0),
    )

    assert from_linear_measurements(measurements) is None
