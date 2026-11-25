"""ML.0b training/export metadata contracts; no torch or clinical data required."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from scripts.export_view_recognition_onnx import (
    MODEL_ID,
    build_view_manifest_section,
    load_contract,
    update_manifest,
)
from scripts.train_view_recognition import compute_effective_class_weights, resolve_active_class_names

from echo_personal_tool.domain.models.view_recognition import (
    EXTENDED_KNOWN_VIEWS,
    KNOWN_VIEWS,
    TTE_STANDARD_VIEWS,
    ViewRecognitionManifest,
    ViewRecognitionSample,
)
from echo_personal_tool.domain.services.view_recognition_inference import ViewInferenceConfig
from echo_personal_tool.infrastructure.view_recognition_dataset import ViewRecognitionDataset


def test_effective_class_weights_balance_rare_classes() -> None:
    weights = compute_effective_class_weights([100, 10, 1])
    assert weights[0] < weights[1] < weights[2]
    assert np.mean(weights) == pytest.approx(1.0)
    assert np.all(np.isfinite(compute_effective_class_weights([0, 0])))
    assert compute_effective_class_weights([12, 12]) == [1.0, 1.0]


@pytest.mark.parametrize(
    ("preset", "expected"),
    [("legacy7", KNOWN_VIEWS), ("tte7", TTE_STANDARD_VIEWS), ("extended9", EXTENDED_KNOWN_VIEWS)],
)
def test_training_class_presets(preset: str, expected: tuple[str, ...]) -> None:
    assert resolve_active_class_names([], preset) == list(expected)
    assert resolve_active_class_names(expected, "manifest") == list(expected)


def test_export_preserves_training_preprocessing_and_ood(tmp_path: Path) -> None:
    config = ViewInferenceConfig.ml0b_default(input_size=128)
    contract = {"input_size": 128, "head_type": "prototype", **config.to_manifest_fields()}
    (tmp_path / "io_contract.json").write_text(json.dumps(contract))
    assert load_contract(tmp_path) == contract
    section = build_view_manifest_section(class_names=list(EXTENDED_KNOWN_VIEWS), contract=contract)
    assert ViewInferenceConfig.from_manifest_section(section) == config
    assert section["head_type"] == "prototype"
    assert section["trained_class_names"] == list(EXTENDED_KNOWN_VIEWS)
    legacy = build_view_manifest_section(class_names=list(KNOWN_VIEWS))
    assert "preprocessing" not in legacy and "ood" not in legacy


def test_load_contract_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="io_contract.json"):
        load_contract(tmp_path)


def test_export_manifest_is_idempotent_and_keeps_other_models(tmp_path: Path) -> None:
    onnx = tmp_path / "classifier.onnx"
    onnx.write_bytes(b"test artifact")
    manifest_path = tmp_path / "model_manifest.json"
    manifest_path.write_text(json.dumps({"models": {"segmentation": {"status": "unchanged"}}}))
    config = ViewInferenceConfig.ml0b_default(input_size=128)
    for _ in range(2):
        update_manifest(
            onnx,
            class_names=list(EXTENDED_KNOWN_VIEWS),
            input_size=128,
            contract=config.to_manifest_fields(),
            manifest_path=manifest_path,
        )
    manifest = json.loads(manifest_path.read_text())
    assert manifest["models"]["segmentation"] == {"status": "unchanged"}
    slot = manifest["models"][MODEL_ID]
    assert slot["sha256"] == hashlib.sha256(onnx.read_bytes()).hexdigest()
    assert slot["onnx"]["input_shape"] == [1, 3, 128, 128]
    assert ViewInferenceConfig.from_manifest_section(manifest["view_recognition"]) == config


def test_extended_dataset_raw_intensity_and_label_order() -> None:
    manifest = ViewRecognitionManifest(
        samples=(ViewRecognitionSample("rv", "local.dcm", "RV_A4C", "train"),),
        class_names=EXTENDED_KNOWN_VIEWS,
    )
    frame = np.full((3, 16, 16, 3), 128, dtype=np.uint8)
    dataset = ViewRecognitionDataset(manifest, lambda _: frame, views=manifest.class_names, normalize=False)
    clip, label = dataset[0]
    assert label == EXTENDED_KNOWN_VIEWS.index("RV_A4C")
    np.testing.assert_array_equal(clip, frame)


def test_training_loader_keeps_raw_frames_and_filters_non_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import train_view_recognition as trainer

    manifest = ViewRecognitionManifest(
        class_names=("SUBCOSTAL", "RV_A4C"),
        samples=(
            ViewRecognitionSample("rv", "rv.dcm", "RV_A4C", "train"),
            ViewRecognitionSample("sc", "sc.dcm", "SUBCOSTAL", "val"),
            ViewRecognitionSample("ood", "other.dcm", "UNKNOWN", "train"),
            ViewRecognitionSample("tee", "tee.dcm", "TEE", "train"),
        ),
    )
    monkeypatch.setattr(trainer, "_require_torch", lambda: None)
    monkeypatch.setattr(trainer, "DataLoader", lambda dataset, **_kwargs: dataset)
    raw = np.full((4, 16, 16, 3), 128, dtype=np.uint8)
    dataset = trainer._make_loader("train", manifest, lambda _: raw, 2, 0, False)
    assert len(dataset) == 1
    clip, label = dataset[0]
    assert label == 1  # explicit manifest order, never legacy7
    np.testing.assert_array_equal(clip, raw)


def test_reexport_refreshes_old_slot_input_shape(tmp_path: Path) -> None:
    path = tmp_path / "model_manifest.json"
    path.write_text(json.dumps({"models": {MODEL_ID: {"filename": "old.onnx", "onnx": {}}}}))
    onnx = tmp_path / "new.onnx"
    onnx.write_bytes(b"new")
    update_manifest(onnx, input_size=128, class_names=["RV_A4C", "SUBCOSTAL"], manifest_path=path)
    slot = json.loads(path.read_text())["models"][MODEL_ID]
    assert slot["filename"] == "new.onnx"
    assert slot["onnx"]["input_shape"] == [1, 3, 128, 128]
    assert slot["onnx"]["output_shape"] == [1, 2]
