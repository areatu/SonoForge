"""Unit tests for strain computation functions."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.strain_computation import (
    apply_drift_compensation,
    arc_contraction_mm,
    arc_length_inflation_mm,
    compute_gls,
    compute_longitudinal_strain_gl,
    compute_radial_strain_gl,
    compute_strain_rate,
    compute_weighted_longitudinal_strain_gl,
    compute_weighted_radial_strain_gl,
    contour_arc_length,
)


def _make_positions(
    n_frames: int = 10,
    n_kernels: int = 6,
    endo_indices: list[int] | None = None,
    epi_indices: list[int] | None = None,
    contraction_ratio: float = 0.9,
) -> np.ndarray:
    """Build synthetic kernel positions that contract toward center."""
    if endo_indices is None:
        endo_indices = [0, 1, 2]
    if epi_indices is None:
        epi_indices = [3, 4, 5]
    n_total = max(max(endo_indices) if endo_indices else 0, max(epi_indices) if epi_indices else 0) + 1
    pos = np.zeros((n_frames, n_total, 2), dtype=np.float64)
    # ED positions: ring around center (50, 50)
    cx, cy = 50.0, 50.0
    for i in range(n_total):
        angle = 2 * np.pi * i / n_total
        r = 20.0 if i in endo_indices else 28.0
        pos[0, i, :] = [cx + r * np.cos(angle), cy + r * np.sin(angle)]
    # Subsequent frames: contract toward center
    for t in range(1, n_frames):
        ratio = 1.0 - (contraction_ratio * t / n_frames)
        for i in range(n_total):
            r = 20.0 if i in endo_indices else 28.0
            pos[t, i, :] = [cx + r * ratio * np.cos(angle := 2 * np.pi * i / n_total), cy + r * ratio * np.sin(angle)]
    return pos


class TestContourArcLength:
    def test_zero_for_single_point(self) -> None:
        pts = np.array([[1.0, 2.0]])
        assert contour_arc_length(pts, (0.5, 0.5)) == 0.0

    def test_known_distance(self) -> None:
        # Two points 10 apart in row direction
        pts = np.array([[0.0, 0.0], [0.0, 10.0]])
        result = contour_arc_length(pts, (1.0, 1.0))
        assert result == pytest.approx(10.0)

    def test_with_pixel_spacing(self) -> None:
        pts = np.array([[0.0, 0.0], [0.0, 10.0]])
        result = contour_arc_length(pts, (0.5, 0.5))
        assert result == pytest.approx(5.0)

    def test_cumulative_length(self) -> None:
        pts = np.array([[0.0, 0.0], [3.0, 0.0], [3.0, 4.0]])
        result = contour_arc_length(pts, (1.0, 1.0))
        assert result == pytest.approx(7.0)  # 3 + 4


class TestComputeLongitudinalStrainGL:
    def test_returns_zero_for_zero_length(self) -> None:
        # All points at same position → l0 = 0
        pos = np.zeros((5, 3, 2), dtype=np.float64)
        strain = compute_longitudinal_strain_gl(pos, 0, (1.0, 1.0), [0, 1, 2])
        assert np.all(strain == 0.0)

    def test_homogeneous_contraction(self) -> None:
        pos = _make_positions(n_frames=10, contraction_ratio=0.1)
        strain = compute_longitudinal_strain_gl(pos, 0, (1.0, 1.0), [0, 1, 2])
        # First frame = 0 by definition
        assert strain[0] == pytest.approx(0.0)
        # Later frames should show shortening (negative strain)
        assert strain[-1] < 0.0

    def test_output_length_matches_frames(self) -> None:
        pos = _make_positions(n_frames=8)
        strain = compute_longitudinal_strain_gl(pos, 0, (1.0, 1.0), [0, 1, 2])
        assert len(strain) == 8


class TestApplyDriftCompensation:
    def test_zeroes_at_ed_and_end(self) -> None:
        strain = np.array([0.0, -5.0, -10.0, -15.0, -10.0, -5.0, 0.0])
        result = apply_drift_compensation(strain, ed_index=0, end_index=6)
        assert result[0] == pytest.approx(0.0)
        assert result[6] == pytest.approx(0.0)

    def test_no_change_when_ed_equals_end(self) -> None:
        strain = np.array([1.0, 2.0, 3.0])
        result = apply_drift_compensation(strain, ed_index=1, end_index=1)
        np.testing.assert_array_equal(result, strain)

    def test_single_element(self) -> None:
        strain = np.array([5.0])
        result = apply_drift_compensation(strain, ed_index=0, end_index=0)
        assert result[0] == 5.0

    def test_does_not_mutate_input(self) -> None:
        strain = np.array([0.0, -5.0, -10.0])
        original = strain.copy()
        apply_drift_compensation(strain, 0, 2)
        np.testing.assert_array_equal(strain, original)


class TestComputeRadialStrainGL:
    def test_returns_zero_for_zero_thickness(self) -> None:
        pos = np.zeros((5, 6, 2), dtype=np.float64)
        strain = compute_radial_strain_gl(pos, 0, (1.0, 1.0), [0, 1, 2], [3, 4, 5])
        assert np.all(strain == 0.0)

    def test_wall_thickening_gives_positive_strain(self) -> None:
        # Manually create positions where epi moves outward relative to endo
        n_frames, n_kernels = 5, 6
        pos = np.zeros((n_frames, n_kernels, 2), dtype=np.float64)
        cx, cy = 50.0, 50.0
        for i in range(3):
            angle = 2 * np.pi * i / 3
            # endo at radius 10, epi at radius 20
            pos[0, i, :] = [cx + 10 * np.cos(angle), cy + 10 * np.sin(angle)]
            pos[0, i + 3, :] = [cx + 20 * np.cos(angle), cy + 20 * np.sin(angle)]
        # At t>0: endo stays, epi moves outward → thicker wall
        for t in range(1, n_frames):
            pos[t, :3] = pos[0, :3]
            for i in range(3):
                angle = 2 * np.pi * i / 3
                pos[t, i + 3, :] = [cx + 25 * np.cos(angle), cy + 25 * np.sin(angle)]
        strain = compute_radial_strain_gl(pos, 0, (1.0, 1.0), [0, 1, 2], [3, 4, 5])
        assert strain[0] == pytest.approx(0.0)
        assert strain[-1] > 0.0


class TestComputeGls:
    def test_returns_zero_when_ed_equals_es(self) -> None:
        strain = np.array([0.0, -5.0, -10.0])
        assert compute_gls(strain, 1, 1) == 0.0

    def test_finds_min_in_segment(self) -> None:
        strain = np.array([0.0, -5.0, -15.0, -10.0, 0.0])
        assert compute_gls(strain, 0, 4) == pytest.approx(-15.0)

    def test_reversed_ed_es(self) -> None:
        strain = np.array([0.0, -5.0, -15.0, -10.0, 0.0])
        assert compute_gls(strain, 4, 0) == pytest.approx(-15.0)

    def test_empty_segment(self) -> None:
        strain = np.array([0.0])
        assert compute_gls(strain, 0, 0) == 0.0


class TestComputeWeightedLongitudinalStrainGL:
    def test_returns_zeros_for_few_endo(self) -> None:
        pos = np.zeros((5, 3, 2), dtype=np.float64)
        result = compute_weighted_longitudinal_strain_gl(pos, 0, (1.0, 1.0), [0])
        assert np.all(result == 0.0)

    def test_zero_length_at_ed(self) -> None:
        pos = np.zeros((5, 6, 2), dtype=np.float64)
        result = compute_weighted_longitudinal_strain_gl(pos, 0, (1.0, 1.0), [0, 1, 2])
        assert np.all(result == 0.0)


class TestComputeWeightedRadialStrainGL:
    def test_returns_zeros_for_no_pairs(self) -> None:
        pos = np.zeros((5, 3, 2), dtype=np.float64)
        result = compute_weighted_radial_strain_gl(pos, 0, (1.0, 1.0), [0], [])
        assert np.all(result == 0.0)

    def test_zero_thickness_at_ed(self) -> None:
        pos = np.zeros((5, 6, 2), dtype=np.float64)
        result = compute_weighted_radial_strain_gl(pos, 0, (1.0, 1.0), [0, 1, 2], [3, 4, 5])
        assert np.all(result == 0.0)


class TestComputeStrainRate:
    def test_constant_strain_gives_zero_rate(self) -> None:
        strain = np.full(10, -10.0)
        times = list(range(10))
        rate = compute_strain_rate(strain, times)
        np.testing.assert_allclose(rate, 0.0)

    def test_linear_strain_gives_constant_rate(self) -> None:
        strain = np.array([0.0, -1.0, -2.0, -3.0])
        times = [0.0, 33.3, 66.6, 99.9]  # 33.3ms intervals
        rate = compute_strain_rate(strain, times)
        # dt = 33.3ms = 0.0333s, dstrain = -1.0 → rate ≈ -30 %/s
        assert rate[1] == pytest.approx(-30.0, abs=1.0)

    def test_wrong_length_times_falls_back(self) -> None:
        strain = np.array([0.0, -1.0, -2.0])
        rate = compute_strain_rate(strain, [10.0])  # wrong length
        assert len(rate) == 3

    def test_zero_dt_gives_zero_rate(self) -> None:
        strain = np.array([0.0, -1.0])
        rate = compute_strain_rate(strain, [50.0, 50.0])
        assert rate[1] == 0.0


class TestNoiseVsSignalMetrics:
    """The measurement-theory checks behind the honest QC (plan §7.5, F6).

    Noise inflates every arc length, so a noisy clip reads *less* strain while
    its NCC stays high. ``arc_length_inflation_mm`` measures that inflation
    directly and ``arc_contraction_mm`` measures the signal it competes with.
    """

    @staticmethod
    def _arc(n_frames: int = 6, contraction: float = 0.8, spacing: float = 1.0) -> np.ndarray:
        """A straight line of nodes that shortens by ``contraction``."""
        pts = np.zeros((n_frames, 6, 2), dtype=np.float64)
        for t in range(n_frames):
            step = 10.0 * spacing * (contraction if t == n_frames - 1 else 1.0)
            pts[t, :, 0] = np.arange(6) * step
        return pts

    def test_noise_inflates_the_polyline(self) -> None:
        rng = np.random.default_rng(7)
        raw = self._arc() + rng.normal(0.0, 0.5, (6, 6, 2))
        clean = self._arc()
        inflation = arc_length_inflation_mm(raw, clean, list(range(6)), (0.5, 0.5))
        assert inflation > 0.0

    def test_clean_positions_have_no_inflation(self) -> None:
        pts = self._arc()
        assert arc_length_inflation_mm(pts, pts, list(range(6)), (0.5, 0.5)) == 0.0

    def test_contraction_is_measured_from_ed(self) -> None:
        pts = self._arc(contraction=0.8, spacing=1.0)
        # ED length 50 px, ES length 40 px, spacing 0.5 mm/px → 5 mm
        assert arc_contraction_mm(pts, list(range(6)), 0, (0.5, 0.5)) == pytest.approx(5.0, abs=1e-6)

    def test_no_contraction_reads_zero_not_negative(self) -> None:
        pts = self._arc(contraction=1.0)
        assert arc_contraction_mm(pts, list(range(6)), 0, (1.0, 1.0)) == 0.0
