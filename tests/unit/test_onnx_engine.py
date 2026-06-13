"""Unit tests for OnnxInferenceEngine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine


def _write_manifest(models_dir: Path, *, include_onnx_file: bool = True) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = models_dir / "echonet_seg_resnet50.onnx"
    if include_onnx_file:
        onnx_path.write_bytes(b"fake-onnx")
    manifest = {
        "active_model": "echonet_seg_resnet50",
        "models": {
            "echonet_seg_resnet50": {
                "filename": "echonet_seg_resnet50.onnx",
                "onnx": {
                    "input_name": "input",
                    "output_name": "logits",
                    "input_shape": [1, 3, 112, 112],
                },
            }
        },
    }
    manifest_path = models_dir / "model_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return onnx_path


def test_is_available_true_when_manifest_and_model_exist(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir)

    with patch(
        "echo_personal_tool.infrastructure.onnx_engine._get_ort",
        return_value=MagicMock(),
    ), patch(
        "echo_personal_tool.infrastructure.onnx_engine._create_session",
    ) as mock_create:
        mock_create.return_value = MagicMock()
        engine = OnnxInferenceEngine(models_dir=models_dir)

        assert engine.is_available() is True
        mock_create.assert_called_once()


def test_is_available_false_when_manifest_missing(tmp_path: Path) -> None:
    engine = OnnxInferenceEngine(models_dir=tmp_path / "models")

    assert engine.is_available() is False


def test_is_available_false_when_onnx_file_missing(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir, include_onnx_file=False)

    engine = OnnxInferenceEngine(models_dir=models_dir)

    assert engine.is_available() is False


def test_segment_returns_frame_sized_mask(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir)
    logits = np.full((1, 1, 112, 112), 2.0, dtype=np.float32)
    session = MagicMock()
    session.run.return_value = [logits]

    engine = OnnxInferenceEngine(models_dir=models_dir, session=session)
    frame = np.zeros((200, 150), dtype=np.uint8)

    mask = engine.segment(frame)

    assert mask.shape == (200, 150)
    assert mask.dtype == np.uint8
    assert set(np.unique(mask)).issubset({0, 1})
    session.run.assert_called_once()
    call_args = session.run.call_args
    assert call_args.args[0] == ["logits"]
    assert "input" in call_args.args[1]
    assert call_args.args[1]["input"].shape == (1, 3, 112, 112)


def test_segment_upscales_partial_mask_to_frame_size(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir)
    logits = np.full((1, 1, 112, 112), -2.0, dtype=np.float32)
    logits[:, :, 40:70, 40:70] = 2.0
    session = MagicMock()
    session.run.return_value = [logits]

    engine = OnnxInferenceEngine(models_dir=models_dir, session=session)
    frame = np.zeros((224, 224, 3), dtype=np.uint8)

    mask = engine.segment(frame)

    assert mask.shape == (224, 224)
    assert mask.sum() > 0


def test_segment_raises_when_unavailable(tmp_path: Path) -> None:
    engine = OnnxInferenceEngine(models_dir=tmp_path / "models")
    frame = np.zeros((64, 64), dtype=np.uint8)

    with pytest.raises(RuntimeError, match="not available"):
        engine.segment(frame)


def test_segment_uses_cpu_provider_when_creating_session(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    onnx_path = _write_manifest(models_dir)

    with patch(
        "echo_personal_tool.infrastructure.onnx_engine._get_ort",
        return_value=MagicMock(),
    ), patch(
        "echo_personal_tool.infrastructure.onnx_engine._create_session",
    ) as mock_create_session:
        mock_create_session.return_value = MagicMock()
        OnnxInferenceEngine(models_dir=models_dir)

    mock_create_session.assert_called_once_with(onnx_path)
