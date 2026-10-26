"""Tests for the background cine phase worker (QtCore only, no display)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6.QtCore")

from echo_personal_tool.application.workers.cine_phase_worker import (  # noqa: E402
    FAILURE_NO_FRAMES,
    CinePhaseWorker,
)
from echo_personal_tool.domain.services.cine_phase_timeline import PhaseTimeline  # noqa: E402


def _dark_pool_cine(n: int = 72, period: int = 24) -> np.ndarray:
    yy, xx = np.mgrid[:64, :64]
    frames = []
    for t in range(n):
        radius = 12 + 6 * np.cos(2 * np.pi * (t - 3) / period)
        cavity = ((xx - 32) / radius) ** 2 + ((yy - 32) / (radius * 1.3)) ** 2 < 1
        image = np.full((64, 64, 3), 170, dtype=np.uint8)
        image[cavity] = 20
        frames.append(image)
    return np.asarray(frames)


def _worker(monkeypatch: pytest.MonkeyPatch, frames: np.ndarray | None, r_peaks=None, confidence: float = 0.0):
    worker = CinePhaseWorker(
        source_path=Path("/tmp/fake.dcm"),
        media_format="dicom",
        frame_time_ms=33.3,
        n_frames=72,
        instance_uid="1.2.3",
        generation=7,
    )
    monkeypatch.setattr(worker, "_load_frames", lambda: frames)
    monkeypatch.setattr(worker, "_read_ecg_r_peaks", lambda: (r_peaks, confidence))
    return worker


class TestDownsample:
    def test_spatial_decimation_preserves_temporal_resolution_and_colour(self) -> None:
        frames = np.full((12, 200, 300, 3), 128, dtype=np.uint8)
        result = CinePhaseWorker._downsample(list(frames))
        assert result is not None
        assert result.shape[0] == 12
        assert result.shape[1] == 64
        assert result.shape[2] == 96
        assert result.shape[3] == 3
        assert result.dtype == np.uint8

    def test_grayscale_stack_stays_3d(self) -> None:
        frames = np.zeros((8, 120, 160), dtype=np.float32)
        result = CinePhaseWorker._downsample(list(frames))
        assert result is not None
        assert result.shape[1] == 72
        assert result.shape[2] == 96


class TestRun:
    def test_finished_carries_timeline_uid_and_generation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        worker = _worker(monkeypatch, _dark_pool_cine())
        captured: list[tuple[object, str, int]] = []
        worker.signals.finished.connect(lambda *args: captured.append(args))
        worker.run()
        assert len(captured) == 1
        timeline, uid, generation = captured[0]
        assert isinstance(timeline, PhaseTimeline)
        assert uid == "1.2.3" and generation == 7
        assert timeline.n_frames == 72
        assert timeline.cycles

    def test_ecg_peaks_are_forwarded_to_the_detector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r_peaks = np.asarray([100.0, 900.0, 1700.0])
        worker = _worker(monkeypatch, _dark_pool_cine(), r_peaks=r_peaks, confidence=0.95)
        captured: list[tuple[object, str, int]] = []
        worker.signals.finished.connect(lambda *args: captured.append(args))
        worker.run()
        timeline = captured[0][0]
        assert timeline.source.startswith("ecg")

    def test_missing_frames_emits_stable_failure_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        worker = _worker(monkeypatch, None)
        failures: list[tuple[str, str, int]] = []
        worker.signals.failed.connect(lambda *args: failures.append(args))
        worker.run()
        assert failures == [(FAILURE_NO_FRAMES, "1.2.3", 7)]
