"""Temporal fusion data models for LV Auto neighbor-aware contour."""

from __future__ import annotations

from dataclasses import dataclass, field

from echo_personal_tool.domain.models.contour import Contour


@dataclass(frozen=True)
class TemporalFusionConfig:
    """Configuration for temporal fusion (from manifest)."""

    window: int = 2
    vote_threshold: int = 3
    max_node_shift_ratio_ed: float = 0.03
    max_node_shift_ratio_es: float = 0.025
    apex_max_shift_ratio_ed: float = 0.02
    apex_max_shift_ratio_es: float = 0.015
    annulus_max_shift_ratio_ed: float = 0.015
    annulus_max_shift_ratio_es: float = 0.012
    apex_direction_lock: bool = True
    confidence_weighted: bool = True
    outlier_rejection: bool = True
    max_neighbor_shift_ratio: float = 0.15
    min_confidence_score: float = 0.3

    def max_node_shift_ratio(self, phase: str) -> float:
        return self.max_node_shift_ratio_es if phase == "ES" else self.max_node_shift_ratio_ed

    def apex_max_shift_ratio(self, phase: str) -> float:
        return self.apex_max_shift_ratio_es if phase == "ES" else self.apex_max_shift_ratio_ed

    def annulus_max_shift_ratio(self, phase: str) -> float:
        return self.annulus_max_shift_ratio_es if phase == "ES" else self.annulus_max_shift_ratio_ed


@dataclass
class TemporalFusionResult:
    """Result of temporal fusion on anchor frame N."""

    anchor_frame_index: int
    fused_contour: Contour
    center_contour: Contour
    neighbor_contours: dict[int, Contour] = field(default_factory=dict)
    frames_used: int = 0
    frames_requested: int = 0
    config: TemporalFusionConfig = field(default_factory=TemporalFusionConfig)
