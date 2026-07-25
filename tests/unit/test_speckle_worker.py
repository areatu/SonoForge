"""Unit tests for SpeckleTrackingWorker and _embed_window_curve."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.application.workers.speckle_worker import (
    SpeckleTrackingSignals,
    SpeckleTrackingWorker,
    _embed_window_curve,
)


class TestEmbedWindowCurve:
    def test_exact_length(self) -> None:
        curve = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _embed_window_curve(curve, n_frames=10, phase_start=2, phase_end=6)
        assert result.shape == (10,)
        assert result[2] == 1.0
        assert result[6] == 5.0
        assert np.isnan(result[0])
        assert np.isnan(result[7])

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


class TestSpeckleTrackingSignals:
    def test_has_signals(self) -> None:
        signals = SpeckleTrackingSignals()
        assert hasattr(signals, "finished")
        assert hasattr(signals, "error")
        assert hasattr(signals, "progress")


class TestSpeckleTrackingWorker:
    def test_creation(self) -> None:
        from echo_personal_tool.domain.models.speckle import MyocardialZone

        frames = np.zeros((10, 32, 32), dtype=np.uint8)
        angles = np.linspace(0, 2 * np.pi, 16, endpoint=False)
        endo = np.column_stack([16 + 5 * np.cos(angles), 16 + 5 * np.sin(angles)])
        epi = np.column_stack([16 + 8 * np.cos(angles), 16 + 8 * np.sin(angles)])
        zone = MyocardialZone(
            endo_points=endo, epi_points=epi,
            thickness_mm=8.0, pixel_spacing=(0.5, 0.5),
        )

        worker = SpeckleTrackingWorker(
            frames=frames,
            zone=zone,
            pixel_spacing=(0.5, 0.5),
        )
        assert worker._frames.shape == (10, 32, 32)
        assert worker._pixel_spacing == (0.5, 0.5)
        assert worker._ecg_waveform is None

    def test_with_ecg_waveform(self) -> None:
        from echo_personal_tool.domain.models.ecg import EcgLead, EcgWaveform
        from echo_personal_tool.domain.models.speckle import MyocardialZone

        frames = np.zeros((10, 32, 32), dtype=np.uint8)
        angles = np.linspace(0, 2 * np.pi, 16, endpoint=False)
        endo = np.column_stack([16 + 5 * np.cos(angles), 16 + 5 * np.sin(angles)])
        epi = np.column_stack([16 + 8 * np.cos(angles), 16 + 8 * np.sin(angles)])
        zone = MyocardialZone(
            endo_points=endo, epi_points=epi,
            thickness_mm=8.0, pixel_spacing=(0.5, 0.5),
        )

        lead = EcgLead("II", np.zeros(100), 500.0, 0, 16)
        ecg = EcgWaveform(leads=[lead], waveform_frequency=500.0, number_of_waveform_channels=1)

        worker = SpeckleTrackingWorker(
            frames=frames,
            zone=zone,
            pixel_spacing=(0.5, 0.5),
            ecg_waveform=ecg,
        )
        assert worker._ecg_waveform is not None

    def test_has_signals(self) -> None:
        from echo_personal_tool.domain.models.speckle import MyocardialZone

        frames = np.zeros((10, 32, 32), dtype=np.uint8)
        angles = np.linspace(0, 2 * np.pi, 16, endpoint=False)
        endo = np.column_stack([16 + 5 * np.cos(angles), 16 + 5 * np.sin(angles)])
        epi = np.column_stack([16 + 8 * np.cos(angles), 16 + 8 * np.sin(angles)])
        zone = MyocardialZone(
            endo_points=endo, epi_points=epi,
            thickness_mm=8.0, pixel_spacing=(0.5, 0.5),
        )

        worker = SpeckleTrackingWorker(
            frames=frames,
            zone=zone,
            pixel_spacing=(0.5, 0.5),
        )
        assert hasattr(worker.signals, "finished")
        assert hasattr(worker.signals, "error")
        assert hasattr(worker.signals, "progress")
