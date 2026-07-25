"""Extended unit tests for SpeckleTrackingWorker."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers.speckle_worker import (
    SpeckleTrackingSignals,
    SpeckleTrackingWorker,
    _embed_window_curve,
)
from echo_personal_tool.domain.models.speckle import (
    MyocardialZone,
    SpeckleConfig,
    StrainResult,
    TrackingKernel,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _make_zone(n_points=16):
    angles = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    endo = np.column_stack([16 + 5 * np.cos(angles), 16 + 5 * np.sin(angles)])
    epi = np.column_stack([16 + 8 * np.cos(angles), 16 + 8 * np.sin(angles)])
    return MyocardialZone(
        endo_points=endo,
        epi_points=epi,
        thickness_mm=8.0,
        pixel_spacing=(0.5, 0.5),
    )


def _make_frames(n=10, h=32, w=32):
    return np.random.randint(0, 256, (n, h, w), dtype=np.uint8)


# ── _embed_window_curve edge cases ─────────────────────────────────


class TestEmbedWindowCurveExtended:
    def test_phase_start_equals_end(self):
        curve = np.array([42.0])
        result = _embed_window_curve(curve, n_frames=5, phase_start=2, phase_end=2)
        assert result.shape == (5,)
        assert result[2] == 42.0
        assert np.isnan(result[0])
        assert np.isnan(result[4])

    def test_curve_fills_entire_window(self):
        curve = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _embed_window_curve(curve, n_frames=5, phase_start=0, phase_end=4)
        np.testing.assert_array_equal(result, curve)

    def test_all_nan_outside_window(self):
        """Points outside [phase_start, phase_end] should be NaN."""
        curve = np.array([10.0, 20.0])
        result = _embed_window_curve(curve, n_frames=6, phase_start=2, phase_end=3)
        assert result.shape == (6,)
        assert np.isnan(result[0])
        assert np.isnan(result[1])
        assert result[2] == 10.0
        assert result[3] == 20.0
        assert np.isnan(result[4])
        assert np.isnan(result[5])


# ── Signals ────────────────────────────────────────────────────────


class TestSpeckleTrackingSignalsExtended:
    def test_progress_signal_exists(self):
        signals = SpeckleTrackingSignals()
        assert hasattr(signals, "progress")


# ── Worker construction with various configs ───────────────────────


class TestSpeckleTrackingWorkerExtended:
    def test_init_with_custom_config(self):
        config = SpeckleConfig(
            kernel_size=16,
            search_radius=10,
            ncc_threshold=0.5,
            tracking_mode="incremental",
        )
        frames = _make_frames()
        zone = _make_zone()
        worker = SpeckleTrackingWorker(
            frames=frames,
            zone=zone,
            pixel_spacing=(0.5, 0.5),
            config=config,
        )
        assert worker._config.kernel_size == 16
        assert worker._config_preset == "standard"

    def test_init_with_manual_ed_es(self):
        frames = _make_frames()
        zone = _make_zone()
        worker = SpeckleTrackingWorker(
            frames=frames,
            zone=zone,
            pixel_spacing=(0.5, 0.5),
            manual_ed=0,
            manual_es=5,
        )
        assert worker._manual_ed == 0
        assert worker._manual_es == 5

    def test_init_with_config_preset(self):
        frames = _make_frames()
        zone = _make_zone()
        worker = SpeckleTrackingWorker(
            frames=frames,
            zone=zone,
            pixel_spacing=(0.5, 0.5),
            config_preset="high_quality",
        )
        assert worker._config_preset == "high_quality"


# ── run – exception path ──────────────────────────────────────────


class TestSpeckleTrackingWorkerRun:
    @patch("echo_personal_tool.application.workers.speckle_worker.sample_kernels_in_zone")
    def test_run_exception_emits_error(self, mock_kernels):
        mock_kernels.side_effect = RuntimeError("kernel error")

        frames = _make_frames()
        zone = _make_zone()
        worker = SpeckleTrackingWorker(
            frames=frames,
            zone=zone,
            pixel_spacing=(0.5, 0.5),
            frame_time_ms=33.3,
            manual_ed=0,
            manual_es=5,
        )
        errors = []
        worker.signals.error.connect(lambda msg: errors.append(msg))
        worker.run()

        assert len(errors) == 1
        assert "kernel error" in errors[0]

    @patch("echo_personal_tool.application.workers.speckle_worker.assign_aha_segments")
    @patch("echo_personal_tool.application.workers.speckle_worker.sample_kernels_in_zone")
    def test_run_with_manual_ed_es(self, mock_kernels, mock_assign):
        mock_kernels.return_value = [
            TrackingKernel(center=(10.0, 10.0), radius=4, node_index=0, layer="endo"),
            TrackingKernel(center=(15.0, 15.0), radius=4, node_index=1, layer="epi"),
        ]
        mock_assign.return_value = [
            TrackingKernel(center=(10.0, 10.0), radius=4, node_index=0, layer="endo"),
            TrackingKernel(center=(15.0, 15.0), radius=4, node_index=1, layer="epi"),
        ]

        frames = _make_frames(n=10)
        zone = _make_zone()
        n_kernels = 2

        patches = {
            "detect_ed_es_from_frames": MagicMock(return_value=(0, 5)),
            "track_cine_incremental": MagicMock(return_value=[MagicMock(displacements=np.zeros((6, n_kernels, 2)))]),
            "preprocess_echo_frame": MagicMock(return_value=np.zeros((32, 32), dtype=np.uint8)),
            "build_zone_mask": MagicMock(return_value=np.ones((32, 32), dtype=bool)),
            "extract_trajectories": MagicMock(
                return_value=(
                    np.full((6, n_kernels, 2), 10.0),
                    np.full((6, n_kernels), 0.9),
                )
            ),
            "interpolate_invalid_kernels": MagicMock(return_value=np.full((6, n_kernels, 2), 10.0)),
            "smooth_trajectories": MagicMock(return_value=np.full((6, n_kernels, 2), 10.0)),
            "apply_motion_model": MagicMock(return_value=np.full((6, n_kernels, 2), 10.0)),
            "compute_weighted_longitudinal_strain_gl": MagicMock(
                return_value=np.array([0.0, -5.0, -10.0, -5.0, 0.0, 0.0])
            ),
            "compute_weighted_radial_strain_gl": MagicMock(return_value=np.array([0.0, 2.0, 5.0, 2.0, 0.0, 0.0])),
            "compute_strain_rate": MagicMock(return_value=np.zeros(10)),
            "estimate_heart_rate_fft": MagicMock(return_value=72.0),
            "build_myocardial_roi_mask": MagicMock(return_value=np.ones((32, 32), dtype=bool)),
            "compute_gls": MagicMock(return_value=-15.0),
            "apply_drift_compensation": MagicMock(return_value=np.array([0.0, -5.0, -10.0, -5.0, 0.0, 0.0])),
            "compute_aha_segment_strain": MagicMock(return_value=({1: -15.0}, {1: 0.8})),
        }

        with (
            patch(
                "echo_personal_tool.application.workers.speckle_worker.detect_ed_es_from_frames",
                patches["detect_ed_es_from_frames"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.track_cine_incremental",
                patches["track_cine_incremental"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.preprocess_echo_frame",
                patches["preprocess_echo_frame"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.build_zone_mask",
                patches["build_zone_mask"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.extract_trajectories",
                patches["extract_trajectories"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.interpolate_invalid_kernels",
                patches["interpolate_invalid_kernels"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.smooth_trajectories",
                patches["smooth_trajectories"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.apply_motion_model",
                patches["apply_motion_model"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.compute_weighted_longitudinal_strain_gl",
                patches["compute_weighted_longitudinal_strain_gl"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.compute_weighted_radial_strain_gl",
                patches["compute_weighted_radial_strain_gl"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.compute_strain_rate",
                patches["compute_strain_rate"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.estimate_heart_rate_fft",
                patches["estimate_heart_rate_fft"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.build_myocardial_roi_mask",
                patches["build_myocardial_roi_mask"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.compute_gls",
                patches["compute_gls"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.apply_drift_compensation",
                patches["apply_drift_compensation"],
            ),
            patch(
                "echo_personal_tool.application.workers.speckle_worker.compute_aha_segment_strain",
                patches["compute_aha_segment_strain"],
            ),
        ):
            worker = SpeckleTrackingWorker(
                frames=frames,
                zone=zone,
                pixel_spacing=(0.5, 0.5),
                frame_time_ms=33.3,
                manual_ed=0,
                manual_es=5,
            )
            finished = []
            worker.signals.finished.connect(lambda r: finished.append(r))
            worker.run()

            assert len(finished) == 1
            assert isinstance(finished[0], StrainResult)


# ── _dump_ste_debug ───────────────────────────────────────────────


class TestDumpSteDebug:
    def test_creates_debug_json(self, tmp_path):
        with patch(
            "echo_personal_tool.application.workers.speckle_worker.Path.home",
            return_value=tmp_path,
        ):
            frames = _make_frames()
            zone = _make_zone()
            worker = SpeckleTrackingWorker(
                frames=frames,
                zone=zone,
                pixel_spacing=(0.5, 0.5),
            )

            n_frames, h, w = frames.shape
            n_kernels = 4
            angles = np.linspace(0, 2 * np.pi, n_kernels, endpoint=False)
            kernels = [
                TrackingKernel(
                    center=(
                        float(16 + 5 * np.cos(a)),
                        float(16 + 5 * np.sin(a)),
                    ),
                    radius=4,
                    node_index=i,
                    layer="endo" if i < 2 else "epi",
                )
                for i, a in enumerate(angles)
            ]
            smoothed = np.full((n_frames, n_kernels, 2), 16.0)
            ncc_matrix = np.full((n_frames, n_kernels), 0.9)
            longitudinal = np.full(n_frames, -10.0)

            worker._dump_ste_debug(
                smoothed=smoothed,
                ncc_matrix=ncc_matrix,
                kernels=kernels,
                ed_contour=smoothed[0],
                es_contour=smoothed[5],
                endo_indices=[0, 1],
                epi_indices=[2, 3],
                longitudinal=longitudinal,
                radial=np.full(n_frames, 5.0),
                gls=-10.0,
                global_ed=0,
                global_es=5,
                phase_start=0,
                phase_end=5,
                pixel_spacing=(0.5, 0.5),
                config=SpeckleConfig(),
            )

            debug_dir = tmp_path / "ECHO2026_ste_debug"
            assert debug_dir.exists()
            json_files = list(debug_dir.glob("ste_*.json"))
            assert len(json_files) == 1

            with open(json_files[0]) as f:
                data = json.load(f)
            assert data["gls_pct"] == -10.0
            assert data["ed_frame"] == 0
            assert data["es_frame"] == 5
            assert len(data["kernels"]) == n_kernels
