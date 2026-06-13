"""Unit tests for open-arc contour geometry."""

from __future__ import annotations

import math

import numpy as np
import pytest

from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    apex_point,
    long_axis_endpoints,
    move_node_and_resample,
    polygon_area_mm2,
    resample_open_arc,
    sample_spline,
)


def _semicircle_arc(num: int = 5) -> list[tuple[float, float]]:
    """Open arc: (0,0) septal → semicircle → (10,0) lateral."""
    angles = np.linspace(math.pi, 0.0, num)
    return [(5.0 + 5.0 * math.cos(a), 5.0 * math.sin(a)) for a in angles]



def test_resample_open_arc_preserves_endpoints_and_count() -> None:
    arc = _semicircle_arc(4)
    result = resample_open_arc(arc, num_nodes=8)
    assert len(result) == 8
    assert result[0] == pytest.approx(arc[0], abs=1e-3)
    assert result[-1] == pytest.approx(arc[-1], abs=1e-3)


def test_resample_open_arc_equal_spacing() -> None:
    arc = _semicircle_arc(4)
    result = resample_open_arc(arc, num_nodes=9)
    seg_lens = [
        math.hypot(result[i + 1][0] - result[i][0], result[i + 1][1] - result[i][1])
        for i in range(len(result) - 1)
    ]
    assert max(seg_lens) - min(seg_lens) == pytest.approx(0.0, abs=0.5)


def test_move_node_and_resample_moves_interior_point() -> None:
    arc = resample_open_arc(_semicircle_arc(5), num_nodes=DEFAULT_NODE_COUNT)
    moved = move_node_and_resample(arc, node_index=DEFAULT_NODE_COUNT // 2, x=5.0, y=8.0)
    assert len(moved) == DEFAULT_NODE_COUNT
    mid = DEFAULT_NODE_COUNT // 2
    assert moved[mid][1] == pytest.approx(8.0, abs=0.5)


def test_apex_point_farthest_from_annulus() -> None:
    arc = _semicircle_arc(7)
    annulus = (arc[0], arc[-1])
    apex = apex_point(arc, annulus)
    assert apex[1] == pytest.approx(5.0, abs=0.2)


def test_long_axis_endpoints_mid_annulus_to_apex() -> None:
    arc = _semicircle_arc(7)
    annulus = (arc[0], arc[-1])
    base, tip = long_axis_endpoints(arc, annulus)
    assert base == pytest.approx((5.0, 0.0), abs=0.2)
    assert tip[1] > base[1]


def test_sample_spline_returns_dense_curve() -> None:
    arc = _semicircle_arc(5)
    dense = sample_spline(arc, num_samples=50)
    assert len(dense) == 50


def test_polygon_area_mm2_for_axis_aligned_rectangle() -> None:
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert polygon_area_mm2(square, (1.0, 1.0)) == pytest.approx(100.0)
