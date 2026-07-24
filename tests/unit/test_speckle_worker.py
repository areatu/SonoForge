"""Unit tests for SpeckleTrackingWorker (_embed_window_curve and signals)."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker, _embed_window_curve
from echo_personal_tool.domain.models.speckle import MyocardialZone


def _make_zone() -> MyocardialZone:
    angles = np.linspace(0, 2 * np.pi, 32, endpoint=False)
    endo = np.column_stack([50 + 20 * np.cos(angles), 50 + 20 * np.sin(angles)])
    epi = np.column_stack([50 + 30 * np.cos(angles), 50 + 30 * np.sin(angles)])
    return MyocardialZone(
        endo_points=endo, epi_points=epi,
        thickness_mm=8.0, pixel_spacing=(0.5, 0.5),
    )


class TestEmbedWindowCurve:
    def test_exact_length(self) -> None:
        curve = np.array([1.0, 2.0, 3.0])
        result = _embed_window_curve(curve, n_frames=10, phase_start=2, phase_end=4)
        assert result.shape == (10,)
        assert result[2] == 1.0
        assert result[3] == 2.0
        assert result[4] == 3.0
        assert np.isnan(result[0])
        assert np.isnan(result[5])

    def test_shorter_curve(self) -> None:
        curve = np.array([10.0, 20.0])
        result = _embed_window_curve(curve, n_frames=10, phase_start=3, phase_end=6)
        assert result.shape == (10,)
        assert result[3] == 10.0
        assert result[4] == 20.0
        assert np.isnan(result[5])

    def test_longer_curve(self) -> None:
        curve = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _embed_window_curve(curve, n_frames=10, phase_start=2, phase_end=3)
        assert result.shape == (10,)
        # Only 2 slots available, first 2 copied
        assert result[2] == 1.0
        assert result[3] == 2.0

    def test_empty_curve(self) -> None:
        curve = np.array([])
        result = _embed_window_curve(curve, n_frames=5, phase_start=1, phase_end=3)
        assert result.shape == (5,)
        assert all(np.isnan(result))

    def test_full_frame_range(self) -> None:
        curve = np.array([10.0, 20.0, 30.0])
        result = _embed_window_curve(curve, n_frames=3, phase_start=0, phase_end=2)
        np.testing.assert_array_equal(result, curve)


class TestSpeckleTrackingWorker:
    def test_instantiation(self) -> None:
        frames = np.zeros((20, 64, 64), dtype=np.uint8)
        zone = _make_zone()
        worker = SpeckleTrackingWorker(
            frames=frames, zone=zone, pixel_spacing=(0.5, 0.5),
        )
        assert worker._frames.shape == (20, 64, 64)
        assert worker._pixel_spacing == (0.5, 0.5)

    def test_has_signals(self) -> None:
        frames = np.zeros((10, 32, 32), dtype=np.uint8)
        zone = _make_zone()
        worker = SpeckleTrackingWorker(
            frames=frames, zone=zone, pixel_spacing=(0.5, 0.5),
        )
        assert hasattr(worker.signals, "finished")
        assert hasattr(worker.signals, "error")
        assert hasattr(worker.signals, "progress")

    def test_auto_delete(self) -> None:
        frames = np.zeros((10, 32, 32), dtype=np.uint8)
        zone = _make_zone()
        worker = SpeckleTrackingWorker(
            frames=frames, zone=zone, pixel_spacing=(0.5, 0.5),
        )
        assert worker.autoDelete() is True

    def test_with_manual_ed_es(self) -> None:
        frames = np.zeros((10, 32, 32), dtype=np.uint8)
        zone = _make_zone()
        worker = SpeckleTrackingWorker(
            frames=frames, zone=zone, pixel_spacing=(0.5, 0.5),
            manual_ed=2, manual_es=7,
        )
        assert worker._manual_ed == 2
        assert worker._manual_es == 7

    def test_with_custom_config(self) -> None:
        from echo_personal_tool.domain.models.speckle import SpeckleConfig
        frames = np.zeros((10, 32, 32), dtype=np.uint8)
        zone = _make_zone()
        cfg = SpeckleConfig.preset_research()
        worker = SpeckleTrackingWorker(
            frames=frames, zone=zone, pixel_spacing=(0.5, 0.5),
            config=cfg,
        )
        assert worker._config is cfg
