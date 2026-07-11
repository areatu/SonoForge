"""Unit tests for OnnxWorker background inference."""

from __future__ import annotations

import json
import sys
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QWidget

from echo_personal_tool.application.workers.onnx_worker import (
    OnnxWorker,
    run_segment_in_subprocess,
)

pytest.importorskip("pytestqt")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _write_manifest(models_dir: Path, *, timeout_sec: float = 2.0) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "active_model": "echonet_seg_resnet50",
        "models": {
            "echonet_seg_resnet50": {
                "filename": "echonet_seg_resnet50.onnx",
            }
        },
        "inference": {
            "timeout_sec": timeout_sec,
        },
    }
    (models_dir / "model_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class _InlinePool:
    """Run submitted callables synchronously for deterministic unit tests."""

    def apply_async(self, fn, args=(), kwargs=None):
        from concurrent.futures import Future as _Future
        from unittest.mock import MagicMock

        result = _Future()
        try:
            result.set_result(fn(*args, **(kwargs or {})))
        except Exception as exc:  # noqa: BLE001
            result.set_exception(exc)
        mock = MagicMock()
        mock.get.return_value = result.result()
        return mock


class _PendingPool:
    """Return a result that never completes (for timeout tests)."""

    def apply_async(self, fn, args=(), kwargs=None):
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock.ready.return_value = False
        mock.get.side_effect = lambda timeout=None: (_ for _ in ()).throw(
            __import__("multiprocessing").TimeoutError
        )
        return mock


def _run_worker(qtbot, worker: OnnxWorker) -> None:
    QThreadPool.globalInstance().start(worker)


def test_run_segment_in_subprocess_returns_mask_bytes(tmp_path: Path) -> None:
    frame = np.zeros((32, 24), dtype=np.uint8)
    expected = np.ones((32, 24), dtype=np.uint8)

    with patch(
        "echo_personal_tool.application.workers.onnx_worker.OnnxInferenceEngine",
    ) as mock_engine_cls:
        mock_engine_cls.return_value.segment.return_value = expected
        mask_bytes = run_segment_in_subprocess(
            frame.tobytes(),
            frame.shape,
            frame.dtype.str,
            str(tmp_path),
        )

    mask = np.frombuffer(mask_bytes, dtype=np.uint8).reshape(frame.shape)
    np.testing.assert_array_equal(mask, expected)


def test_worker_emits_finished_with_mask(
    qapp: QApplication,
    qtbot,
    tmp_path: Path,
) -> None:
    parent = QWidget()
    frame = np.zeros((16, 12), dtype=np.uint8)
    mask = np.ones((16, 12), dtype=np.uint8)
    received: list[np.ndarray] = []

    worker = OnnxWorker(frame, models_dir=tmp_path, parent=parent)
    worker.signals.finished.connect(received.append)

    with patch(
        "echo_personal_tool.application.workers.onnx_worker._get_pool",
        return_value=_InlinePool(),
    ), patch(
        "echo_personal_tool.application.workers.onnx_worker.run_segment_in_subprocess",
        return_value=mask.tobytes(),
    ):
        _run_worker(qtbot, worker)
        qtbot.waitUntil(lambda: len(received) == 1, timeout=5000)

    np.testing.assert_array_equal(received[0], mask)


def test_worker_emits_failed_on_exception(
    qapp: QApplication,
    qtbot,
    tmp_path: Path,
) -> None:
    parent = QWidget()
    frame = np.zeros((8, 8), dtype=np.uint8)
    errors: list[str] = []

    worker = OnnxWorker(frame, models_dir=tmp_path, parent=parent)
    worker.signals.failed.connect(errors.append)

    with patch(
        "echo_personal_tool.application.workers.onnx_worker._get_pool",
        return_value=_InlinePool(),
    ), patch(
        "echo_personal_tool.application.workers.onnx_worker.run_segment_in_subprocess",
        side_effect=RuntimeError("segmentation failed"),
    ):
        _run_worker(qtbot, worker)
        qtbot.waitUntil(lambda: len(errors) == 1, timeout=5000)

    assert errors[0] == "segmentation failed"


def test_worker_emits_timed_out(
    qapp: QApplication,
    qtbot,
    tmp_path: Path,
) -> None:
    parent = QWidget()
    frame = np.zeros((8, 8), dtype=np.uint8)
    timed_out: list[bool] = []

    worker = OnnxWorker(frame, models_dir=tmp_path, timeout_sec=0.05, parent=parent)
    worker.signals.timed_out.connect(lambda: timed_out.append(True))

    with patch(
        "echo_personal_tool.application.workers.onnx_worker._get_pool",
        return_value=_PendingPool(),
    ):
        _run_worker(qtbot, worker)
        qtbot.waitUntil(lambda: len(timed_out) == 1, timeout=5000)

    assert timed_out == [True]


def test_worker_loads_timeout_from_manifest(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir, timeout_sec=3.5)

    worker = OnnxWorker(np.zeros((4, 4), dtype=np.uint8), models_dir=models_dir)

    assert worker._timeout_sec == 3.5


def test_worker_defaults_timeout_when_manifest_missing(tmp_path: Path) -> None:
    worker = OnnxWorker(np.zeros((4, 4), dtype=np.uint8), models_dir=tmp_path / "models")

    assert worker._timeout_sec == 2.0


def test_get_pool_uses_spawn_context() -> None:
    mock_ctx = MagicMock()
    mock_pool = MagicMock()
    mock_ctx.Pool.return_value = mock_pool
    with patch(
        "echo_personal_tool.application.workers.onnx_worker.multiprocessing",
    ) as mock_mp:
        mock_mp.get_context.return_value = mock_ctx
        from echo_personal_tool.application.workers import onnx_worker

        onnx_worker._pool = None
        first = onnx_worker._get_pool()
        second = onnx_worker._get_pool()

    mock_mp.get_context.assert_called_once_with("spawn")
    mock_ctx.Pool.assert_called_once_with(processes=2, initializer=onnx_worker._init_worker)
    assert first is second
    onnx_worker._pool = None
