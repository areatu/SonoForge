"""Unit tests for speckle tracking domain models."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    SpeckleConfig,
    StrainResult,
    TrackingKernel,
    TrackingResult,
)


# ── TrackingKernel ─────────────────────────────────────────────────


class TestTrackingKernel:
    def test_defaults(self) -> None:
        k = TrackingKernel(center=(10.0, 20.0))
        assert k.center == (10.0, 20.0)
        assert k.radius == 10
        assert k.node_index == 0
        assert k.layer == "endo"
        assert k.aha_segment == 0
        assert k.arc_length_param == 0.0

    def test_custom(self) -> None:
        k = TrackingKernel(
            center=(50.0, 60.0), radius=15, node_index=5,
            layer="epi", aha_segment=3, arc_length_param=0.75,
        )
        assert k.radius == 15
        assert k.layer == "epi"
        assert k.aha_segment == 3

    def test_frozen(self) -> None:
        k = TrackingKernel(center=(0.0, 0.0))
        with pytest.raises(dataclasses.FrozenInstanceError):
            k.radius = 20  # type: ignore[misc]


# ── MyocardialZone ─────────────────────────────────────────────────


class TestMyocardialZone:
    def test_creation(self) -> None:
        endo = np.array([[10, 20], [30, 40], [50, 60]], dtype=np.float64)
        epi = np.array([[12, 22], [32, 42], [52, 62]], dtype=np.float64)
        zone = MyocardialZone(
            endo_points=endo, epi_points=epi,
            thickness_mm=8.0, pixel_spacing=(0.5, 0.5),
        )
        assert zone.thickness_mm == 8.0
        assert zone.pixel_spacing == (0.5, 0.5)
        assert zone.endo_points.shape == (3, 2)
        assert zone.epi_points.shape == (3, 2)

    def test_copies_arrays(self) -> None:
        endo = np.array([[1, 2]], dtype=np.float64)
        epi = np.array([[3, 4]], dtype=np.float64)
        zone = MyocardialZone(
            endo_points=endo, epi_points=epi,
            thickness_mm=5.0, pixel_spacing=(1.0, 1.0),
        )
        # Mutating original should not affect zone
        endo[0, 0] = 999
        assert zone.endo_points[0, 0] == 1.0

    def test_frozen(self) -> None:
        zone = MyocardialZone(
            endo_points=np.zeros((2, 2)), epi_points=np.zeros((2, 2)),
            thickness_mm=5.0, pixel_spacing=(1.0, 1.0),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            zone.thickness_mm = 10.0  # type: ignore[misc]


# ── TrackingResult ─────────────────────────────────────────────────


class TestTrackingResult:
    def test_creation(self) -> None:
        n = 5
        result = TrackingResult(
            frame_index=3,
            displacements=np.zeros((n, 2)),
            ncc_scores=np.ones(n),
            valid_mask=np.ones(n, dtype=bool),
            kernel_positions=np.zeros((n, 2)),
        )
        assert result.frame_index == 3
        assert result.reference_frame == 0
        assert result.displacements.shape == (5, 2)

    def test_not_frozen(self) -> None:
        """TrackingResult is mutable (unfrozen dataclass)."""
        result = TrackingResult(
            frame_index=0,
            displacements=np.zeros((1, 2)),
            ncc_scores=np.ones(1),
            valid_mask=np.ones(1, dtype=bool),
            kernel_positions=np.zeros((1, 2)),
        )
        result.frame_index = 5
        assert result.frame_index == 5


# ── SpeckleConfig ──────────────────────────────────────────────────


class TestSpeckleConfig:
    def test_defaults(self) -> None:
        cfg = SpeckleConfig()
        assert cfg.kernel_size == 12
        assert cfg.search_radius == 8
        assert cfg.pyramid_levels == 2
        assert cfg.ncc_threshold == 0.3
        assert cfg.tracking_mode == "incremental"
        assert cfg.bidirectional is True
        assert cfg.drift_compensation is True

    def test_preset_standard(self) -> None:
        cfg = SpeckleConfig.preset_standard()
        assert cfg.kernel_size == 12
        assert cfg.search_radius == 8
        assert cfg.bidirectional is True
        assert cfg.drift_compensation is True
        assert cfg.tracking_mode == "incremental"
        assert cfg.ncc_threshold == 0.3

    def test_preset_research(self) -> None:
        cfg = SpeckleConfig.preset_research()
        assert cfg.kernel_size == 18
        assert cfg.search_radius == 18
        assert cfg.spatial_smoothing == 1.2
        assert cfg.temporal_smoothing == 1.1

    def test_preset_debug(self) -> None:
        cfg = SpeckleConfig.preset_debug()
        assert cfg.bidirectional is False
        assert cfg.spatial_smoothing == 0.0
        assert cfg.temporal_smoothing == 0.0
        assert cfg.drift_compensation is False

    def test_frozen(self) -> None:
        cfg = SpeckleConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.kernel_size = 24  # type: ignore[misc]


# ── StrainResult ───────────────────────────────────────────────────


class TestStrainResult:
    def test_minimal(self) -> None:
        result = StrainResult(
            longitudinal=np.array([-0.2, -0.15]),
            radial=np.array([0.1, 0.12]),
            gls=-0.18,
        )
        assert result.gls == -0.18
        assert result.ed_index == 0
        assert result.es_index == 0
        assert result.heart_rate_bpm == 0.0
        assert result.phases == {}
        assert result.zone is None
        assert result.kernels == []

    def test_populated(self) -> None:
        kernel = TrackingKernel(center=(10.0, 20.0))
        zone = MyocardialZone(
            endo_points=np.zeros((3, 2)),
            epi_points=np.ones((3, 2)),
            thickness_mm=8.0, pixel_spacing=(0.5, 0.5),
        )
        result = StrainResult(
            longitudinal=np.array([-0.2]),
            radial=np.array([0.1]),
            gls=-0.2,
            strain_rate=np.array([-1.0]),
            ed_index=0,
            es_index=10,
            heart_rate_bpm=72.0,
            phases={"ED": 0, "ES": 10},
            zone=zone,
            kernels=[kernel],
            segment_strain={1: -0.20, 2: -0.18},
            segment_quality={1: 0.9, 2: 0.85},
            drift_compensation_applied=True,
            tracking_quality_mean=0.87,
            cycle_count=2,
            config_preset="research",
            kernels_accepted_count=10,
            kernels_rejected_count=2,
            kernels_total_count=12,
        )
        assert result.heart_rate_bpm == 72.0
        assert result.phases["ES"] == 10
        assert result.zone is zone
        assert len(result.kernels) == 1
        assert result.segment_strain[1] == -0.20
        assert result.drift_compensation_applied is True
        assert result.kernels_total_count == 12
