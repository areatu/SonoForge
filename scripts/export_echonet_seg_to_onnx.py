#!/usr/bin/env python3
"""Export EchoNet-Dynamic LV segmentation weights to ONNX.

Uses only the DeepLabV3-ResNet50 segmentation branch from EchoNet-Dynamic (MIT).
Does NOT export R2+1D / R3D video EF models.

Requirements (one-off export environment):
    pip install torch torchvision onnx onnxruntime

Usage:
    python scripts/export_echonet_seg_to_onnx.py
    python scripts/export_echonet_seg_to_onnx.py --weights models/deeplabv3_resnet50_random.pt
    python scripts/export_echonet_seg_to_onnx.py --quantize-int8 --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import torch
import torch.nn as nn
import torchvision

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "models"
MANIFEST_PATH = MODELS_DIR / "model_manifest.json"
DEFAULT_WEIGHTS_URL = (
    "https://github.com/echonet/dynamic/releases/download/v1.0.0/"
    "deeplabv3_resnet50_random.pt"
)
INPUT_SIZE = 112
MODEL_ID = "echonet_seg_resnet50"


class EchoNetSegmentationWrapper(nn.Module):
    """Wrap torchvision DeepLabV3 to return raw logits (B, 1, H, W)."""

    def __init__(self, backbone: nn.Module) -> None:
        super().__init__()
        self.backbone = backbone

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.backbone(x)["out"]


def build_deeplabv3_resnet50() -> nn.Module:
    """Create DeepLabV3-ResNet50 with 1-class head (EchoNet segmentation setup)."""
    try:
        model = torchvision.models.segmentation.deeplabv3_resnet50(
            weights=None, aux_loss=False
        )
    except TypeError:
        model = torchvision.models.segmentation.deeplabv3_resnet50(
            pretrained=False, aux_loss=False
        )

    classifier = model.classifier[-1]
    model.classifier[-1] = nn.Conv2d(
        classifier.in_channels,
        1,
        kernel_size=classifier.kernel_size,
    )
    return model


def load_state_dict(weights_path: Path) -> dict[str, torch.Tensor]:
    try:
        checkpoint = torch.load(weights_path, map_location="cpu", weights_only=False)
    except TypeError:
        checkpoint = torch.load(weights_path, map_location="cpu")

    if isinstance(checkpoint, dict) and "state_dict" in checkpoint:
        state_dict = checkpoint["state_dict"]
    elif isinstance(checkpoint, dict):
        # Raw state_dict saved without wrapper key
        if all(isinstance(v, torch.Tensor) for v in checkpoint.values()):
            state_dict = checkpoint
        else:
            raise ValueError(
                f"Unrecognized checkpoint format in {weights_path}. "
                "Expected key 'state_dict' or a flat state_dict."
            )
    else:
        raise ValueError(f"Unsupported checkpoint type: {type(checkpoint)}")

    cleaned: dict[str, torch.Tensor] = {}
    for key, value in state_dict.items():
        cleaned[key.removeprefix("module.")] = value
    return cleaned


def download_weights(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"Weights already present: {dest}")
        return
    print(f"Downloading weights from {url} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"Saved to {dest}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_onnx(
    model: nn.Module,
    output_path: Path,
    opset_version: int = 17,
) -> None:
    model.eval()
    wrapper = EchoNetSegmentationWrapper(model)
    dummy = torch.randn(1, 3, INPUT_SIZE, INPUT_SIZE)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapper,
        dummy,
        str(output_path),
        export_params=True,
        opset_version=opset_version,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={
            "input": {0: "batch"},
            "logits": {0: "batch"},
        },
    )
    print(f"ONNX exported: {output_path}")


def quantize_int8(onnx_path: Path, output_path: Path) -> None:
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except ImportError as exc:
        raise SystemExit(
            "onnxruntime is required for --quantize-int8. "
            "Install with: pip install onnxruntime"
        ) from exc

    quantize_dynamic(
        model_input=str(onnx_path),
        model_output=str(output_path),
        weight_type=QuantType.QUInt8,
    )
    print(f"INT8 ONNX exported: {output_path}")


def verify_onnx(onnx_path: Path) -> None:
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as exc:
        raise SystemExit(
            "Verification requires onnxruntime and numpy. "
            "Install with: pip install onnxruntime numpy"
        ) from exc

    session = ort.InferenceSession(
        str(onnx_path), providers=["CPUExecutionProvider"]
    )
    sample = np.random.randn(1, 3, INPUT_SIZE, INPUT_SIZE).astype(np.float32)
    outputs = session.run(None, {"input": sample})
    logits = outputs[0]
    print(
        f"Verification OK: logits shape={logits.shape}, "
        f"dtype={logits.dtype}, "
        f"range=[{logits.min():.3f}, {logits.max():.3f}]"
    )


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Manifest not found: {MANIFEST_PATH}")
    with MANIFEST_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest: dict) -> None:
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Manifest updated: {MANIFEST_PATH}")


def update_manifest_after_export(
    manifest: dict,
    onnx_path: Path,
    int8_path: Path | None,
) -> None:
    entry = manifest["models"][MODEL_ID]
    entry["status"] = "exported"
    entry["sha256"] = sha256_file(onnx_path)
    entry["file_size_bytes"] = onnx_path.stat().st_size
    entry["exported_at"] = datetime.now(UTC).isoformat()

    if int8_path and int8_path.exists():
        entry["sha256_int8"] = sha256_file(int8_path)
        entry["file_size_int8_bytes"] = int8_path.stat().st_size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export EchoNet-Dynamic DeepLabV3-ResNet50 segmentation to ONNX."
    )
    parser.add_argument(
        "--weights",
        type=Path,
        default=MODELS_DIR / "deeplabv3_resnet50_random.pt",
        help="Path to deeplabv3_resnet50_random.pt",
    )
    parser.add_argument(
        "--weights-url",
        default=DEFAULT_WEIGHTS_URL,
        help="URL to download weights if --weights is missing",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=MODELS_DIR / "echonet_seg_resnet50.onnx",
        help="Output ONNX path",
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=17,
        help="ONNX opset version",
    )
    parser.add_argument(
        "--quantize-int8",
        action="store_true",
        help="Also export dynamic INT8 quantized model (*_int8.onnx)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run onnxruntime smoke test after export",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Do not download weights; fail if --weights is missing",
    )
    parser.add_argument(
        "--no-update-manifest",
        action="store_true",
        help="Skip updating models/model_manifest.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.weights.exists():
        if args.no_download:
            print(f"Weights not found: {args.weights}", file=sys.stderr)
            return 1
        download_weights(args.weights_url, args.weights)

    print("Building DeepLabV3-ResNet50 (1-class head)...")
    model = build_deeplabv3_resnet50()
    state_dict = load_state_dict(args.weights)
    model.load_state_dict(state_dict, strict=True)
    print("Weights loaded successfully.")

    export_onnx(model, args.output, opset_version=args.opset)

    int8_path: Path | None = None
    if args.quantize_int8:
        int8_path = args.output.with_name(
            args.output.stem + "_int8" + args.output.suffix
        )
        quantize_int8(args.output, int8_path)

    if args.verify:
        verify_onnx(args.output)
        if int8_path and int8_path.exists():
            verify_onnx(int8_path)

    if not args.no_update_manifest:
        manifest = load_manifest()
        update_manifest_after_export(manifest, args.output, int8_path)
        save_manifest(manifest)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
