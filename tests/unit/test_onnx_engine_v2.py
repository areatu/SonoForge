"""Tests for ONNX engine v2 (224x224 support)."""

from __future__ import annotations

from echo_personal_tool.infrastructure.onnx_engine import (
    OnnxInferenceEngine,
    _resolve_io_names,
)


class TestResolveInputSize:
    def test_default_112_when_no_manifest(self) -> None:
        engine = OnnxInferenceEngine.__new__(OnnxInferenceEngine)
        engine._manifest = None
        assert engine._resolve_input_size() == 112

    def test_reads_224_from_manifest(self) -> None:
        engine = OnnxInferenceEngine.__new__(OnnxInferenceEngine)
        engine._manifest = {
            "active_model": "test_model",
            "models": {"test_model": {"onnx": {"input_shape": [1, 3, 224, 224]}}},
        }
        assert engine._resolve_input_size() == 224

    def test_reads_112_from_manifest(self) -> None:
        engine = OnnxInferenceEngine.__new__(OnnxInferenceEngine)
        engine._manifest = {
            "active_model": "test_model",
            "models": {"test_model": {"onnx": {"input_shape": [1, 3, 112, 112]}}},
        }
        assert engine._resolve_input_size() == 112

    def test_fallback_when_no_onnx_meta(self) -> None:
        engine = OnnxInferenceEngine.__new__(OnnxInferenceEngine)
        engine._manifest = {
            "active_model": "test_model",
            "models": {"test_model": {}},
        }
        assert engine._resolve_input_size() == 112


class TestResolveIoNames:
    def test_custom_names(self) -> None:
        manifest = {
            "active_model": "m",
            "models": {"m": {"onnx": {"input_name": "x", "output_name": "y"}}},
        }
        assert _resolve_io_names(manifest) == ("x", "y")

    def test_default_names(self) -> None:
        assert _resolve_io_names({}) == ("input", "logits")
