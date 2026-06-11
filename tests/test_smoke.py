"""Smoke tests for package bootstrap."""

import pytest

from echo_personal_tool import __version__


def test_version_is_set() -> None:
    assert __version__ == "0.1.0"


def test_onnx_engine_imports_with_phase2() -> None:
    pytest.importorskip("onnxruntime")
    from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine

    assert OnnxInferenceEngine is not None
