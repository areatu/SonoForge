"""Two-phase scroll load: target frame first, then neighbor prefetch."""

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
from echo_personal_tool.domain.models.viewer_state import ViewerState
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
        "scroll_batch_size": 3,
    }
    defaults.update(overrides)
    return PlaybackConfig(**defaults)


def _dicom_instance(path: Path, frames: int = 10) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=frames,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=40.0,
        series_description="Test",
        path=path,
        media_format="dicom",
    )


def _make_controller(monkeypatch: pytest.MonkeyPatch) -> tuple[AppController, list[object]]:
    started: list[object] = []

    class _SpyPool:
        def start(self, worker) -> None:
            started.append(worker)

    class _SpyLoader:
        def __init__(
            self,
            path,
            frame_index=0,
            media_format="dicom",
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
    controller._playback_config = _scroll_cfg()
    return controller, started


def test_scroll_phase1_uses_batch_size_one(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, started = _make_controller(monkeypatch)
    path = tmp_path / "study.dcm"
    path.write_bytes(b"\x00")
    inst = _dicom_instance(path)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(path, 10)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))

    state = ViewerState(
        instance=inst,
        current_frame_index=5,
        total_frames=10,
        frame_time_ms=40.0,
        is_playing=False,
        scroll_navigation=True,
    )
    controller._request_frame_if_needed(state)

    assert len(started) == 1
    assert started[0]._batch_size == 1
    assert started[0]._frame_index == 5


def test_scroll_phase2_after_phase1(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, started = _make_controller(monkeypatch)
    path = tmp_path / "study.dcm"
    path.write_bytes(b"\x00")
    inst = _dicom_instance(path)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(path, 10)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))
    controller._batch_target_frame = 5

    state = ViewerState(
        instance=inst,
        current_frame_index=5,
        total_frames=10,
        frame_time_ms=40.0,
        is_playing=False,
        scroll_navigation=True,
    )
    controller._request_frame_if_needed(state)
    assert len(started) == 1
    request_id = controller._scroll_load_id
    pixels = np.zeros((8, 8), dtype=np.uint8)
    controller._on_scroll_target_loaded(request_id, path, [(5, pixels)])

    assert len(started) == 2
    assert started[1]._batch_size == 2
    assert started[1]._frame_index == 6


def test_scroll_cancel_phase2_on_new_target(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, started = _make_controller(monkeypatch)
    path = tmp_path / "study.dcm"
    path.write_bytes(b"\x00")
    inst = _dicom_instance(path)
    controller._current_instance = inst
    controller._frame_cache.set_total_frames(path, 10)
    controller._frame_cache.put(0, np.zeros((8, 8), dtype=np.uint8))

    state5 = ViewerState(
        instance=inst,
        current_frame_index=5,
        total_frames=10,
        frame_time_ms=40.0,
        is_playing=False,
        scroll_navigation=True,
    )
    controller._request_frame_if_needed(state5)
    phase1_id = controller._scroll_load_id
    pixels = np.zeros((8, 8), dtype=np.uint8)
    controller._on_scroll_target_loaded(phase1_id, path, [(5, pixels)])
    neighbor_id = controller._scroll_neighbor_load_id
    assert neighbor_id != 0

    state8 = ViewerState(
        instance=inst,
        current_frame_index=8,
        total_frames=10,
        frame_time_ms=40.0,
        is_playing=False,
        scroll_navigation=True,
    )
    controller._request_frame_if_needed(state8)
    assert controller._scroll_neighbor_load_id == 0

    stale_pixels = np.ones((8, 8), dtype=np.uint8)
    controller._on_scroll_neighbors_loaded(neighbor_id, path, [(6, stale_pixels)])
    assert not controller._frame_cache.is_loaded(6)
