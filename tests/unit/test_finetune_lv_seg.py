"""Regression coverage for the ML.0a/A2C trainer merge; no torch or DICOM decoding."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from scripts import finetune_lv_seg as trainer


def test_parser_combines_ml0a_and_a2c_options(tmp_path: Path) -> None:
    args = trainer.parse_args(
        [
            "--view",
            "A2C",
            "--gold-dir",
            str(tmp_path),
            "--backbone-init",
            "manifest",
            "--weights",
            str(tmp_path / "encoder.pt"),
            "--val-ratio",
            "0.25",
            "--seed",
            "7",
            "--epochs",
            "2",
            "--batch-size",
            "3",
            "--lr",
            "0.002",
            "--verify",
            "--update-manifest",
        ]
    )
    assert args.view == "A2C" and args.gold_dir == tmp_path
    assert args.backbone_init == "manifest" and args.weights == tmp_path / "encoder.pt"
    assert args.val_ratio == pytest.approx(0.25) and args.seed == 7
    assert args.epochs == 2 and args.batch_size == 3 and args.lr == pytest.approx(0.002)
    assert args.verify and args.update_manifest
    assert args.output is None


def test_trainer_has_one_definition_per_top_level_name() -> None:
    tree = ast.parse(Path(trainer.__file__).read_text(encoding="utf-8"))
    names = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
    assert len(names) == len(set(names)), "merge must not leave shadowed loaders or entry points"


@pytest.mark.parametrize("use_manifest", [True, False])
def test_loader_keeps_view_filter_and_study_groups(tmp_path: Path, use_manifest: bool) -> None:
    manifest_path = tmp_path / "manifest.json"
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir()
    if use_manifest:
        manifest_path.write_text(
            json.dumps(
                {
                    "studies": [
                        {
                            "study_id": "one",
                            "study_uid": "study-uid",
                            "instance_path": "cine.dcm",
                            "ed_frame": 0,
                            "es_frame": 2,
                        }
                    ]
                }
            )
        )
    frames = [
        {"view": view, "phase": phase, "frame_index": index, "points": [[1, 1], [2, 1], [1, 2]]}
        for view in ("A4C", "A2C")
        for phase, index in (("ED", 0), ("ES", 2))
    ]
    (gold_dir / "lv_one.json").write_text(
        json.dumps(
            {
                "study_uid": "study-uid",
                "instance_path": "cine.dcm",
                "frames": frames,
            }
        )
    )
    selected = trainer.load_lv_samples(manifest_path, view="A2C", gold_dir=gold_dir)
    assert len(selected) == 2 and {s["view"] for s in selected} == {"A2C"}
    assert {s["study_id"] for s in selected} == {"one"}
    assert {s["study_uid"] for s in selected} == {"study-uid"}
    assert {s["phase"] for s in selected} == {"ED", "ES"}
    assert {s["instance_path"] for s in selected} == {"cine.dcm"}


@pytest.mark.parametrize("view", ["A4C", "A2C", "ALL"])
def test_main_trains_once_and_routes_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    view: str,
) -> None:
    samples = [{"study_id": study, "frame_index": frame} for study, frame in (("a", 0), ("a", 1), ("b", 0))]
    loader = MagicMock(return_value=samples)
    dataset = MagicMock(side_effect=lambda *_args, **_kwargs: MagicMock())
    model = object()
    build = MagicMock(return_value=model)
    train = MagicMock()
    export = MagicMock()
    verify = MagicMock()
    update = MagicMock()
    for name, fake in {
        "load_lv_samples": loader,
        "LVGoldDataset": dataset,
        "build_model": build,
        "train_model": train,
        "export_onnx": export,
        "verify_onnx": verify,
        "update_model_manifest": update,
    }.items():
        monkeypatch.setattr(trainer, name, fake)
    monkeypatch.setattr(trainer, "resolve_manifest_normalization", lambda *_args: (None, None))
    manifest_path = tmp_path / "manifest.json"
    assert (
        trainer.main(
            [
                "--manifest",
                str(manifest_path),
                "--gold-dir",
                str(tmp_path),
                "--view",
                view,
                "--val-ratio",
                "0.5",
                "--epochs",
                "2",
                "--verify",
                "--update-manifest",
            ]
        )
        == 0
    )
    loader.assert_called_once_with(manifest_path, view=view, gold_dir=tmp_path)
    build.assert_called_once_with(backbone_init="manifest", weights_path=trainer.DEFAULT_WEIGHTS)
    assert train.call_count == 1 and train.call_args.args[0] is model
    assert train.call_args.kwargs["epochs"] == 2
    assert dataset.call_count == 2
    train_samples, val_samples = (call.args[0] for call in dataset.call_args_list)
    assert train_samples and val_samples
    assert {s["study_id"] for s in train_samples}.isdisjoint(s["study_id"] for s in val_samples)
    expected_path = trainer.DEFAULT_A2C_OUTPUT if view == "A2C" else trainer.DEFAULT_OUTPUT
    expected_id = trainer.A2C_MODEL_ID if view == "A2C" else trainer.MODEL_ID
    export.assert_called_once_with(model, expected_path, input_size=trainer.INPUT_SIZE)
    verify.assert_called_once_with(expected_path, input_size=trainer.INPUT_SIZE)
    update.assert_called_once_with(expected_path, model_id=expected_id)


def test_dataset_caches_roi_and_uses_shared_preprocessing(monkeypatch: pytest.MonkeyPatch) -> None:
    rgb = np.full((16, 16, 3), 128, dtype=np.uint8)
    monkeypatch.setattr(trainer, "_resolve_frame", lambda *_args: rgb)
    monkeypatch.setattr(trainer, "try_parse_from_path", lambda *_args: None)
    monkeypatch.setattr(trainer, "resolve_segment_roi_xyxy", lambda *_args, **_kwargs: (0, 0, 16, 16))
    monkeypatch.setattr(trainer, "_require_torch", lambda: None)
    torch = MagicMock()
    torch.from_numpy.side_effect = lambda arr: arr
    monkeypatch.setattr(trainer, "torch", torch)
    dataset = trainer.LVGoldDataset(
        [{"instance_path": "cine.dcm", "frame_index": 0, "points": [[2, 2], [10, 2], [6, 10]]}], input_size=8
    )
    tensor, mask = dataset[0]
    assert len(dataset) == 1
    assert tensor.shape == (3, 8, 8) and mask.shape == (1, 8, 8)
    assert tensor.dtype == np.float32 and np.isfinite(tensor).all()
    assert np.count_nonzero(mask) > 0


def test_manifest_update_hashes_correct_a2c_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "a2c.onnx"
    artifact.write_bytes(b"local test artifact")
    path = tmp_path / "model_manifest.json"
    path.write_text(json.dumps({"models": {"other": {"status": "unchanged"}}}))
    trainer.update_model_manifest(artifact, trainer.A2C_MODEL_ID, manifest_path=path)
    models = json.loads(path.read_text())["models"]
    assert models["other"] == {"status": "unchanged"}
    assert models[trainer.A2C_MODEL_ID]["filename"] == artifact.name
    assert models[trainer.A2C_MODEL_ID]["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
