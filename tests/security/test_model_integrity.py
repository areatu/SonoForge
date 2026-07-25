"""Verify ONNX model SHA256 checksums are validated on load.

Tests that corrupted models are rejected and integrity mismatches are logged.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.security

from echo_personal_tool.infrastructure.onnx_engine import (
    ModelIntegrityError,
    OnnxInferenceEngine,
    _load_manifest,
    _resolve_model_path,
    _verify_model_integrity,
)


class TestModelIntegrityVerification:
    """Test _verify_model_integrity against expected SHA256 hashes."""

    def test_matching_hash_no_warning(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake model data")
        expected = hashlib.sha256(model.read_bytes()).hexdigest()
        with caplog.at_level(logging.WARNING):
            _verify_model_integrity(model, expected)
        assert "integrity mismatch" not in caplog.text.lower()

    def test_mismatched_hash_raises_error(self, tmp_path: Path) -> None:
        model = tmp_path / "model.onnx"
        model.write_bytes(b"fake model data")
        with pytest.raises(ModelIntegrityError, match="integrity check failed"):
            _verify_model_integrity(model, "0" * 64)

    def test_none_hash_skips_check(self, tmp_path: Path) -> None:
        model = tmp_path / "model.onnx"
        model.write_bytes(b"data")
        _verify_model_integrity(model, None)

    def test_empty_hash_skips_check(self, tmp_path: Path) -> None:
        model = tmp_path / "model.onnx"
        model.write_bytes(b"data")
        _verify_model_integrity(model, "")

    def test_tampered_model_detected(self, tmp_path: Path) -> None:
        original = tmp_path / "model.onnx"
        original.write_bytes(b"original model content")
        expected = hashlib.sha256(original.read_bytes()).hexdigest()
        tampered = tmp_path / "tampered.onnx"
        tampered.write_bytes(b"tampered model content")
        with pytest.raises(ModelIntegrityError, match="integrity check failed"):
            _verify_model_integrity(tampered, expected)

    def test_empty_model_file_hash(self, tmp_path: Path) -> None:
        model = tmp_path / "empty.onnx"
        model.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        _verify_model_integrity(model, expected)


class TestModelManifestLoading:
    """Test manifest loading and model resolution."""

    def test_missing_manifest_returns_none(self, tmp_path: Path) -> None:
        result = _load_manifest(tmp_path)
        assert result is None

    def test_valid_manifest_loaded(self, tmp_path: Path) -> None:
        manifest = {
            "inference": {"active_model": "seg_model"},
            "models": {
                "seg_model": {
                    "filename": "seg.onnx",
                    "sha256": "abc123",
                    "onnx": {"input_name": "input", "output_name": "logits"},
                }
            },
        }
        (tmp_path / "model_manifest.json").write_text(json.dumps(manifest))
        result = _load_manifest(tmp_path)
        assert result is not None
        assert result["inference"]["active_model"] == "seg_model"

    def test_resolve_model_path_valid(self, tmp_path: Path) -> None:
        manifest = {
            "inference": {"active_model": "seg"},
            "models": {"seg": {"filename": "seg.onnx"}},
        }
        (tmp_path / "seg.onnx").write_bytes(b"model")
        result = _resolve_model_path(tmp_path, manifest)
        assert result == tmp_path / "seg.onnx"

    def test_resolve_model_path_no_active(self, tmp_path: Path) -> None:
        manifest = {"models": {"seg": {"filename": "seg.onnx"}}}
        result = _resolve_model_path(tmp_path, manifest)
        assert result is None

    def test_resolve_model_path_missing_filename(self, tmp_path: Path) -> None:
        manifest = {
            "inference": {"active_model": "seg"},
            "models": {"seg": {}},
        }
        result = _resolve_model_path(tmp_path, manifest)
        assert result is None

    def test_resolve_model_path_nonexistent_file(self, tmp_path: Path) -> None:
        manifest = {
            "inference": {"active_model": "seg"},
            "models": {"seg": {"filename": "missing.onnx"}},
        }
        result = _resolve_model_path(tmp_path, manifest)
        assert result == tmp_path / "missing.onnx"


class TestOnnxEngineInit:
    """Test OnnxInferenceEngine initialization edge cases."""

    def test_session_passed_directly(self, tmp_path: Path) -> None:
        mock_session = MagicMock()
        engine = OnnxInferenceEngine(models_dir=tmp_path, session=mock_session)
        assert engine._session is mock_session

    def test_missing_model_file_session_none(self, tmp_path: Path) -> None:
        manifest = {
            "inference": {"active_model": "seg"},
            "models": {"seg": {"filename": "missing.onnx"}},
        }
        (tmp_path / "model_manifest.json").write_text(json.dumps(manifest))
        engine = OnnxInferenceEngine(models_dir=tmp_path)
        assert engine.is_available() is False
        assert engine._session is None

    def test_segment_without_session_raises(self, tmp_path: Path) -> None:
        engine = OnnxInferenceEngine(models_dir=tmp_path, session=None)
        import numpy as np

        with pytest.raises(RuntimeError, match="not available"):
            engine.segment(np.zeros((112, 112), dtype=np.uint8))

    def test_crop_mode_default(self, tmp_path: Path) -> None:
        engine = OnnxInferenceEngine(models_dir=tmp_path, session=MagicMock())
        assert engine.crop_mode == "center_square"

    def test_crop_mode_from_manifest(self, tmp_path: Path) -> None:
        manifest = {
            "inference": {"active_model": "seg", "crop_mode": "echonet"},
            "models": {"seg": {"filename": "seg.onnx"}},
        }
        (tmp_path / "model_manifest.json").write_text(json.dumps(manifest))
        (tmp_path / "seg.onnx").write_bytes(b"model")
        with patch(
            "echo_personal_tool.infrastructure.onnx_engine._create_session",
            return_value=MagicMock(),
        ):
            engine = OnnxInferenceEngine(models_dir=tmp_path)
        assert engine.crop_mode == "echonet"
