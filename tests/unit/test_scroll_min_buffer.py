"""Scroll neighbor prefetch respects min_buffer and scroll_batch_size."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.infrastructure.system_profiler import PlaybackConfig

pytest.importorskip("pytestqt")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _scroll_cfg(**overrides: int) -> PlaybackConfig:
    defaults = {
        "prefetch_radius": 3,
        "min_buffer": 2,
        "batch_size": 3,
        "max_lag_frames": 2,
        "evict_window": 30,
        "scroll_debounce_ms": 80,
        "scroll_batch_size": 5,
    }
    defaults.update(overrides)
    return PlaybackConfig(**defaults)


def _mp4_instance(path: Path, frames: int = 20) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2.3.4",
        modality="US",
        number_of_frames=frames,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="Test",
        path=path,
        media_format="mp4",
    )


def test_scroll_neighbors_fill_to_min_buffer_first(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    started: list[object] = []

    class _SpyPool:
        def start(self, worker) -> None:
            started.append(worker)

    class _SpyLoader:
        def __init__(
            self,
            path,
            frame_index=0,
            media_format="mp4",
            parent=None,
            total_frames=0,
            batch_size=0,
        ) -> None:
            self._batch_size = batch_size
            self._frame_index = frame_index
            self.signals = MagicMock()

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        _SpyLoader,
    )
    controller = AppController(thread_pool=_SpyPool())
    controller._playback_config = _scroll_cfg(min_buffer=2, scroll_batch_size=5)
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 20)
    controller._frame_cache.put(5, np.zeros((8, 8), dtype=np.uint8))

    controller._maybe_start_scroll_neighbors(5)

    assert len(started) == 1
    assert started[0]._frame_index == 6
    assert started[0]._batch_size == 2


def test_scroll_neighbors_respect_scroll_batch_size_cap(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    started: list[object] = []

    class _SpyPool:
        def start(self, worker) -> None:
            started.append(worker)

    class _SpyLoader:
        def __init__(
            self,
            path,
            frame_index=0,
            media_format="mp4",
            parent=None,
            total_frames=0,
            batch_size=0,
        ) -> None:
            self._batch_size = batch_size
            self._frame_index = frame_index
            self.signals = MagicMock()

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.FrameLoaderWorker",
        _SpyLoader,
    )
    controller = AppController(thread_pool=_SpyPool())
    controller._playback_config = _scroll_cfg(min_buffer=2, scroll_batch_size=5)
    mp4 = tmp_path / "clip.mp4"
    mp4.write_bytes(b"\x00")
    inst = _mp4_instance(mp4)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(mp4, 20)
    controller._frame_cache.put(5, np.zeros((8, 8), dtype=np.uint8))
    controller._frame_cache.put(6, np.zeros((8, 8), dtype=np.uint8))
    controller._frame_cache.put(7, np.zeros((8, 8), dtype=np.uint8))
    controller._frame_cache.put(8, np.zeros((8, 8), dtype=np.uint8))

    controller._maybe_start_scroll_neighbors(5)

    assert len(started) == 1
    assert started[0]._frame_index == 9
    assert started[0]._batch_size == 2
