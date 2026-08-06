"""Unit tests for OnnxWorker and related functions."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

pytest.importorskip("pytestqt")

from echo_personal_tool.application.workers.onnx_worker import (
    _DEFAULT_TIMEOUT_SEC,
    OnnxWorker,
    OnnxWorkerSignals,
    _load_timeout_sec,
    run_segment_in_subprocess,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ── Signals ────────────────────────────────────────────────────────


class TestOnnxWorkerSignals:
    def test_has_required_signals(self):
        signals = OnnxWorkerSignals()
        assert hasattr(signals, "finished")
        assert hasattr(signals, "failed")
        assert hasattr(signals, "timed_out")


# ── _load_timeout_sec ─────────────────────────────────────────────


class TestLoadTimeoutSec:
    def test_missing_manifest_returns_default(self, tmp_path):
        result = _load_timeout_sec(tmp_path)
        assert result == _DEFAULT_TIMEOUT_SEC

    def test_manifest_without_inference_returns_default(self, tmp_path):
        manifest_path = tmp_path / "model_manifest.json"
        manifest_path.write_text(json.dumps({"active_model": "x"}))
        result = _load_timeout_sec(tmp_path)
        assert result == _DEFAULT_TIMEOUT_SEC

    def test_manifest_with_timeout(self, tmp_path):
        manifest_path = tmp_path / "model_manifest.json"
        manifest_path.write_text(json.dumps({"inference": {"timeout_sec": 5.0}}))
        result = _load_timeout_sec(tmp_path)
        assert result == 5.0

    def test_manifest_with_null_timeout(self, tmp_path):
        manifest_path = tmp_path / "model_manifest.json"
        manifest_path.write_text(json.dumps({"inference": {"timeout_sec": None}}))
        result = _load_timeout_sec(tmp_path)
        assert result == _DEFAULT_TIMEOUT_SEC


# ── run_segment_in_subprocess ──────────────────────────────────────


class TestRunSegmentInSubprocess:
    @patch("echo_personal_tool.application.workers.onnx_worker.OnnxInferenceEngine")
    def test_calls_engine_segment(self, MockEngine):
        engine = MagicMock()
        mask = np.zeros((10, 10), dtype=np.uint8)
        engine.segment.return_value = mask
        MockEngine.return_value = engine

        frame = np.zeros((10, 10), dtype=np.uint8)
        result_bytes = run_segment_in_subprocess(
            frame_bytes=frame.tobytes(),
            shape=frame.shape,
            dtype_str=frame.dtype.str,
            models_dir_str="/tmp/models",
            roi_xyxy=None,
            crop_mode="center_square",
            manifest_section="inference",
        )
        engine.segment.assert_called_once()
        result_mask = np.frombuffer(result_bytes, dtype=np.uint8).reshape((10, 10))
        assert result_mask.shape == (10, 10)

    @patch("echo_personal_tool.application.workers.onnx_worker.OnnxInferenceEngine")
    def test_passes_roi_and_crop(self, MockEngine):
        engine = MagicMock()
        mask = np.ones((10, 10), dtype=np.uint8)
        engine.segment.return_value = mask
        MockEngine.return_value = engine

        frame = np.zeros((10, 10), dtype=np.uint8)
        run_segment_in_subprocess(
            frame_bytes=frame.tobytes(),
            shape=frame.shape,
            dtype_str=frame.dtype.str,
            models_dir_str="/tmp/models",
            roi_xyxy=(1, 2, 3, 4),
            crop_mode="roi",
            manifest_section="inference",
        )
        _, kwargs = engine.segment.call_args
        assert kwargs["roi_xyxy"] == (1, 2, 3, 4)
        assert kwargs["crop_mode"] == "roi"


# ── OnnxWorker construction ───────────────────────────────────────


class TestOnnxWorkerConstruction:
    def test_init_with_defaults(self):
        frame = np.zeros((64, 64), dtype=np.uint8)
        worker = OnnxWorker(frame)
        assert worker._frame.shape == (64, 64)
        assert worker._roi_xyxy is None
        assert worker._crop_mode == "center_square"
        assert worker.autoDelete() is True

    def test_init_with_roi(self):
        frame = np.zeros((64, 64), dtype=np.uint8)
        worker = OnnxWorker(frame, roi_xyxy=(10, 10, 50, 50))
        assert worker._roi_xyxy == (10, 10, 50, 50)

    def test_init_with_custom_timeout(self):
        frame = np.zeros((64, 64), dtype=np.uint8)
        worker = OnnxWorker(frame, timeout_sec=10.0)
        assert worker._timeout_sec == 10.0

    def test_init_with_models_dir(self, tmp_path):
        frame = np.zeros((64, 64), dtype=np.uint8)
        worker = OnnxWorker(frame, models_dir=tmp_path)
        assert worker._models_dir == tmp_path


# ── OnnxWorker.run ────────────────────────────────────────────────


class TestOnnxWorkerRun:
    @patch("echo_personal_tool.application.workers.onnx_worker._get_pool")
    def test_successful_inference(self, mock_get_pool):
        mock_pool = MagicMock()
        mask = np.ones((10, 10), dtype=np.uint8)
        async_result = MagicMock()
        async_result.ready.return_value = True
        async_result.get.return_value = mask.tobytes()
        mock_pool.apply_async.return_value = async_result
        mock_get_pool.return_value = mock_pool

        frame = np.zeros((10, 10), dtype=np.uint8)
        worker = OnnxWorker(frame, timeout_sec=5.0)
        finished = []
        worker.signals.finished.connect(lambda m: finished.append(m))
        worker.run()

        assert len(finished) == 1
        assert finished[0].shape == (10, 10)
        np.testing.assert_array_equal(finished[0], mask)

    @patch("echo_personal_tool.application.workers.onnx_worker._get_pool")
    def test_pool_apply_fails(self, mock_get_pool):
        mock_pool = MagicMock()
        mock_pool.apply_async.side_effect = RuntimeError("pool error")
        mock_get_pool.return_value = mock_pool

        frame = np.zeros((10, 10), dtype=np.uint8)
        worker = OnnxWorker(frame, timeout_sec=5.0)
        failed = []
        worker.signals.failed.connect(lambda msg: failed.append(msg))
        worker.run()

        assert len(failed) == 1
        assert "pool error" in failed[0]

    @patch("echo_personal_tool.application.workers.onnx_worker._get_pool")
    def test_timeout(self, mock_get_pool):
        mock_pool = MagicMock()
        async_result = MagicMock()
        async_result.ready.return_value = False
        mock_pool.apply_async.return_value = async_result
        mock_get_pool.return_value = mock_pool

        frame = np.zeros((10, 10), dtype=np.uint8)
        worker = OnnxWorker(frame, timeout_sec=0.01)
        timed_out = []
        worker.signals.timed_out.connect(lambda: timed_out.append(True))
        worker.run()

        assert len(timed_out) == 1

    @patch("echo_personal_tool.application.workers.onnx_worker._get_pool")
    def test_result_get_exception(self, mock_get_pool):
        mock_pool = MagicMock()
        async_result = MagicMock()
        async_result.ready.return_value = True
        async_result.get.side_effect = RuntimeError("result error")
        mock_pool.apply_async.return_value = async_result
        mock_get_pool.return_value = mock_pool

        frame = np.zeros((10, 10), dtype=np.uint8)
        worker = OnnxWorker(frame, timeout_sec=5.0)
        failed = []
        worker.signals.failed.connect(lambda msg: failed.append(msg))
        worker.run()

        assert len(failed) == 1
        assert "result error" in failed[0]

    @patch("echo_personal_tool.application.workers.onnx_worker._get_pool")
    def test_polls_multiple_times_before_timeout(self, mock_get_pool):
        mock_pool = MagicMock()
        async_result = MagicMock()
        call_count = [0]

        def ready_side_effect():
            call_count[0] += 1
            return call_count[0] >= 3

        async_result.ready.side_effect = ready_side_effect
        mask = np.zeros((10, 10), dtype=np.uint8)
        async_result.get.return_value = mask.tobytes()
        mock_pool.apply_async.return_value = async_result
        mock_get_pool.return_value = mock_pool

        frame = np.zeros((10, 10), dtype=np.uint8)
        worker = OnnxWorker(frame, timeout_sec=5.0)
        finished = []
        worker.signals.finished.connect(lambda m: finished.append(m))
        worker.run()

        assert len(finished) == 1

    @patch("echo_personal_tool.application.workers.onnx_worker._get_pool")
    def test_mask_shape_matches_frame(self, mock_get_pool):
        mock_pool_inst = MagicMock()
        mask = np.ones((20, 30), dtype=np.uint8)
        async_result = MagicMock()
        async_result.ready.return_value = True
        async_result.get.return_value = mask.tobytes()
        mock_pool_inst.apply_async.return_value = async_result
        mock_get_pool.return_value = mock_pool_inst

        frame = np.zeros((20, 30), dtype=np.uint8)
        worker = OnnxWorker(frame, timeout_sec=5.0)
        finished = []
        worker.signals.finished.connect(lambda m: finished.append(m))
        worker.run()

        assert finished[0].shape == (20, 30)
