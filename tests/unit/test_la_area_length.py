"""Unit tests for left atrial area-length volume."""

from __future__ import annotations

import math

import pytest

from echo_personal_tool.domain.calculations.la_area_length import (
    from_measurements,
    volume_ml,
)
from echo_personal_tool.domain.models import Contour, LinearMeasurement


def test_volume_ml_uses_ase_formula() -> None:
    area_cm2 = 20.0
    length_cm = 5.0
    expected = (8.0 * area_cm2 * area_cm2) / (3.0 * math.pi * length_cm)
    assert volume_ml(area_cm2, length_cm) == pytest.approx(expected)


def test_volume_ml_rejects_non_positive_inputs() -> None:
    assert volume_ml(0.0, 5.0) == 0.0
    assert volume_ml(20.0, 0.0) == 0.0


def test_from_measurements_computes_lav_from_contour_and_caliper() -> None:
    la_contour = Contour(
        phase="ES",
        view="A4C",
        chamber="LA",
        points=[(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)],
    )
    measurements = (
        LinearMeasurement(label="LAL", pixel_length=50.0, millimeter_length=50.0),
    )
    result = from_measurements((la_contour,), measurements, (1.0, 1.0))
    assert result is not None
    assert result.area_cm2 == pytest.approx(50.0)
    assert result.length_cm == pytest.approx(5.0)
    assert result.volume_ml == pytest.approx(volume_ml(50.0, 5.0))


def test_from_measurements_returns_partial_result_without_length() -> None:
    la_contour = Contour(
        phase="ES",
        chamber="LA",
        points=[(0.0, 0.0), (100.0, 0.0), (0.0, 100.0)],
    )
    result = from_measurements((la_contour,), (), (1.0, 1.0))
    assert result is not None
    assert result.area_cm2 == pytest.approx(50.0)
    assert result.length_cm is None
    assert result.volume_ml is None


def test_from_measurements_ignores_lv_contours() -> None:
    lv_contour = Contour(
        phase="ED",
        points=[(0.0, 0.0), (100.0, 0.0), (50.0, 80.0)],
        mitral_annulus=((0.0, 0.0), (100.0, 0.0)),
    )
    result = from_measurements((lv_contour,), (), (1.0, 1.0))
    assert result is None
