#!/usr/bin/env python3
"""Export the trained view-recognition classifier to ONNX (#639 step 2).

Loads the checkpoint produced by ``scripts/train_view_recognition.py``
(``model.pth`` + ``io_contract.json``), rebuilds the EfficientNet-B0
classifier, and exports it to ONNX with the same I/O contract the
:class:`OnnxViewRecognizer` adapter expects: input name ``input``, output
name ``logits``, opset 17 and a dynamic batch axis.

Requirements:
    pip install torch torchvision onnx onnxruntime numpy

Usage:
    python scripts/export_view_recognition_onnx.py --checkpoint models/view_recognition
    python scripts/export_view_recognition_onnx.py --checkpoint models/view_recognition --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

    _BACKBONE_FACTORY = "torchvision"
except ImportError:  # pragma: no cover - depends on installed extras
    _BACKBONE_FACTORY = None

MODELS_DIR = PROJECT_ROOT / "models"
MANIFEST_PATH = MODELS_DIR / "model_manifest.json"
DEFAULT_OUTPUT = MODELS_DIR / "view_recognition_efficientnet_b0.onnx"
MODEL_ID = "view_recognition_efficientnet_b0"
DEFAULT_INPUT_SIZE = 224
OPSET = 17
INPUT_NAME = "input"
OUTPUT_NAME = "logits"


class _ClassifierWrapper(nn.Module):
    """Wrap the EfficientNet-B0 classifier so its forward returns raw logits."""

    def __init__(self, model: nn.Module) -> None:
        super().__init__()
        self.model = model

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.model(x)


def load_contract(checkpoint_dir: Path) -> dict:
    """Read ``io_contract.json`` from the checkpoint directory."""
    contract_path = checkpoint_dir / "io_contract.json"
    if not contract_path.is_file():
        msg = f"io_contract.json not found in {checkpoint_dir}"
        raise FileNotFoundError(msg)
    return json.loads(contract_path.read_text(encoding="utf-8"))


def build_model(contract: dict) -> nn.Module:
    """Rebuild the classifier from the contract's class count."""
    if _BACKBONE_FACTORY is None:
        raise RuntimeError(
            "torchvision is required to rebuild the EfficientNet-B0 backbone; "
            "install torchvision before running this script"
        )
    num_classes = int(contract.get("num_classes", len(contract.get("class_names", []))))
    model = efficientnet_b0(weights=EfficientNet_B0_Weights.DEFAULT)
    classifier = model.classifier
    in_features = classifier[1].in_features
    classifier[1] = nn.Linear(in_features, num_classes)
    return model


def export_onnx(
    model: nn.Module,
    output_path: Path,
    *,
    input_size: int = DEFAULT_INPUT_SIZE,
    opset: int = OPSET,
) -> None:
    model.eval()
    wrapper = _ClassifierWrapper(model)
    dummy = torch.randn(1, 3, input_size, input_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapper,
        dummy,
        str(output_path),
        export_params=True,
        opset_version=opset,
        do_constant_folding=True,
        input_names=[INPUT_NAME],
        output_names=[OUTPUT_NAME],
        dynamic_axes={INPUT_NAME: {0: "batch"}, OUTPUT_NAME: {0: "batch"}},
    )
    print(f"ONNX exported: {output_path} ({output_path.stat().st_size:,} bytes)")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def update_manifest(
    onnx_path: Path,
    *,
    input_size: int = DEFAULT_INPUT_SIZE,
    class_names: list[str],
) -> None:
    """Add the view-recognition model slot and ``view_recognition`` section."""
    if not MANIFEST_PATH.exists():
        print(f"Manifest not found: {MANIFEST_PATH}")
        return
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    models = manifest.setdefault("models", {})
    if MODEL_ID not in models:
        models[MODEL_ID] = {
            "id": MODEL_ID,
            "filename": onnx_path.name,
            "architecture": "efficientnet_b0",
            "description": "View-recognition classifier (EfficientNet-B0 fine-tuned)",
            "onnx": {
                "opset_version": OPSET,
                "input_name": INPUT_NAME,
                "output_name": OUTPUT_NAME,
                "input_shape": [1, 3, input_size, input_size],
                "output_shape": [1, "num_classes"],
                "output_type": "logits",
                "postprocess": "softmax_then_mean_argmax_over_clip",
            },
            "status": "exported",
            "sha256": _sha256(onnx_path),
            "file_size_bytes": onnx_path.stat().st_size,
            "export_script": "scripts/export_view_recognition_onnx.py",
        }
    else:
        models[MODEL_ID]["sha256"] = _sha256(onnx_path)
        models[MODEL_ID]["file_size_bytes"] = onnx_path.stat().st_size
        models[MODEL_ID]["status"] = "exported"

    if "view_recognition" not in manifest:
        manifest["view_recognition"] = {
            "active_model": MODEL_ID,
            "class_names": class_names,
        }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Manifest updated: {MANIFEST_PATH}")


def verify_onnx(onnx_path: Path, input_size: int = DEFAULT_INPUT_SIZE) -> None:
    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime not installed, skipping verify")
        return
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    sample = np.random.randn(1, 3, input_size, input_size).astype(np.float32)
    outputs = session.run(None, {INPUT_NAME: sample})
    print(f"ONNX verify OK: output shape {outputs[0].shape}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--input-size", type=int, default=DEFAULT_INPUT_SIZE)
    parser.add_argument("--no-manifest", action="store_true")
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    contract = load_contract(args.checkpoint)
    model = build_model(contract)
    state = torch.load(args.checkpoint / "model.pth", map_location="cpu")
    model.load_state_dict(state)
    export_onnx(model, args.output, input_size=args.input_size)
    if not args.no_manifest:
        update_manifest(
            args.output,
            input_size=args.input_size,
            class_names=list(contract.get("class_names", [])),
        )
    if args.verify:
        verify_onnx(args.output, input_size=args.input_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
