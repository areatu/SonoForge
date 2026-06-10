"""Unit tests for Bernoulli pressure gradient calculation."""

from __future__ import annotations

from echo_personal_tool.domain.calculations.bernoulli import pressure_gradient_mmhg


def test_pressure_gradient_100_cm_s() -> None:
    assert pressure_gradient_mmhg(100.0) == 4.0


def test_pressure_gradient_200_cm_s() -> None:
    assert pressure_gradient_mmhg(200.0) == 16.0


def test_pressure_gradient_zero() -> None:
    assert pressure_gradient_mmhg(0.0) == 0.0
