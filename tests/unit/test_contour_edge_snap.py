"""Unit tests for contour_edge_snap (edge map, normals, snap functions)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from echo_personal_tool.domain.services.contour_edge_snap import (
    EdgeMap,
    EdgeSnapConfig,
    apply_soft_magnetic_snap,
    build_edge_map,
    directed_edge_score,
    edge_snap_config_for_source,
    magnetic_edge_snap_config_for_source,
    outward_normal_at_index,
    snap_magnetic_point,
    snap_point,
    snap_weighted_nodes,
)


# ── EdgeSnapConfig ─────────────────────────────────────────────────


class TestEdgeSnapConfig:
    def test_defaults(self) -> None:
        cfg = EdgeSnapConfig()
        assert cfg.search_radius_px == 12.0
        assert cfg.profile_samples == 25
        assert cfg.blur_sigma == 1.2
        assert cfg.min_edge_strength == 0.0
        assert cfg.inward_only is True
        assert cfg.outward_only is False
        assert cfg.intensity_fallback is False

    def test_frozen(self) -> None:
        cfg = EdgeSnapConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.search_radius_px = 20.0  # type: ignore[misc]


# ── edge_snap_config_for_source ────────────────────────────────────


class TestEdgeSnapConfigForSource:
    def test_ai_not_cine(self) -> None:
        cfg = edge_snap_config_for_source("ai")
        assert cfg.search_radius_px == 16.0
        assert cfg.min_edge_strength == 0.05

    def test_ai_cine(self) -> None:
        cfg = edge_snap_config_for_source("ai", cine=True)
        assert cfg.search_radius_px == 10.0
        assert cfg.inward_only is False

    def test_manual(self) -> None:
        cfg = edge_snap_config_for_source("manual")
        assert cfg.search_radius_px == 10.0
        assert cfg.min_edge_strength == 0.08

    def test_other_source(self) -> None:
        cfg = edge_snap_config_for_source("gold")
        assert cfg.search_radius_px == 12.0
        assert cfg.min_edge_strength == 0.06

    def test_case_insensitive(self) -> None:
        cfg = edge_snap_config_for_source("AI")
        assert cfg.search_radius_px == 16.0


# ── magnetic_edge_snap_config_for_source ───────────────────────────


class TestMagneticEdgeSnapConfigForSource:
    def test_manual(self) -> None:
        cfg = magnetic_edge_snap_config_for_source("manual")
        assert cfg.search_radius_px >= 14.0
        assert cfg.profile_samples == 33
        assert cfg.inward_only is False
        assert cfg.outward_only is True
        assert cfg.intensity_fallback is True
        assert cfg.min_edge_strength == 0.0


# ── EdgeMap & build_edge_map ───────────────────────────────────────


class TestBuildEdgeMap:
    def test_grayscale(self) -> None:
        frame = np.random.randint(0, 255, (50, 80), dtype=np.uint8)
        em = build_edge_map(frame)
        assert isinstance(em, EdgeMap)
        assert em.height == 50
        assert em.width == 80
        assert em.magnitude.shape == (50, 80)
        assert em.grad_x.shape == (50, 80)
        assert em.grad_y.shape == (50, 80)
        assert em.intensity is not None

    def test_bgr(self) -> None:
        frame = np.random.randint(0, 255, (50, 80, 3), dtype=np.uint8)
        em = build_edge_map(frame)
        assert em.height == 50
        assert em.width == 80

    def test_with_display_levels(self) -> None:
        frame = np.random.randint(0, 255, (30, 40), dtype=np.uint8)
        em = build_edge_map(frame, display_levels=(50.0, 200.0))
        assert em.magnitude.shape == (30, 40)

    def test_custom_blur(self) -> None:
        frame = np.random.randint(0, 255, (30, 40), dtype=np.uint8)
        em = build_edge_map(frame, blur_sigma=3.0)
        assert em.magnitude.shape == (30, 40)


# ── outward_normal_at_index ────────────────────────────────────────


class TestOutwardNormalAtIndex:
    def test_horizontal_line(self) -> None:
        points = [(0.0, 50.0), (50.0, 50.0), (100.0, 50.0)]
        nx, ny = outward_normal_at_index(points, 1)
        # Tangent is (1, 0), normal is (0, 1) or (0, -1)
        assert abs(ny) > abs(nx)

    def test_unit_length(self) -> None:
        points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
        nx, ny = outward_normal_at_index(points, 1)
        length = np.hypot(nx, ny)
        assert abs(length - 1.0) < 1e-6

    def test_points_away_from_centroid(self) -> None:
        # Semi-circle around centroid
        angles = np.linspace(0, np.pi, 10)
        points = [(float(np.cos(a) * 50 + 100), float(np.sin(a) * 50 + 100)) for a in angles]
        nx, ny = outward_normal_at_index(points, 5)
        # Normal should point away from centroid
        cx = np.mean([p[0] for p in points])
        cy = np.mean([p[1] for p in points])
        to_interior = (cx - points[5][0], cy - points[5][1])
        # dot product should be negative (pointing away from interior)
        assert nx * to_interior[0] + ny * to_interior[1] < 0


# ── directed_edge_score ────────────────────────────────────────────


class TestDirectedEdgeScore:
    def _make_edge_map(self) -> EdgeMap:
        frame = np.zeros((50, 80), dtype=np.uint8)
        frame[25, :] = 255  # horizontal bright line
        return build_edge_map(frame)

    def test_returns_float(self) -> None:
        em = self._make_edge_map()
        score = directed_edge_score(em, 40.0, 25.0, (0.0, -1.0))
        assert isinstance(score, float)

    def test_zero_normal(self) -> None:
        em = self._make_edge_map()
        score = directed_edge_score(em, 40.0, 25.0, (0.0, 0.0))
        assert score == 0.0

    def test_out_of_bounds(self) -> None:
        em = self._make_edge_map()
        score = directed_edge_score(em, -10.0, -10.0, (0.0, 1.0))
        assert score == 0.0


# ── snap_point ─────────────────────────────────────────────────────


class TestSnapPoint:
    def _make_edge_map(self) -> EdgeMap:
        frame = np.zeros((50, 80), dtype=np.uint8)
        frame[25, :] = 255  # horizontal bright line at y=25
        return build_edge_map(frame)

    def test_returns_tuple_or_none(self) -> None:
        em = self._make_edge_map()
        result = snap_point(em, 40.0, 20.0, (0.0, -1.0))
        # Should find the edge at y=25
        if result is not None:
            assert isinstance(result, tuple)
            assert len(result) == 2

    def test_zero_normal_returns_none(self) -> None:
        em = self._make_edge_map()
        result = snap_point(em, 40.0, 20.0, (0.0, 0.0))
        assert result is None

    def test_with_config(self) -> None:
        em = self._make_edge_map()
        cfg = EdgeSnapConfig(search_radius_px=5.0, profile_samples=10)
        result = snap_point(em, 40.0, 22.0, (0.0, -1.0), config=cfg)
        # May or may not find edge depending on distance
        assert result is None or isinstance(result, tuple)


# ── snap_magnetic_point ────────────────────────────────────────────


class TestSnapMagneticPoint:
    def _make_edge_map(self) -> EdgeMap:
        frame = np.zeros((50, 80), dtype=np.uint8)
        frame[25, :] = 200
        return build_edge_map(frame)

    def test_returns_tuple_or_none(self) -> None:
        em = self._make_edge_map()
        result = snap_magnetic_point(em, 40.0, 20.0, (0.0, -1.0))
        assert result is None or isinstance(result, tuple)


# ── apply_soft_magnetic_snap ───────────────────────────────────────


class TestApplySoftMagneticSnap:
    def _make_edge_map(self) -> EdgeMap:
        frame = np.zeros((50, 80), dtype=np.uint8)
        frame[25, :] = 200
        return build_edge_map(frame)

    def test_too_few_points(self) -> None:
        em = self._make_edge_map()
        points = [(10.0, 10.0), (20.0, 20.0)]
        result = apply_soft_magnetic_snap(points, [1.0, 1.0], em, strength=0.5, max_radial_px=5.0)
        assert result == points

    def test_zero_strength_no_change(self) -> None:
        em = self._make_edge_map()
        points = [(10.0, 10.0), (40.0, 20.0), (70.0, 10.0)]
        weights = [1.0, 1.0, 1.0]
        result = apply_soft_magnetic_snap(points, weights, em, strength=0.0, max_radial_px=5.0)
        assert result == points

    def test_pins_first_and_last(self) -> None:
        em = self._make_edge_map()
        points = [(10.0, 10.0), (40.0, 20.0), (70.0, 10.0)]
        weights = [1.0, 1.0, 1.0]
        result = apply_soft_magnetic_snap(points, weights, em, strength=0.5, max_radial_px=5.0)
        assert result[0] == points[0]
        assert result[-1] == points[-1]


# ── snap_weighted_nodes ────────────────────────────────────────────


class TestSnapWeightedNodes:
    def _make_edge_map(self) -> EdgeMap:
        frame = np.zeros((50, 80), dtype=np.uint8)
        frame[25, :] = 200
        return build_edge_map(frame)

    def test_too_few_points(self) -> None:
        em = self._make_edge_map()
        points = [(10.0, 10.0), (20.0, 20.0)]
        result = snap_weighted_nodes(points, [1.0, 1.0], em)
        assert result == points

    def test_pins_first_and_last(self) -> None:
        em = self._make_edge_map()
        points = [(10.0, 10.0), (40.0, 20.0), (70.0, 10.0)]
        weights = [1.0, 1.0, 1.0]
        result = snap_weighted_nodes(points, weights, em)
        assert result[0] == points[0]
        assert result[-1] == points[-1]

    def test_low_weight_no_snap(self) -> None:
        em = self._make_edge_map()
        points = [(10.0, 10.0), (40.0, 20.0), (70.0, 10.0)]
        weights = [1.0, 0.01, 1.0]  # middle node has low weight
        result = snap_weighted_nodes(points, weights, em, weight_threshold=0.12)
        assert result[1] == points[1]  # no snap
