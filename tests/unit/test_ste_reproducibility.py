"""Reproducibility and multi-cycle averaging tests for STE."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.cardiac_cycle_detector import (
    average_strain_curves,
    detect_cycle_boundaries,
)


def _synthetic_area_signal(n_frames: int = 90) -> np.ndarray:
    t = np.arange(n_frames, dtype=np.float64)
    # 3 cardiac cycles over 90 frames.
    return 1000.0 + 180.0 * np.sin(2.0 * np.pi * t / 30.0)


def _synthetic_longitudinal_strain(n_frames: int = 90) -> np.ndarray:
    t = np.arange(n_frames, dtype=np.float64)
    phase = np.mod(t, 30.0) / 30.0
    # Triangle-like cycle: 0 -> negative peak -> 0.
    cycle = np.where(phase < 0.5, -40.0 * phase, -40.0 * (1.0 - phase))
    return cycle


def test_detect_cycle_boundaries_three_cycles():
    areas = _synthetic_area_signal(90)
    boundaries = detect_cycle_boundaries(areas, min_cycle_frames=15)

    assert len(boundaries) == 2
    assert all(start < end for start, end in boundaries)
    assert all((end - start + 1) >= 15 for start, end in boundaries)
    assert abs(boundaries[0][0] - 8) <= 2
    assert abs(boundaries[1][0] - 38) <= 2


def test_average_strain_curves_resample_and_average():
    base = np.linspace(0.0, -20.0, 10, dtype=np.float64)
    cycle_1 = np.concatenate([base, base[::-1]])
    cycle_2 = cycle_1 + 1.0
    cycle_3 = cycle_1 - 1.0
    full_curve = np.concatenate([cycle_1, cycle_2, cycle_3])
    boundaries = [(0, 19), (20, 39), (40, 59)]

    averaged = average_strain_curves([full_curve], boundaries, n_output_frames=20)
    np.testing.assert_allclose(averaged, cycle_1, atol=1e-6)


def test_gls_reproducible_10_runs():
    gls_values: list[float] = []
    for _ in range(10):
        areas = _synthetic_area_signal(90)
        strain = _synthetic_longitudinal_strain(90)
        boundaries = detect_cycle_boundaries(areas, min_cycle_frames=15)
        assert len(boundaries) >= 2

        averaged = average_strain_curves([strain], boundaries, n_output_frames=90)
        gls_values.append(float(np.min(averaged)))

    assert float(np.std(gls_values)) < 0.5
