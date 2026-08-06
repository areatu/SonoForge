"""Tests for temporal fusion v2 (confidence weighting, outlier rejection)."""

from __future__ import annotations

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.temporal_fusion import TemporalFusionConfig
from echo_personal_tool.domain.services.lv_temporal_fusion import (
    compute_neighbor_confidence,
    reject_outlier_neighbors,
)


def _make_contour(
    *,
    ma: tuple[tuple[float, float], tuple[float, float]] = ((0, 0), (20, 0)),
    apex: tuple[float, float] = (10, 30),
    points: list[tuple[float, float]] | None = None,
) -> Contour:
    if points is None:
        points = [(0, 0), (5, 15), (10, 30), (15, 15), (20, 0)]
    return Contour(
        phase="ED",
        view="A4C",
        chamber="LV",
        points=points,
        mitral_annulus=ma,
        apex_landmark=apex,
    )


class TestComputeNeighborConfidence:
    def test_identical_contours(self) -> None:
        c = _make_contour()
        score = compute_neighbor_confidence(c, c, phase="ED")
        assert score == 1.0

    def test_similar_contours(self) -> None:
        anchor = _make_contour(ma=((0, 0), (20, 0)))
        neighbor = _make_contour(ma=((1, 0), (21, 0)))  # 1px shift
        score = compute_neighbor_confidence(anchor, neighbor, phase="ED")
        assert score > 0.8

    def test_different_contours(self) -> None:
        anchor = _make_contour(ma=((0, 0), (20, 0)))
        neighbor = _make_contour(ma=((10, 10), (30, 10)))  # large shift
        score = compute_neighbor_confidence(anchor, neighbor, phase="ED")
        assert score < 0.5

    def test_no_annulus(self) -> None:
        anchor = _make_contour()
        neighbor = _make_contour(ma=None)
        score = compute_neighbor_confidence(anchor, neighbor, phase="ED")
        assert score == 0.0


class TestRejectOutlierNeighbors:
    def test_keeps_similar_neighbors(self) -> None:
        anchor = _make_contour(ma=((0, 0), (20, 0)))
        n1 = _make_contour(ma=((1, 0), (21, 0)))
        result = reject_outlier_neighbors(anchor, {0: n1}, max_shift_ratio=0.15)
        assert 0 in result

    def test_removes_distant_neighbors(self) -> None:
        anchor = _make_contour(ma=((0, 0), (20, 0)))
        # MA length = 20, max_shift = 0.15 * 20 = 3px
        n1 = _make_contour(ma=((5, 0), (25, 0)))  # 5px shift > 3px
        result = reject_outlier_neighbors(anchor, {0: n1}, max_shift_ratio=0.15)
        assert 0 not in result

    def test_removes_neighbor_with_no_annulus(self) -> None:
        anchor = _make_contour()
        n1 = _make_contour(ma=None)
        result = reject_outlier_neighbors(anchor, {0: n1}, max_shift_ratio=0.15)
        assert 0 not in result

    def test_empty_input(self) -> None:
        anchor = _make_contour()
        result = reject_outlier_neighbors(anchor, {}, max_shift_ratio=0.15)
        assert result == {}


class TestTemporalFusionConfig:
    def test_new_fields_default(self) -> None:
        config = TemporalFusionConfig()
        assert config.confidence_weighted is True
        assert config.outlier_rejection is True
        assert config.max_neighbor_shift_ratio == 0.15
        assert config.min_confidence_score == 0.3

    def test_backward_compat(self) -> None:
        """Old manifest without new fields should still work."""
        config = TemporalFusionConfig(
            window=2,
            vote_threshold=3,
            apex_direction_lock=True,
        )
        assert config.confidence_weighted is True  # default
        assert config.outlier_rejection is True  # default
