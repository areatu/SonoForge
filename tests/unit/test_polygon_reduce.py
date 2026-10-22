"""Tests for polygon_reduce (Douglas-Peucker point reduction)."""

from __future__ import annotations

from echo_personal_tool.domain.services.polygon_reduce import reduce_polygon_points


class TestReducePolygonPoints:
    def test_empty_list(self) -> None:
        assert reduce_polygon_points([]) == []

    def test_single_point(self) -> None:
        assert reduce_polygon_points([(1.0, 2.0)]) == [(1.0, 2.0)]

    def test_two_points(self) -> None:
        assert reduce_polygon_points([(0.0, 0.0), (10.0, 10.0)]) == [(0.0, 0.0), (10.0, 10.0)]

    def test_collinear_points_reduced(self) -> None:
        points = [(0.0, 0.0), (5.0, 5.0), (10.0, 10.0), (15.0, 15.0)]
        result = reduce_polygon_points(points, epsilon=1.0)
        assert len(result) < len(points)
        assert result[0] == (0.0, 0.0)
        assert result[-1] == (15.0, 15.0)

    def test_corner_preserved(self) -> None:
        points = [(0.0, 0.0), (5.0, 0.1), (10.0, 0.0), (10.0, 10.0)]
        result = reduce_polygon_points(points, epsilon=1.0)
        assert (10.0, 10.0) in result
        assert (0.0, 0.0) in result

    def test_closed_polygon_preserves_first_last(self) -> None:
        points = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        result = reduce_polygon_points(points, epsilon=1.0, closed=True)
        assert result[0] == result[-1]

    def test_epsilon_zero_no_reduction(self) -> None:
        points = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
        result = reduce_polygon_points(points, epsilon=0.0)
        assert len(result) == len(points)

    def test_large_epsilon_minimal_points(self) -> None:
        points = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0), (10.0, 10.0)]
        result = reduce_polygon_points(points, epsilon=5.0)
        assert len(result) <= 3
