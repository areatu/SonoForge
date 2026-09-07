"""End-to-end 720p cine playback test for CI.

Everything else in this folder measures a *simulated* tick: FrameCache plus a NamedTuple
state, at 64-512 px, without Qt, without a decoder and without a viewer. That is why the
720p defects found by the audit (docs/bench/2026-09-06-cine-720p-playback-audit.md) never
showed up here - a per-frame ROI recompute, a display-levels cache that never hit, a
219 ms decode batch, a timer period that ignored the work of its own tick. Together they
cost 25 of 30 FPS and only exist once the real AppController, the real ViewerWidget and a
real multiframe DICOM meet.

This test drives exactly that, offscreen, and asserts on what a user would see.

The margins are deliberately wide (2-3x the measured healthy value, still 1.5-3x below the
broken one): the job is to catch a multiples-sized regression on a shared CI runner, not to
police the last millisecond.

Measured on the audit bench box (2 vCPU / 4 GB, Debian 12, offscreen raster), and against
the pre-fix baseline commit cf82a7b - where this same test fails on every threshold, so the
four P0 defects of the audit cannot come back unnoticed:

                                fixed tree              cf82a7b (broken)
    mono8 720p, 60 frames       30.92 FPS               11.91 FPS
      p95 inter-frame gap       33.3 ms                 84.5 ms
      ticks overdue >1.5x       0 %                     100 %
      render (show_frame_fast)  0.57 ms                 23.93 ms
      Play -> first frame       59 ms                   195 ms
    RGB24 720p, 30 frames       30.71 FPS                8.75 FPS
      p95 inter-frame gap       34.5 ms                 129.6 ms
      ticks overdue >1.5x       0 %                     100 %
      render (show_frame_fast)  1.06 ms                  2.91 ms
      Play -> first frame       38 ms                   186 ms
    cache misses                0 % both                0 % both

Run:  pytest tests/bench/test_cine_playback_e2e_ci.py -v
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.gui

from tests.fixtures.generate_synthetic_dicom import (  # noqa: E402
    write_synthetic_multiframe_dicom,
)

from echo_personal_tool.application.app_controller import AppController  # noqa: E402
from echo_personal_tool.domain.models import InstanceMetadata  # noqa: E402
from echo_personal_tool.infrastructure import playback_diagnostics as pd  # noqa: E402

ROWS, COLS = 720, 1280
FRAME_TIME_MS = 33.3
PLAY_SECONDS = 4.0


@pytest.fixture(scope="session")
def qapp_session():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture(scope="session")
def cine_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("cine720p")


@dataclass
class PlaybackRun:
    """What the user saw during the measured window."""

    first_frame_ms: float
    play_to_first_frame_ms: float
    fps: float
    gaps_ms: list[float]
    render_ms: list[float]
    shown: int
    cache_misses: int
    peak_cache_mb: float


def _run_cine(qapp, monkeypatch, path: Path, *, frames: int) -> PlaybackRun:
    """Load a cine into the real controller + viewer, play it, and measure."""
    from PySide6.QtCore import QThreadPool

    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    # Diagnostics give the cache-miss count; capture the report the controller logs on pause.
    reports: list = []
    real_stop = pd.PlaybackDiagnostics.stop

    def _stop(self):
        report = real_stop(self)
        reports.append(report)
        return report

    monkeypatch.setattr(pd, "_ENABLED", True)
    monkeypatch.setattr(pd.PlaybackDiagnostics, "stop", _stop)

    controller = AppController()
    viewer = ViewerWidget()
    viewer.resize(1400, 820)
    viewer.show()

    shown_at: list[float] = []
    render_ms: list[float] = []
    cache_mb: list[float] = []

    def on_frame(pixels) -> None:
        image = np.asarray(pixels)
        t0 = time.perf_counter()
        viewer.show_frame_fast(image)
        render_ms.append((time.perf_counter() - t0) * 1000.0)
        viewer._graphics.viewport().repaint()
        shown_at.append(time.perf_counter())
        cache_mb.append(controller._frame_cache.memory_bytes() / 1e6)

    controller.frame_loaded.connect(on_frame)
    controller.state_manager.state_changed.connect(viewer.set_state)

    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4",
        modality="US",
        number_of_frames=frames,
        pixel_spacing=(0.2, 0.2),
        frame_time_ms=FRAME_TIME_MS,
        series_description="ci-cine-720p",
        path=path,
        media_format="dicom",
    )

    try:
        t_load = time.perf_counter()
        controller.load_instance(instance)
        deadline = t_load + 30.0
        while controller._pending_decode_id != 0 and time.perf_counter() < deadline:
            qapp.processEvents()
            time.sleep(0.002)
        first_frame_ms = (time.perf_counter() - t_load) * 1000.0
        assert len(shown_at) == 1, "load_instance must deliver exactly the first frame"

        shown_at.clear()
        render_ms.clear()
        cache_mb.clear()

        controller.set_playing(True)
        t_play = time.perf_counter()
        while time.perf_counter() - t_play < PLAY_SECONDS:
            qapp.processEvents()
        elapsed = time.perf_counter() - t_play
        controller.set_playing(False)
        qapp.processEvents()
    finally:
        controller.frame_loaded.disconnect(on_frame)
        controller.state_manager.state_changed.disconnect(viewer.set_state)
        viewer.close()
        viewer.deleteLater()
        QThreadPool.globalInstance().waitForDone(5000)
        qapp.processEvents()

    play_to_first = (shown_at[0] - t_play) * 1000.0 if shown_at else float("inf")
    gaps = [(shown_at[i] - shown_at[i - 1]) * 1000.0 for i in range(1, len(shown_at))]
    ticks = reports[-1].frame_ticks if reports else []
    return PlaybackRun(
        first_frame_ms=first_frame_ms,
        play_to_first_frame_ms=play_to_first,
        fps=len(shown_at) / elapsed if elapsed > 0 else 0.0,
        gaps_ms=gaps,
        render_ms=render_ms,
        shown=len(shown_at),
        cache_misses=sum(1 for t in ticks if t.phase == "cache_miss"),
        peak_cache_mb=max(cache_mb) if cache_mb else 0.0,
    )


def _assert_playback_is_smooth(run: PlaybackRun, *, label: str) -> None:
    target_fps = 1000.0 / FRAME_TIME_MS
    p95 = float(np.percentile(run.gaps_ms, 95)) if run.gaps_ms else float("inf")
    overdue = sum(1 for g in run.gaps_ms if g > FRAME_TIME_MS * 1.5)
    overdue_pct = 100.0 * overdue / len(run.gaps_ms) if run.gaps_ms else 100.0
    miss_pct = 100.0 * run.cache_misses / max(1, run.shown + run.cache_misses)
    worst_render = float(np.mean(run.render_ms)) if run.render_ms else float("inf")

    detail = (
        f"{label}: fps={run.fps:.2f} p95_gap={p95:.1f} ms overdue={overdue_pct:.1f}% "
        f"misses={miss_pct:.1f}% render_avg={worst_render:.2f} ms "
        f"first_frame={run.first_frame_ms:.0f} ms play->frame={run.play_to_first_frame_ms:.0f} ms "
        f"shown={run.shown} peak_cache={run.peak_cache_mb:.0f} MB"
    )

    # Printed on success too (-s): these are the numbers the margins below were set from.
    print(detail)

    # Healthy: 30.7-30.8. Broken (audit baseline): 5.0-16.3.
    assert run.fps >= 20.0, detail
    # Healthy: 35 ms. Broken: 63-376 ms.
    assert p95 <= 2.5 * FRAME_TIME_MS, detail
    # Healthy: 0.3 %. Broken: 100 %.
    assert overdue_pct <= 10.0, detail
    # Healthy: 0 %. A starved cache is the failure mode this test exists for.
    assert miss_pct <= 5.0, detail
    # Healthy: 0.9-2.4 ms. Broken (per-frame ROI + dead W/L cache): 18-20 ms.
    assert worst_render <= 8.0, detail
    # Healthy: 10-33 ms. Broken (whole file re-read per frame): 216-473 ms.
    assert run.first_frame_ms <= 2000.0, detail
    # SLO is 250 ms; healthy is ~36 ms.
    assert run.play_to_first_frame_ms <= 750.0, detail
    assert run.fps > 0 and target_fps > 0


def test_cine_720p_mono_playback_holds_30fps(qapp_session, cine_dir, monkeypatch) -> None:
    """1280x720 MONOCHROME2, 60 frames (~55 MB): the common B-mode cine."""
    path = write_synthetic_multiframe_dicom(
        cine_dir / "ci_mono8_720p_60f.dcm",
        frame_count=60,
        rows=ROWS,
        cols=COLS,
        moving=True,
    )

    run = _run_cine(qapp_session, monkeypatch, path, frames=60)

    _assert_playback_is_smooth(run, label="mono8 720p")
    # Two loops of a 60-frame cine in 4 s at 30 fps; the cache holds the whole clip.
    assert run.shown >= 60, f"only {run.shown} frames shown in {PLAY_SECONDS} s"


def test_cine_720p_rgb_playback_holds_30fps(qapp_session, cine_dir, monkeypatch) -> None:
    """1280x720 RGB24, 30 frames (~83 MB): 2.76 MB per frame, the audit's worst case."""
    path = write_synthetic_multiframe_dicom(
        cine_dir / "ci_rgb24_720p_30f.dcm",
        frame_count=30,
        rows=ROWS,
        cols=COLS,
        samples_per_pixel=3,
        moving=True,
    )

    run = _run_cine(qapp_session, monkeypatch, path, frames=30)

    _assert_playback_is_smooth(run, label="RGB24 720p")
    assert run.shown >= 30, f"only {run.shown} frames shown in {PLAY_SECONDS} s"
