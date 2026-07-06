#!/usr/bin/env python3
"""Fine-tune EchoNet DeepLabV3-ResNet50 on LA gold segmentation masks.

Reads LA gold JSON files, rasterizes contours to binary masks, trains a
light decoder head (frozen ResNet backbone), and exports to ONNX.

Requirements:
    pip install torch torchvision onnx numpy scipy opencv-python-headless

Usage:
    python scripts/finetune_la_seg.py --gold-root /path/to/gold
    python scripts/finetune_la_seg.py --gold-root /path/to/gold --epochs 40
    python scripts/finetune_la_seg.py --gold-root /path/to/gold --verify
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "models"
MANIFEST_PATH = MODELS_DIR / "model_manifest.json"
DEFAULT_OUTPUT = MODELS_DIR / "echonet_la_resnet50_224.onnx"
INPUT_SIZE = 224
MODEL_ID = "echonet_la_resnet50_224"


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def rasterize_polygon(
    points: list[list[float]],
    shape: tuple[int, int],
) -> np.ndarray:
    """Rasterize open-arc contour to filled binary mask."""
    pts = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    mask = np.zeros(shape, dtype=np.uint8)
    # Close the polygon for fillPoly
    closed = np.vstack([pts, pts[:1]])
    cv2.fillPoly(mask, [closed.astype(np.int32)], 1)
    return mask


def load_la_gold(gold_root: Path) -> list[dict]:
    """Load all LA gold JSON files from gold_root/gold/la_*.json."""
    gold_dir = gold_root / "gold"
    if not gold_dir.is_dir():
        msg = f"gold directory not found: {gold_dir}"
        raise FileNotFoundError(msg)

    studies = []
    for path in sorted(gold_dir.glob("la_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  SKIP {path.name}: {exc}")
            continue
        if data.get("chamber", "").upper() != "LA":
            continue
        studies.append(data)
    return studies


def _resolve_dicom_frame(
    instance_path: str,
    frame_index: int,
) -> np.ndarray | None:
    """Load a single DICOM frame as grayscale uint8. Returns None on failure."""
    try:
        import pydicom
    except ImportError:
        return None

    try:
        ds = pydicom.dcmread(instance_path, stop_before_pixels=True)
        pixel_array = pydicom.dcmread(instance_path).pixel_array
    except Exception:
        return None

    if pixel_array.ndim == 3:
        # Multi-frame: select frame_index
        if frame_index < pixel_array.shape[0]:
            frame = pixel_array[frame_index]
        else:
            frame = pixel_array[-1]
    else:
        frame = pixel_array

    # Normalize to uint8
    frame = frame.astype(np.float32)
    fmin, fmax = frame.min(), frame.max()
    if fmax > fmin:
        frame = (frame - fmin) / (fmax - fmin) * 255.0
    else:
        frame = np.zeros_like(frame)
    return frame.astype(np.uint8)


class LaGoldDataset(torch.utils.data.Dataset):
    """Dataset of (frame, mask) pairs from LA gold annotations."""

    def __init__(
        self,
        studies: list[dict],
        *,
        input_size: int = INPUT_SIZE,
    ) -> None:
        self._samples: list[dict] = []
        self._input_size = input_size
        for study in studies:
            instance_path = study.get("instance_path", "")
            for frame in study.get("frames", []):
                if frame.get("chamber", "").upper() != "LA":
                    continue
                points = frame.get("points", [])
                if len(points) < 3:
                    continue
                self._samples.append(
                    {
                        "instance_path": instance_path,
                        "frame_index": frame.get("frame_index", 0),
                        "points": points,
                        "mitral_annulus": frame.get("mitral_annulus"),
                        "pixel_spacing_mm": study.get("pixel_spacing_mm", [0.15, 0.15]),
                    }
                )

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        sample = self._samples[idx]
        frame = _resolve_dicom_frame(sample["instance_path"], sample["frame_index"])
        if frame is None:
            # Fallback: synthetic noise frame
            frame = np.random.randint(0, 256, (224, 224), dtype=np.uint8)

        h, w = frame.shape[:2]
        mask = rasterize_polygon(sample["points"], (h, w))

        # Resize to input_size
        frame_resized = cv2.resize(frame, (self._input_size, self._input_size), interpolation=cv2.INTER_CUBIC)
        mask_resized = cv2.resize(mask, (self._input_size, self._input_size), interpolation=cv2.INTER_NEAREST)

        # To float tensors
        frame_t = torch.from_numpy(frame_resized).float().unsqueeze(0) / 255.0
        frame_t = frame_t.expand(3, -1, -1)  # grayscale → 3ch
        mask_t = torch.from_numpy(mask_resized).float().unsqueeze(0)

        return frame_t, mask_t


# ---------------------------------------------------------------------------
# Augmentation
# ---------------------------------------------------------------------------

def augment_pair(
    frame: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Random horizontal flip + gamma + speckle noise (no vertical flip)."""
    # Horizontal flip (A4C-safe)
    if random.random() > 0.5:
        frame = torch.flip(frame, dims=[2])
        mask = torch.flip(mask, dims=[2])

    # Gamma correction
    if random.random() > 0.5:
        gamma = random.uniform(0.7, 1.5)
        frame = frame.clamp(min=1e-6).pow(gamma)

    # Speckle noise
    if random.random() > 0.5:
        noise = torch.randn_like(frame) * 0.05
        frame = (frame + noise * frame).clamp(0.0, 1.0)

    return frame, mask


# ---------------------------------------------------------------------------
# Loss: BCE + Dice
# ---------------------------------------------------------------------------

def bce_dice_loss(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Combined BCE + Dice loss for binary segmentation."""
    bce = F.binary_cross_entropy_with_logits(logits, target)
    probs = torch.sigmoid(logits)
    intersection = (probs * target).sum(dim=(1, 2, 3))
    cardinality = probs.sum(dim=(1, 2, 3)) + target.sum(dim=(1, 2, 3))
    dice = 1.0 - (2.0 * intersection + 1.0) / (cardinality + 1.0)
    return bce + dice.mean()


# ---------------------------------------------------------------------------
# Model: frozen backbone + trainable decoder head
# ---------------------------------------------------------------------------

def build_la_model() -> nn.Module:
    """DeepLabV3-ResNet50 with frozen backbone, trainable 1-class head."""
    try:
        model = torchvision.models.segmentation.deeplabv3_resnet50(
            weights=None, aux_loss=False
        )
    except TypeError:
        model = torchvision.models.segmentation.deeplabv3_resnet50(
            pretrained=False, aux_loss=False
        )

    # Replace classifier head
    classifier = model.classifier[-1]
    model.classifier[-1] = nn.Conv2d(
        classifier.in_channels, 1, kernel_size=classifier.kernel_size,
    )

    # Freeze backbone
    for param in model.backbone.parameters():
        param.requires_grad = False
    for param in model.classifier[:-1].parameters():
        param.requires_grad = False

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Model: {trainable:,} trainable / {total:,} total params")

    return model


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train(
    model: nn.Module,
    dataset: LaGoldDataset,
    *,
    epochs: int = 40,
    batch_size: int = 4,
    lr: float = 1e-4,
    device: str = "cpu",
) -> None:
    """Train the decoder head on LA gold masks."""
    if len(dataset) == 0:
        print("ERROR: No training samples found. Need ≥1 LA gold file.")
        sys.exit(1)

    loader = torch.utils.data.DataLoader(
        dataset, batch_size=batch_size, shuffle=True, drop_last=False,
    )
    optimizer = torch.optim.Adam(
        filter(lambda p: p.requires_grad, model.parameters()), lr=lr,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    model.to(device)
    model.train()

    print(f"Training: {len(dataset)} samples, {epochs} epochs, lr={lr}")
    for epoch in range(1, epochs + 1):
        total_loss = 0.0
        n_batches = 0
        for frames, masks in loader:
            frames = frames.to(device)
            masks = masks.to(device)

            # Augment
            frames_aug, masks_aug = augment_pair(frames, masks)

            optimizer.zero_grad()
            output = model(frames_aug)["out"]
            loss = bce_dice_loss(output, masks_aug)
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        scheduler.step()
        avg = total_loss / max(n_batches, 1)
        if epoch % 5 == 0 or epoch == 1:
            print(f"  Epoch {epoch:3d}/{epochs}: loss={avg:.4f}")

    print("Training complete.")


# ---------------------------------------------------------------------------
# ONNX export
# ---------------------------------------------------------------------------

class _Wrapper(nn.Module):
    def __init__(self, backbone: nn.Module) -> None:
        super().__init__()
        self.backbone = backbone

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.backbone(x)["out"]


def export_onnx(
    model: nn.Module,
    output_path: Path,
    *,
    input_size: int = INPUT_SIZE,
    opset: int = 17,
) -> None:
    model.eval()
    wrapper = _Wrapper(model)
    dummy = torch.randn(1, 3, input_size, input_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapper, dummy, str(output_path),
        export_params=True, opset_version=opset,
        do_constant_folding=True,
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
    )
    print(f"ONNX exported: {output_path} ({output_path.stat().st_size:,} bytes)")


def update_manifest(onnx_path: Path) -> None:
    """Add LA model slot to model_manifest.json."""
    if not MANIFEST_PATH.exists():
        print(f"Manifest not found: {MANIFEST_PATH}")
        return
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    models = manifest.setdefault("models", {})
    if MODEL_ID not in models:
        models[MODEL_ID] = {
            "id": MODEL_ID,
            "filename": onnx_path.name,
            "architecture": "deeplabv3_resnet50",
            "description": "LA cavity segmentation A4C ES (fine-tuned)",
            "onnx": {
                "opset_version": 17,
                "input_name": "input",
                "output_name": "logits",
                "input_shape": [1, 3, input_size, input_size],
                "output_shape": [1, 1, input_size, input_size],
                "output_type": "logits",
                "postprocess": "sigmoid_then_threshold_0.5",
            },
            "status": "exported",
            "sha256": _sha256(onnx_path),
            "file_size_bytes": onnx_path.stat().st_size,
            "export_script": "scripts/finetune_la_seg.py",
        }
    else:
        models[MODEL_ID]["sha256"] = _sha256(onnx_path)
        models[MODEL_ID]["file_size_bytes"] = onnx_path.stat().st_size
        models[MODEL_ID]["status"] = "exported"

    # Add la_inference config if missing
    if "la_inference" not in manifest:
        manifest["la_inference"] = {
            "active_model": MODEL_ID,
            "crop_mode": "full_roi",
            "auto_refine_after_segment": True,
        }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Manifest updated: {MANIFEST_PATH}")


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_onnx(onnx_path: Path, input_size: int = INPUT_SIZE) -> None:
    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime not installed, skipping verify")
        return
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    sample = np.random.randn(1, 3, input_size, input_size).astype(np.float32)
    outputs = session.run(None, {"input": sample})
    logits = outputs[0]
    print(
        f"Verify OK: shape={logits.shape}, "
        f"range=[{logits.min():.3f}, {logits.max():.3f}]"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fine-tune LA segmentation + ONNX export")
    p.add_argument("--gold-root", type=Path, required=True, help="Gold dataset root")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="ONNX output path")
    p.add_argument("--epochs", type=int, default=40, help="Training epochs")
    p.add_argument("--batch-size", type=int, default=4, help="Batch size")
    p.add_argument("--lr", type=float, default=1e-4, help="Learning rate")
    p.add_argument("--input-size", type=int, default=INPUT_SIZE, help="Model input size")
    p.add_argument("--verify", action="store_true", help="Verify ONNX after export")
    p.add_argument("--no-manifest", action="store_true", help="Skip manifest update")
    p.add_argument("--device", default="cpu", help="Device (cpu/cuda)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    print(f"Loading LA gold from {args.gold_root} ...")
    studies = load_la_gold(args.gold_root)
    print(f"Found {len(studies)} LA gold studies")

    if not studies:
        print("No LA gold data found. Collect gold annotations first.")
        return 1

    dataset = LaGoldDataset(studies, input_size=args.input_size)
    print(f"Training samples: {len(dataset)}")

    print("Building model ...")
    model = build_la_model()

    train(
        model, dataset,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        device=args.device,
    )

    export_onnx(model, args.output, input_size=args.input_size)

    if args.verify:
        verify_onnx(args.output, input_size=args.input_size)

    if not args.no_manifest:
        update_manifest(args.output)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
