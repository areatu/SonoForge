"""Unit tests for temporal fusion domain models."""

from __future__ import annotations

import dataclasses

import pytest

from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.temporal_fusion import (
    TemporalFusionConfig,
    TemporalFusionResult,
)


class TestTemporalFusionConfig:
    def test_defaults(self) -> None:
        cfg = TemporalFusionConfig()
        assert cfg.window == 2
        assert cfg.vote_threshold == 3
        assert cfg.max_node_shift_ratio_ed == 0.03
        assert cfg.max_node_shift_ratio_es == 0.025
        assert cfg.apex_max_shift_ratio_ed == 0.02
        assert cfg.apex_max_shift_ratio_es == 0.015
        assert cfg.annulus_max_shift_ratio_ed == 0.015
        assert cfg.annulus_max_shift_ratio_es == 0.012
        assert cfg.apex_direction_lock is True
        assert cfg.confidence_weighted is True
        assert cfg.outlier_rejection is True
        assert cfg.max_neighbor_shift_ratio == 0.15
        assert cfg.min_confidence_score == 0.3

    def test_max_node_shift_ratio_ed(self) -> None:
        cfg = TemporalFusionConfig()
        assert cfg.max_node_shift_ratio("ED") == 0.03

    def test_max_node_shift_ratio_es(self) -> None:
        cfg = TemporalFusionConfig()
        assert cfg.max_node_shift_ratio("ES") == 0.025

    def test_apex_max_shift_ratio_ed(self) -> None:
        cfg = TemporalFusionConfig()
        assert cfg.apex_max_shift_ratio("ED") == 0.02

    def test_apex_max_shift_ratio_es(self) -> None:
        cfg = TemporalFusionConfig()
        assert cfg.apex_max_shift_ratio("ES") == 0.015

    def test_annulus_max_shift_ratio_ed(self) -> None:
        cfg = TemporalFusionConfig()
        assert cfg.annulus_max_shift_ratio("ED") == 0.015

    def test_annulus_max_shift_ratio_es(self) -> None:
        cfg = TemporalFusionConfig()
        assert cfg.annulus_max_shift_ratio("ES") == 0.012

    def test_custom_values(self) -> None:
        cfg = TemporalFusionConfig(
            window=4, vote_threshold=5,
            max_node_shift_ratio_ed=0.05, max_node_shift_ratio_es=0.04,
        )
        assert cfg.window == 4
        assert cfg.max_node_shift_ratio("ED") == 0.05
        assert cfg.max_node_shift_ratio("ES") == 0.04

    def test_frozen(self) -> None:
        cfg = TemporalFusionConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.window = 10  # type: ignore[misc]


class TestTemporalFusionResult:
    def test_creation(self) -> None:
        anchor = Contour(phase="ED", points=[(10.0, 20.0), (30.0, 40.0)])
        center = Contour(phase="ED", points=[(11.0, 21.0), (31.0, 41.0)])
        result = TemporalFusionResult(
            anchor_frame_index=5,
            fused_contour=anchor,
            center_contour=center,
        )
        assert result.anchor_frame_index == 5
        assert result.fused_contour is anchor
        assert result.center_contour is center
        assert result.neighbor_contours == {}
        assert result.frames_used == 0
        assert result.frames_requested == 0
        assert isinstance(result.config, TemporalFusionConfig)

    def test_with_neighbors(self) -> None:
        anchor = Contour(phase="ED")
        center = Contour(phase="ED")
        n1 = Contour(phase="ED", points=[(1.0, 2.0)])
        n2 = Contour(phase="ED", points=[(3.0, 4.0)])
        cfg = TemporalFusionConfig(window=3)
        result = TemporalFusionResult(
            anchor_frame_index=10,
            fused_contour=anchor,
            center_contour=center,
            neighbor_contours={8: n1, 12: n2},
            frames_used=3,
            frames_requested=5,
            config=cfg,
        )
        assert len(result.neighbor_contours) == 2
        assert 8 in result.neighbor_contours
        assert result.frames_used == 3
        assert result.config.window == 3

    def test_not_frozen(self) -> None:
        """TemporalFusionResult is mutable (non-frozen dataclass)."""
        anchor = Contour(phase="ED")
        center = Contour(phase="ED")
        result = TemporalFusionResult(
            anchor_frame_index=0,
            fused_contour=anchor,
            center_contour=center,
        )
        result.frames_used = 5
        assert result.frames_used == 5
