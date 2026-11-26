#!/usr/bin/env python3
"""Export the trained view-recognition classifier to ONNX (issue #639, #688 / ML.0b).

Loads the checkpoint produced by ``scripts/train_view_recognition.py``
(``model.pth`` + ``io_contract.json``), rebuilds the EfficientNet-B0
classifier (either cosine ``prototype`` head or legacy ``linear`` head),
exports ONNX, and records the train/serve ``preprocessing`` and ``ood``
metadata into ``models/model_manifest.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import torch
    import torch.nn as nn
except ImportError:  # pragma: no cover - optional heavy ML runtime
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]

try:
    from torchvision.models import efficientnet_b0

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


def _require_torch() -> None:
    if torch is None or nn is None:
        msg = "torch is required to export view-recognition ONNX"
        raise RuntimeError(msg)


def load_contract(checkpoint_dir: Path) -> dict[str, Any]:
    """Read ``io_contract.json`` from the checkpoint directory."""
    contract_path = checkpoint_dir / "io_contract.json"
    if not contract_path.is_file():
        msg = f"io_contract.json not found in {checkpoint_dir}"
        raise FileNotFoundError(msg)
    return json.loads(contract_path.read_text(encoding="utf-8"))


def build_model(contract: dict[str, Any]) -> Any:
    """Rebuild the classifier (prototype or linear head) from ``contract``."""
    _require_torch()
    if _BACKBONE_FACTORY is None:
        raise RuntimeError(
            "torchvision is required to rebuild the EfficientNet-B0 backbone; "
            "install torchvision before running this script"
        )
    from scripts.train_view_recognition import build_prototype_head

    num_classes = int(contract.get("num_classes", len(contract.get("class_names", []))))
    head_type = str(contract.get("head_type", "linear"))
    model = efficientnet_b0(weights=None)  # all weights are restored from the checkpoint
    classifier = model.classifier
    in_features = int(classifier[1].in_features)
    if head_type == "prototype":
        scale = float(contract.get("logit_scale", 12.0) or 12.0)
        classifier[1] = build_prototype_head(in_features, num_classes, init_scale=scale)
    else:
        classifier[1] = nn.Linear(in_features, num_classes)
    return model


def export_onnx(
    model: Any,
    output_path: Path,
    *,
    input_size: int = DEFAULT_INPUT_SIZE,
    opset: int = OPSET,
) -> None:
    _require_torch()

    class _ClassifierWrapper(nn.Module):  # type: ignore[misc]
        def __init__(self, inner: Any) -> None:
            super().__init__()
            self.model = inner

        def forward(self, x: Any) -> Any:
            return self.model(x)

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
    print(f"ONNX exported: {output_path} ({output_path.stat().st_size:,} bytes)")  # noqa: T201


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_view_manifest_section(
    *,
    class_names: list[str],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the ``view_recognition`` manifest section with ML.0b parity fields."""
    section: dict[str, Any] = {
        "active_model": MODEL_ID,
        "class_names": list(class_names),
        "trained_class_names": list(class_names),
    }
    if isinstance(contract, dict):
        for key in ("preprocessing", "logit_scale", "ood", "head_type"):
            if key in contract and contract[key] is not None:
                section[key] = contract[key]
    return section


def update_manifest(
    onnx_path: Path,
    *,
    input_size: int = DEFAULT_INPUT_SIZE,
    class_names: list[str],
    contract: dict[str, Any] | None = None,
    manifest_path: Path = MANIFEST_PATH,
) -> None:
    """Update the view-recognition model slot and ``view_recognition`` section."""
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")  # noqa: T201
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    models = manifest.setdefault("models", {})
    slot = models.setdefault(MODEL_ID, {})
    slot.update(
        {
            "id": MODEL_ID,
            "filename": onnx_path.name,
            "architecture": "efficientnet_b0",
            "description": "View-recognition classifier (EfficientNet-B0)",
            "status": "exported",
            "sha256": _sha256(onnx_path),
            "file_size_bytes": onnx_path.stat().st_size,
            "export_script": "scripts/export_view_recognition_onnx.py",
        }
    )
    slot.setdefault("onnx", {}).update(
        {
            "opset_version": OPSET,
            "input_name": INPUT_NAME,
            "output_name": OUTPUT_NAME,
            "input_shape": [1, 3, input_size, input_size],
            "output_shape": [1, len(class_names)],
            "output_type": "logits",
            "postprocess": "softmax_then_median_argmax_over_clip_with_ood",
        }
    )

    manifest["view_recognition"] = build_view_manifest_section(
        class_names=class_names,
        contract=contract,
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Manifest updated: {manifest_path}")  # noqa: T201


def verify_onnx(onnx_path: Path, input_size: int = DEFAULT_INPUT_SIZE) -> None:
    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime not installed, skipping verify")  # noqa: T201
        return
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    sample = np.random.randn(1, 3, input_size, input_size).astype(np.float32)
    outputs = session.run(None, {INPUT_NAME: sample})
    print(f"ONNX verify OK: output shape {outputs[0].shape}")  # noqa: T201


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--input-size", type=int, default=None)
    parser.add_argument("--no-manifest", action="store_true")
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _require_torch()
    args = _parse_args(argv)
    contract = load_contract(args.checkpoint)
    model = build_model(contract)
    state = torch.load(args.checkpoint / "model.pth", map_location="cpu")
    model.load_state_dict(state)
    input_size = int(contract.get("input_size", DEFAULT_INPUT_SIZE))
    if args.input_size is not None and args.input_size != input_size:
        raise ValueError("--input-size must match the training io_contract.json")
    export_onnx(model, args.output, input_size=input_size)
    if not args.no_manifest:
        update_manifest(
            args.output,
            input_size=input_size,
            class_names=list(contract.get("class_names", [])),
            contract=contract,
        )
    if args.verify:
        verify_onnx(args.output, input_size=input_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
