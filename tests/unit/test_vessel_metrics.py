"""Tests for vessel_metrics.compute_vessel_metrics."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.vessel_metrics import (
    compute_vessel_metrics,
)


def test_happy_path() -> None:
    m = compute_vessel_metrics(178.4, 62.1)
    assert m.ri == pytest.approx((178.4 - 62.1) / 178.4)
    assert m.sd == pytest.approx(178.4 / 62.1)
    assert m.mv_approx == pytest.approx((178.4 + 2 * 62.1) / 3)
    assert m.valid is True


def test_psv_leq_edv_marks_invalid() -> None:
    m = compute_vessel_metrics(50.0, 80.0)
    assert m.valid is False
    assert m.ri is None
    assert m.sd is None
    assert m.mv_approx is None


def test_edv_zero_returns_ri_one() -> None:
    m = compute_vessel_metrics(120.0, 0.0)
    assert m.sd is None
    assert m.ri == pytest.approx(1.0)
    assert m.valid is True
    assert m.mv_approx == pytest.approx(40.0)


def test_psv_zero_no_ri() -> None:
    m = compute_vessel_metrics(0.0, 10.0)
    assert m.ri is None
