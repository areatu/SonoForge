"""Tests for contour_edge_snap module."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.services.contour_edge_snap import (
    EdgeSnapConfig,
    _clamp,
    _sample_bilinear,
    _to_grayscale,
    build_edge_map,
    directed_edge_score,
    edge_snap_config_for_source,
    magnetic_edge_snap_config_for_source,
    outward_normal_at_index,
    outward_normal_at_index_closed,
    snap_closed_polygon,
    snap_magnetic_point,
    snap_point,
)


def _make_edge_map(w=64, h=64):
    frame = np.random.RandomState(42).randint(0, 256, size=(h, w), dtype=np.uint8)
    return build_edge_map(frame, blur_sigma=1.0)


class TestEdgeSnapConfigForSource:
    def test_ai_not_cine(self):
        cfg = edge_snap_config_for_source("AI", cine=False)
        assert cfg.search_radius_px == 16.0
        assert cfg.min_edge_strength == 0.05

    def test_ai_cine(self):
        cfg = edge_snap_config_for_source("ai", cine=True)
        assert cfg.search_radius_px == 10.0
        assert cfg.inward_only is False

    def test_manual(self):
        cfg = edge_snap_config_for_source("manual")
        assert cfg.search_radius_px == 10.0
        assert cfg.min_edge_strength == 0.08

    def test_unknown_source(self):
        cfg = edge_snap_config_for_source("unknown")
        assert cfg.search_radius_px == 12.0


class TestMagneticEdgeSnapConfig:
    def test_base_ai(self):
        cfg = magnetic_edge_snap_config_for_source("ai")
        assert cfg.outward_only is True
        assert cfg.intensity_fallback is True
        assert cfg.inward_only is False
        assert cfg.profile_samples == 33

    def test_search_radius_minimum(self):
        cfg = magnetic_edge_snap_config_for_source("manual")
        assert cfg.search_radius_px >= 14.0


class TestBuildEdgeMap:
    def test_grayscale_input(self):
        frame = np.zeros((32, 48), dtype=np.uint8)
        em = build_edge_map(frame)
        assert em.height == 32
        assert em.width == 48
        assert em.magnitude.shape == (32, 48)
        assert em.intensity is not None

    def test_bgr_input(self):
        frame = np.zeros((32, 48, 3), dtype=np.uint8)
        em = build_edge_map(frame)
        assert em.height == 32

    def test_display_levels(self):
        frame = np.zeros((32, 48), dtype=np.uint8)
        frame[10:20, 10:30] = 200
        em = build_edge_map(frame, display_levels=(50.0, 200.0))
        assert em.height == 32


class TestOutwardNormalAtIndex:
    def test_straight_line(self):
        points = [(0.0, 50.0), (50.0, 50.0), (100.0, 50.0)]
        nx, ny = outward_normal_at_index(points, 1)
        assert isinstance(nx, float)
        assert isinstance(ny, float)
        length = np.hypot(nx, ny)
        assert length == pytest.approx(1.0, abs=0.01)

    def test_first_last_not_interior(self):
        """Centroid test: normal should point away from centroid."""
        points = [(10.0, 10.0), (50.0, 30.0), (90.0, 10.0)]
        nx, ny = outward_normal_at_index(points, 1)
        # Centroid is at ~(50, 16.7), interior direction is roughly (0, -14)
        # Normal should point toward positive y (away from interior)
        assert ny > 0 or abs(ny) < 0.5

    def test_zero_length_tangent(self):
        points = [(50.0, 50.0), (50.0, 50.0), (50.0, 50.0)]
        nx, ny = outward_normal_at_index(points, 1)
        assert nx == 0.0
        assert ny == -1.0


class TestSampleBilinear:
    def test_integer_position(self):
        em = _make_edge_map()
        val = _sample_bilinear(em.magnitude, 10.0, 10.0, em)
        assert isinstance(val, float)

    def test_out_of_bounds(self):
        em = _make_edge_map()
        assert _sample_bilinear(em.magnitude, -1.0, 5.0, em) == 0.0
        assert _sample_bilinear(em.magnitude, 5.0, -1.0, em) == 0.0

    def test_edge_position(self):
        em = _make_edge_map(w=10, h=10)
        assert _sample_bilinear(em.magnitude, 9.5, 9.5, em) == 0.0


class TestClamp:
    def test_within_range(self):
        assert _clamp(5.0, 0.0, 10.0) == 5.0

    def test_below_min(self):
        assert _clamp(-3.0, 0.0, 10.0) == 0.0

    def test_above_max(self):
        assert _clamp(15.0, 0.0, 10.0) == 10.0


class TestDirectedEdgeScore:
    def test_zero_normal(self):
        em = _make_edge_map()
        score = directed_edge_score(em, 32.0, 32.0, (0.0, 0.0))
        assert score == 0.0

    def test_valid_point(self):
        em = _make_edge_map()
        score = directed_edge_score(em, 32.0, 32.0, (0.0, -1.0))
        assert score >= 0.0

    def test_bidirectional(self):
        em = _make_edge_map()
        score_in = directed_edge_score(em, 32.0, 32.0, (1.0, 0.0), inward_only=True)
        score_bi = directed_edge_score(em, 32.0, 32.0, (1.0, 0.0), inward_only=False)
        assert score_bi >= score_in


class TestSnapPoint:
    def test_returns_none_or_point(self):
        em = _make_edge_map()
        result = snap_point(em, 32.0, 32.0, (1.0, 0.0))
        assert result is None or (isinstance(result, tuple) and len(result) == 2)

    def test_with_config(self):
        em = _make_edge_map()
        cfg = EdgeSnapConfig(search_radius_px=5.0, min_edge_strength=0.0)
        result = snap_point(em, 32.0, 32.0, (0.0, -1.0), config=cfg)
        assert result is None or isinstance(result, tuple)

    def test_zero_normal(self):
        em = _make_edge_map()
        result = snap_point(em, 32.0, 32.0, (0.0, 0.0))
        assert result is None

    def test_subpixel_snap_accuracy(self):
        # Create a sharp step edge at x=32.5
        img = np.zeros((64, 64), dtype=np.uint8)
        img[:, 33:] = 255
        em = build_edge_map(img, blur_sigma=0.8)
        # Snap from x=30.0 along normal (1, 0)
        cfg = EdgeSnapConfig(search_radius_px=6.0, min_edge_strength=0.01)
        snapped = snap_point(em, 30.0, 32.0, (1.0, 0.0), config=cfg)
        assert snapped is not None
        # Snapped x should be close to the boundary (around 32-33)
        assert 31.5 <= snapped[0] <= 33.5


class TestToGrayscale:
    def test_grayscale_passthrough(self):
        arr = np.zeros((10, 10), dtype=np.float64)
        result = _to_grayscale(arr)
        assert result.dtype == np.float64

    def test_bgr_conversion(self):
        arr = np.zeros((10, 10, 3), dtype=np.uint8)
        result = _to_grayscale(arr)
        assert result.ndim == 2


class TestSnapMagneticPoint:
    def test_returns_none_or_tuple(self):
        em = _make_edge_map()
        result = snap_magnetic_point(em, 32.0, 32.0, (1.0, 0.0))
        assert result is None or (isinstance(result, tuple) and len(result) == 2)

    def test_zero_normal(self):
        em = _make_edge_map()
        result = snap_magnetic_point(em, 32.0, 32.0, (0.0, 0.0))
        assert result is None


class TestOutwardNormalAtIndexClosed:
    def test_wraps_at_end(self) -> None:
        points = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)]
        nx, ny = outward_normal_at_index_closed(points, 3)
        length = np.hypot(nx, ny)
        assert length == pytest.approx(1.0, abs=0.01)

    def test_wraps_at_start(self) -> None:
        points = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)]
        nx, ny = outward_normal_at_index_closed(points, 0)
        length = np.hypot(nx, ny)
        assert length == pytest.approx(1.0, abs=0.01)


class TestSnapClosedPolygon:
    def test_returns_same_length(self) -> None:
        em = _make_edge_map()
        points = [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)]
        result = snap_closed_polygon(points, em)
        assert len(result) == len(points)

    def test_returns_tuples(self) -> None:
        em = _make_edge_map()
        points = [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0)]
        result = snap_closed_polygon(points, em)
        for pt in result:
            assert isinstance(pt, tuple)
            assert len(pt) == 2

    def test_empty_points(self) -> None:
        em = _make_edge_map()
        assert snap_closed_polygon([], em) == []

    def test_too_few_points(self) -> None:
        em = _make_edge_map()
        points = [(10.0, 10.0), (20.0, 20.0)]
        assert snap_closed_polygon(points, em) == points

    def test_with_config(self) -> None:
        em = _make_edge_map()
        cfg = EdgeSnapConfig(search_radius_px=5.0, min_edge_strength=0.0)
        points = [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)]
        result = snap_closed_polygon(points, em, config=cfg)
        assert len(result) == len(points)
