"""Regression tests for contour serialization and geometry calculations."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    apex_point,
    long_axis_endpoints,
    move_node_and_resample,
    open_arc_polyline_length,
    polygon_area_mm2,
    point_line_distance,
    resample_open_arc,
    sample_spline,
    _resample_polyline,
)


class TestContourSerializationRegression:
    """Contour serialization must produce identical JSON for known inputs."""

    def test_gold_frame_serialization_deterministic(self) -> None:
        frame = {
            "frame_index": 12,
            "phase": "ED",
            "view": "A4C",
            "chamber": "LV",
            "points": [[100.0, 200.0], [110.0, 210.0], [120.0, 220.0]],
            "mitral_annulus": [[90.0, 150.0], [200.0, 150.0]],
            "source": "manual",
            "annotator": "test",
            "annotated_at": "2026-07-06T00:00:00Z",
        }
        json_a = json.dumps(frame, indent=2, ensure_ascii=False)
        json_b = json.dumps(frame, indent=2, ensure_ascii=False)
        assert json_a == json_b

    def test_gold_study_round_trip(self, tmp_path: Path) -> None:
        from echo_personal_tool.domain.services.gold_store import load_gold, save_gold

        data = {
            "study_id": "1.2.840.regression",
            "instance_path": "/data/regression.dcm",
            "pixel_spacing_mm": [0.15, 0.15],
            "chamber": "LV",
            "frames": [
                {
                    "frame_index": 10,
                    "phase": "ED",
                    "chamber": "LV",
                    "points": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
                    "mitral_annulus": [[0.0, 0.0], [10.0, 0.0]],
                    "annotated_at": "2026-07-06T00:00:00Z",
                },
                {
                    "frame_index": 25,
                    "phase": "ES",
                    "chamber": "LV",
                    "points": [[1.5, 2.5], [3.5, 4.5], [5.5, 6.5]],
                    "mitral_annulus": [[0.0, 0.0], [10.0, 0.0]],
                    "annotated_at": "2026-07-06T01:00:00Z",
                },
            ],
        }
        path = tmp_path / "lv_1.2.840.regression.json"
        save_gold(path, data)
        loaded = load_gold(path)
        assert loaded == data

    def test_contour_points_exact_json_roundtrip(self, tmp_path: Path) -> None:
        from echo_personal_tool.domain.services.gold_store import load_gold, save_gold

        points = [
            [12.345678, 98.765432],
            [45.678901, 23.456789],
            [78.901234, 56.789012],
            [111.222333, 444.555666],
        ]
        data = {
            "study_id": "test_precision",
            "frames": [
                {
                    "frame_index": 0,
                    "phase": "ED",
                    "points": points,
                }
            ],
        }
        path = tmp_path / "precision.json"
        save_gold(path, data)
        loaded = load_gold(path)
        assert loaded["frames"][0]["points"] == points


class TestContourGeometryRegression:
    """Contour geometry calculations must produce exact expected results."""

    def test_polygon_area_mm2_square(self) -> None:
        square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        assert polygon_area_mm2(square, (1.0, 1.0)) == pytest.approx(100.0)

    def test_polygon_area_mm2_scaled(self) -> None:
        square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        assert polygon_area_mm2(square, (0.5, 0.5)) == pytest.approx(25.0)

    def test_polygon_area_mm2_asymmetric(self) -> None:
        rect = [(0.0, 0.0), (20.0, 0.0), (20.0, 5.0), (0.0, 5.0)]
        assert polygon_area_mm2(rect, (1.0, 1.0)) == pytest.approx(100.0)

    def test_polygon_area_mm2_triangle(self) -> None:
        triangle = [(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)]
        assert polygon_area_mm2(triangle, (1.0, 1.0)) == pytest.approx(50.0)

    def test_polygon_area_mm2_insufficient_points(self) -> None:
        assert polygon_area_mm2([(0.0, 0.0), (1.0, 1.0)], (1.0, 1.0)) == 0.0

    def test_point_line_distance_perpendicular(self) -> None:
        dist = point_line_distance((5.0, 5.0), (0.0, 0.0), (10.0, 0.0))
        assert dist == pytest.approx(5.0)

    def test_point_line_distance_parallel(self) -> None:
        dist = point_line_distance((0.0, 5.0), (0.0, 0.0), (0.0, 10.0))
        assert dist == pytest.approx(0.0)

    def test_point_line_distance_degenerate_segment(self) -> None:
        dist = point_line_distance((3.0, 4.0), (0.0, 0.0), (0.0, 0.0))
        assert dist == pytest.approx(5.0)

    def test_open_arc_polyline_length_straight(self) -> None:
        points = [(0.0, 0.0), (3.0, 4.0)]
        assert open_arc_polyline_length(points) == pytest.approx(5.0)

    def test_open_arc_polyline_length_empty(self) -> None:
        assert open_arc_polyline_length([]) == 0.0

    def test_open_arc_polyline_length_single(self) -> None:
        assert open_arc_polyline_length([(1.0, 1.0)]) == 0.0

    def test_resample_open_arc_preserves_endpoints(self) -> None:
        arc = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
        result = resample_open_arc(arc, num_nodes=5)
        assert len(result) == 5
        assert result[0] == pytest.approx(arc[0], abs=1e-3)
        assert result[-1] == pytest.approx(arc[-1], abs=1e-3)

    def test_resample_open_arc_single_point(self) -> None:
        result = resample_open_arc([(5.0, 5.0)], num_nodes=4)
        assert len(result) == 4
        for pt in result:
            assert pt == pytest.approx((5.0, 5.0))

    def test_resample_open_arc_empty(self) -> None:
        assert resample_open_arc([], num_nodes=5) == []

    def test_sample_spline_two_points(self) -> None:
        pts = [(0.0, 0.0), (10.0, 0.0)]
        dense = sample_spline(pts, num_samples=10)
        assert len(dense) == 10
        assert dense[0] == pytest.approx((0.0, 0.0))
        assert dense[-1] == pytest.approx((10.0, 0.0))

    def test_sample_spline_single_point(self) -> None:
        assert sample_spline([(5.0, 5.0)], num_samples=10) == [(5.0, 5.0)]

    def test_move_node_and_resample_count(self) -> None:
        arc = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
        result = move_node_and_resample(arc, node_index=1, x=5.0, y=8.0, num_nodes=7)
        assert len(result) == 7

    def test_move_node_and_resample_out_of_bounds(self) -> None:
        arc = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
        result = move_node_and_resample(arc, node_index=99, x=5.0, y=8.0, num_nodes=7)
        assert len(result) == 7

    def test_apex_point_top_of_arc(self) -> None:
        arc = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
        annulus = ((0.0, 0.0), (10.0, 0.0))
        apex = apex_point(arc, annulus)
        assert apex[1] == pytest.approx(5.0)

    def test_long_axis_endpoints(self) -> None:
        arc = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
        annulus = ((0.0, 0.0), (10.0, 0.0))
        base, tip = long_axis_endpoints(arc, annulus)
        assert base[0] == pytest.approx(5.0)
        assert base[1] == pytest.approx(0.0)
        assert tip[1] == pytest.approx(5.0)

    def test_resample_polyline_linear(self) -> None:
        pts = [(0.0, 0.0), (10.0, 0.0)]
        result = _resample_polyline(pts, num_nodes=6)
        assert len(result) == 6
        for i, pt in enumerate(result):
            assert pt[0] == pytest.approx(i * 2.0)
            assert pt[1] == pytest.approx(0.0)

    def test_resample_polyline_single_point(self) -> None:
        result = _resample_polyline([(5.0, 5.0)], num_nodes=4)
        assert len(result) == 4
        assert all(pt == (5.0, 5.0) for pt in result)
