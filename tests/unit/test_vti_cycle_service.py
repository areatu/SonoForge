"""Unit tests for domain/services/vti_cycle_service.py."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.cardiac_cycle_service import CardiacCycle
from echo_personal_tool.domain.services.vti_cycle_service import (
    envelope_points_in_cycle,
    vti_for_cycles,
    vti_from_points,
    vti_in_cycle,
)


def _cycle(start_ms: float, end_ms: float) -> CardiacCycle:
    return CardiacCycle(
        start_ms=start_ms,
        end_ms=end_ms,
        r_peak_ms=start_ms,
        ed_ms=start_ms,
        es_ms=end_ms,
        source="ecg",
        confidence=0.9,
    )


def _triangle_envelope(duration_ms: float = 1000.0, peak_vel: float = 100.0) -> tuple[tuple[float, float], ...]:
    step_ms = 50.0
    n = int(duration_ms / step_ms) + 1
    points: list[tuple[float, float]] = []
    for i in range(n):
        t = i * step_ms
        v = peak_vel * (1.0 - abs(t - duration_ms / 2.0) / (duration_ms / 2.0))
        points.append((t, v))
    return tuple(points)


class TestEnvelopePointsInCycle:
    def test_selects_points_inside_cycle(self) -> None:
        envelope = ((0.0, 10.0), (100.0, 20.0), (200.0, 30.0), (300.0, 20.0), (400.0, 10.0))
        assert envelope_points_in_cycle(envelope, _cycle(100.0, 300.0)) == (
            (100.0, 20.0),
            (200.0, 30.0),
            (300.0, 20.0),
        )

    def test_sparse_cycle_returns_empty(self) -> None:
        envelope = ((0.0, 10.0), (400.0, 10.0))
        assert envelope_points_in_cycle(envelope, _cycle(100.0, 300.0)) == ()

    def test_min_points_parameter(self) -> None:
        envelope = ((0.0, 10.0), (200.0, 30.0), (400.0, 10.0))
        assert envelope_points_in_cycle(envelope, _cycle(0.0, 400.0), min_points=4) == ()


class TestVtiFromPoints:
    def test_triangle_area(self) -> None:
        # triangle base 1000 ms = 1 s, height 100 cm/s -> true VTI 50 cm
        assert vti_from_points(_triangle_envelope()) == pytest.approx(50.0)

    def test_flat_zero(self) -> None:
        assert vti_from_points(((0.0, 0.0), (1000.0, 0.0))) == pytest.approx(0.0)


class TestVtiInCycle:
    def test_returns_area_of_cycle_clip(self) -> None:
        envelope = _triangle_envelope(duration_ms=2000.0, peak_vel=100.0)
        cycle = _cycle(1000.0, 2000.0)
        vti = vti_in_cycle(envelope, cycle)
        assert vti is not None
        # rising half of triangle: base 1000 ms = 1 s, height 100 cm/s -> 50 cm
        assert vti == pytest.approx(50.0)

    def test_sparse_cycle_returns_none(self) -> None:
        envelope = ((0.0, 10.0), (500.0, 10.0), (2000.0, 10.0))
        assert vti_in_cycle(envelope, _cycle(100.0, 1900.0)) is None


class TestVtiForCycles:
    def test_computes_vti_per_cycle(self) -> None:
        envelope = _triangle_envelope(duration_ms=2000.0, peak_vel=100.0)
        cycles = (_cycle(0.0, 1000.0), _cycle(1000.0, 2000.0))
        results = vti_for_cycles(envelope, cycles)
        assert len(results) == 2
        assert results[0].vti_cm == pytest.approx(50.0)
        assert results[1].vti_cm == pytest.approx(50.0)
        assert results[0].cycle == cycles[0]

    def test_skips_sparse_cycles(self) -> None:
        envelope = ((0.0, 10.0), (500.0, 10.0), (2000.0, 10.0))
        cycles = (_cycle(0.0, 1000.0), _cycle(1000.0, 2000.0))
        assert vti_for_cycles(envelope, cycles) == []

    def test_empty_envelope(self) -> None:
        assert vti_for_cycles((), (_cycle(0.0, 1000.0),)) == []
