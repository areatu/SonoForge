"""Cine time-scale ROI detection must run once per instance, never once per frame.

`_emit_cached_frame()` used to call `_maybe_cache_cine_roi_from_frame()` on every emitted
frame, which ran `resolve_cine_segment_roi_xyxy()` (grayscale conversion + tick detector):
14.4-14.9 ms per 1280x720 frame, 23.3 ms on noisy RGB, 38.1 ms on uint16 - up to 45% of a
30 FPS frame budget spent on the main thread.

For DICOM the result was thrown away by design (`_frozen_cine_segment_roi()` and
`_cache_cine_segment_roi()` both refuse `media_format == "dicom"`; DICOM resolves the ROI
from tags), and for cine files whose frame yields no ROI the `is not None` guard never
tripped, so the detector re-ran on every frame in both cases.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models import InstanceMetadata


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _SpyPool:
    """Thread pool double: these tests never start a worker."""

    def start(self, worker):  # pragma: no cover - defensive
        raise AssertionError("no worker must be started by the ROI probe")


def _instance(path: Path, media_format: str, uid: str = "1.2.840.1") -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="1.2.840.2",
        modality="US",
        number_of_frames=8,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="cine",
        path=path,
        media_format=media_format,
    )


@pytest.fixture
def detector(monkeypatch):
    """Replace the detector with a recorder. Returns (calls, result_box)."""
    calls: list[np.ndarray] = []
    result_box: list = [None]

    def _fake_resolve(frame):
        calls.append(frame)
        return result_box[0]

    monkeypatch.setattr(
        "echo_personal_tool.application.app_controller.resolve_cine_segment_roi_xyxy",
        _fake_resolve,
    )
    return calls, result_box


def test_dicom_frames_never_run_cine_roi_detection(qapp, detector, tmp_path) -> None:
    calls, _ = detector
    controller = AppController(thread_pool=_SpyPool())
    controller._current_instance = _instance(tmp_path / "cine.dcm", "dicom")
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    for index in range(5):
        controller._maybe_cache_cine_roi_from_frame(frame, index)

    assert calls == []


def test_cine_without_time_scale_is_probed_once(qapp, detector, tmp_path) -> None:
    calls, result_box = detector
    result_box[0] = None  # detector finds no ticks in this cine
    controller = AppController(thread_pool=_SpyPool())
    controller._current_instance = _instance(tmp_path / "cine.mp4", "mp4")
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    for index in range(5):
        controller._maybe_cache_cine_roi_from_frame(frame, index)

    assert len(calls) == 1


def test_detected_roi_is_cached_and_not_recomputed(qapp, detector, tmp_path) -> None:
    calls, result_box = detector
    roi = (10.0, 20.0, 300.0, 400.0)
    result_box[0] = roi
    controller = AppController(thread_pool=_SpyPool())
    controller._current_instance = _instance(tmp_path / "cine.mp4", "mp4")
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    controller._maybe_cache_cine_roi_from_frame(frame, 0)
    controller._maybe_cache_cine_roi_from_frame(frame, 1)
    controller._maybe_cache_cine_roi_from_frame(frame, 2)

    assert len(calls) == 1
    assert controller._frozen_cine_segment_roi() == roi


def test_every_new_cine_instance_gets_one_probe(qapp, detector, tmp_path) -> None:
    calls, _ = detector
    controller = AppController(thread_pool=_SpyPool())
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    for index, name in enumerate(("a.mp4", "b.mp4", "a.mp4")):
        controller._current_instance = _instance(tmp_path / name, "mp4", uid=f"1.2.840.{index}")
        controller._maybe_cache_cine_roi_from_frame(frame, 0)
        controller._maybe_cache_cine_roi_from_frame(frame, 1)

    assert len(calls) == 3


def test_missing_instance_is_ignored(qapp, detector, tmp_path) -> None:
    calls, _ = detector
    controller = AppController(thread_pool=_SpyPool())
    controller._current_instance = None

    controller._maybe_cache_cine_roi_from_frame(np.zeros((8, 8, 3), dtype=np.uint8), 0)

    assert calls == []
