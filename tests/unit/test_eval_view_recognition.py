"""Tests for the view-recognition eval script (#639 step 2, step 5 metrics)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from echo_personal_tool.domain.models.view_recognition import KNOWN_VIEWS

MODEL_ID = "view_recognition_efficientnet_b0"


def _load_eval_module() -> object:
    """Load ``scripts/eval_view_recognition.py`` as an isolated module."""
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "eval_view_recognition.py"
    spec = importlib.util.spec_from_file_location("eval_view_recognition", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _write_manifest(manifest_path: Path, views: list[str]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    for i, view in enumerate(views):
        samples.append(
            {
                "sample_id": f"s{i}",
                "source_path": f"/fake/{i}.dcm",
                "view": view,
                "split": "test",
            }
        )
    data = {
        "schema_version": 2,
        "class_names": list(KNOWN_VIEWS),
        "samples": samples,
    }
    manifest_path.write_text(json.dumps(data), encoding="utf-8")


def _write_model(models_dir: Path) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = models_dir / "view_recognition_efficientnet_b0.onnx"
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
                "sha256": None,
            }
        },
        "view_recognition": {"active_model": MODEL_ID},
    }
    (models_dir / "model_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return onnx_path


def _fake_session(logits: np.ndarray) -> MagicMock:
    session = MagicMock()
    session.run.return_value = [logits]
    return session


def test_evaluate_reports_top1_and_per_class(tmp_path: Path) -> None:
    eval_mod = _load_eval_module()
    manifest_path = tmp_path / "view_recognition_manifest.json"
    models_dir = tmp_path / "models"
    _write_manifest(manifest_path, ["A4C", "A4C", "SAX", "PLAX"])
    _write_model(models_dir)

    # Model always predicts SAX (index 4).
    logits = np.zeros((8, 7), dtype=np.float32)
    logits[:, 4] = 5.0
    with patch(
        "echo_personal_tool.infrastructure.view_recognition_onnx._create_session",
        return_value=_fake_session(logits),
    ):
        report = eval_mod.evaluate(
            manifest_path=manifest_path,
            models_dir=models_dir,
            split="test",
            clip_provider=eval_mod._synthetic_clip_provider,
        )

    assert report["total"] == 4
    # Only the SAX sample is correct -> 1/4.
    assert abs(float(report["top1_accuracy"]) - 0.25) < 1e-9
    assert report["per_class_recall"]["SAX"] == 1.0
    assert report["per_class_recall"]["A4C"] == 0.0
    assert report["confusion"] == {
        ("A4C", "SAX"): 2,
        ("SAX", "SAX"): 1,
        ("PLAX", "SAX"): 1,
    }


def test_evaluate_raises_when_model_missing(tmp_path: Path) -> None:
    eval_mod = _load_eval_module()
    manifest_path = tmp_path / "view_recognition_manifest.json"
    _write_manifest(manifest_path, ["A4C"])

    try:
        eval_mod.evaluate(
            manifest_path=manifest_path,
            models_dir=tmp_path / "empty_models",
            split="test",
            clip_provider=eval_mod._synthetic_clip_provider,
        )
    except RuntimeError as exc:
        assert "not available" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when model is unavailable")
