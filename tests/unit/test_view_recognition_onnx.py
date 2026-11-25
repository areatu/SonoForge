"""Unit tests for the ONNX view-recognition adapter (#639 step 2)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from echo_personal_tool.infrastructure import view_recognition_onnx as vro
from echo_personal_tool.infrastructure.view_recognition_onnx import OnnxViewRecognizer

MODEL_ID = "view_recognition_efficientnet_b0"


def _write_manifest(
    models_dir: Path,
    *,
    include_model: bool = True,
    class_names: Sequence[str] | None = None,
) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = models_dir / "view_recognition_efficientnet_b0.onnx"
    if include_model:
        onnx_path.write_bytes(b"fake-onnx")
    manifest = {
        "schema_version": "1.0",
        "models": {
            MODEL_ID: {
                "filename": onnx_path.name,
                "onnx": {
                    "input_name": "input",
                    "output_name": "logits",
                    "input_shape": [1, 3, 224, 224],
                },
                "sha256": "deadbeef",
            }
        },
        "view_recognition": {
            "active_model": MODEL_ID,
            **({"class_names": list(class_names)} if class_names else {}),
        },
    }
    manifest_path = models_dir / "model_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return onnx_path


def _frames(n: int = 4) -> list[np.ndarray]:
    return [np.full((8, 8), 0.5, dtype=np.float32) for _ in range(n)]


def _fake_session(logits: np.ndarray) -> MagicMock:
    session = MagicMock()
    session.run.return_value = [logits]
    return session


def test_is_available_true_when_manifest_and_model_exist(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir)
    recognizer = OnnxViewRecognizer(models_dir=models_dir, session=_fake_session(np.zeros((4, 7), dtype=np.float32)))
    assert recognizer.is_available() is True


def test_is_available_false_without_manifest(tmp_path: Path) -> None:
    recognizer = OnnxViewRecognizer(models_dir=tmp_path / "empty")
    assert recognizer.is_available() is False


def test_is_available_false_without_model_file(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir, include_model=False)
    recognizer = OnnxViewRecognizer(models_dir=models_dir)
    assert recognizer.is_available() is False


def test_recognize_raises_when_session_missing(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir, include_model=False)
    recognizer = OnnxViewRecognizer(models_dir=models_dir)
    with pytest.raises(RuntimeError):
        recognizer.recognize(_frames())


def test_recognize_returns_view_from_softmax_logits(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir)
    logits = np.zeros((4, 7), dtype=np.float32)
    logits[:, 2] = 5.0  # A3C wins every frame
    recognizer = OnnxViewRecognizer(models_dir=models_dir, session=_fake_session(logits))
    result = recognizer.recognize(_frames(4))
    assert result.view == "A3C"
    assert result.confidence > 0.9

    # The published model still emits 7 logits; a 5-class manifest must ignore
    # SAX/TEE outputs instead of failing on the column-count mismatch.
    _write_manifest(models_dir, class_names=["A4C", "A2C", "A3C", "PLAX", "PSAX"])
    raw = np.zeros((4, 7), dtype=np.float32)
    raw[:, 6] = 5.0  # TEE wins in the raw output
    recognizer = OnnxViewRecognizer(models_dir=models_dir, session=_fake_session(raw))
    result = recognizer.recognize(_frames(4))
    assert result.view == "A4C"


def test_recognize_uses_manifest_io_names(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir)
    logits = np.zeros((4, 7), dtype=np.float32)
    session = _fake_session(logits)
    recognizer = OnnxViewRecognizer(models_dir=models_dir, session=session)
    recognizer.recognize(_frames(4))
    session.run.assert_called_once()
    args = session.run.call_args.args
    assert args[0] == ["logits"]
    assert "input" in args[1]


def test_input_size_from_manifest(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir)
    recognizer = OnnxViewRecognizer(models_dir=models_dir, session=_fake_session(np.zeros((1, 7), dtype=np.float32)))
    assert recognizer.input_size == 224


def test_default_models_dir_falls_back_to_repo_models() -> None:
    default = vro._default_models_dir()
    assert default.name == "models"


def test_resolve_sha256_reads_active_model_entry(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir)
    manifest = json.loads((models_dir / "model_manifest.json").read_text(encoding="utf-8"))
    assert vro._resolve_sha256(manifest) == "deadbeef"


def test_verify_model_integrity_raises_on_mismatch(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    onnx_path = _write_manifest(models_dir)
    with pytest.raises(RuntimeError):
        vro._verify_model_integrity(onnx_path, "not-the-hash")


def test_verify_model_integrity_accepts_matching_sha(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    onnx_path = _write_manifest(models_dir)
    expected = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    # A matching checksum passes silently; the return is None.
    assert vro._verify_model_integrity(onnx_path, expected) is None


def test_verify_model_integrity_skips_when_no_expected_sha(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    onnx_path = _write_manifest(models_dir)
    # No expected hash -> integrity check is a no-op (returns None, no raise).
    assert vro._verify_model_integrity(onnx_path, None) is None


def test_recognize_uniform_logits_pick_first_class_with_low_confidence(
    tmp_path: Path,
) -> None:
    models_dir = tmp_path / "models"
    _write_manifest(models_dir)
    # All-zero logits -> uniform softmax; argmax picks the first class but
    # the confidence stays low (mean of an even distribution over 7 classes).
    logits = np.zeros((4, 7), dtype=np.float32)
    recognizer = OnnxViewRecognizer(models_dir=models_dir, session=_fake_session(logits))
    result = recognizer.recognize(_frames(4))
    assert result.view == "A4C"
    assert result.confidence < 0.3


@pytest.mark.parametrize("winner", ["RV_A4C", "SUBCOSTAL"])
def test_extended_model_sector_phase_input_and_ood(tmp_path: Path, winner: str) -> None:
    from echo_personal_tool.domain.models.view_recognition import EXTENDED_KNOWN_VIEWS
    from echo_personal_tool.domain.services.view_recognition_inference import (
        ViewInferenceConfig,
        prepare_clip_for_view_model,
    )

    _write_manifest(tmp_path, class_names=EXTENDED_KNOWN_VIEWS)
    path = tmp_path / "model_manifest.json"
    manifest = json.loads(path.read_text())
    cfg = ViewInferenceConfig.ml0b_default()
    manifest["view_recognition"].update(cfg.to_manifest_fields())
    path.write_text(json.dumps(manifest))
    logits = np.zeros((1, 9), dtype=np.float32)
    logits[0, EXTENDED_KNOWN_VIEWS.index(winner)] = 9.6
    session = _fake_session(logits)
    recognizer = OnnxViewRecognizer(models_dir=tmp_path, session=session)
    assert recognizer.recognize(_frames()).view == winner
    supplied = session.run.call_args.args[1]["input"]
    np.testing.assert_array_equal(supplied, prepare_clip_for_view_model(_frames(), config=cfg))
    session.run.return_value = [np.zeros((1, 9), dtype=np.float32)]
    assert recognizer.recognize(_frames()).view == "UNKNOWN"


@pytest.mark.parametrize("explicit", [False, True])
def test_extended_output_column_selection(tmp_path: Path, explicit: bool) -> None:
    from echo_personal_tool.domain.models.view_recognition import EXTENDED_KNOWN_VIEWS

    _write_manifest(tmp_path, class_names=["SUBCOSTAL", "RV_A4C"])
    trained = tuple(reversed(EXTENDED_KNOWN_VIEWS)) if explicit else EXTENDED_KNOWN_VIEWS
    if explicit:
        path = tmp_path / "model_manifest.json"
        manifest = json.loads(path.read_text())
        manifest["view_recognition"]["trained_class_names"] = list(trained)
        path.write_text(json.dumps(manifest))
    logits = np.zeros((1, 9), dtype=np.float32)
    logits[0, trained.index("RV_A4C")] = 5.0
    recognizer = OnnxViewRecognizer(models_dir=tmp_path, session=_fake_session(logits))
    assert recognizer.recognize(_frames()).view == "RV_A4C"
