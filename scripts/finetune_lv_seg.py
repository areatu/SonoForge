#!/usr/bin/env python3
"""Fine-tune EchoNet DeepLabV3-ResNet50 decoder on LV gold segmentation masks.

Loads gold contours from manifest + gold/lv_*.json, rasterizes to masks,
trains a light decoder head (frozen ResNet backbone), exports to ONNX.

Usage:
    python scripts/finetune_lv_seg.py --manifest manifest.json
    python scripts/finetune_lv_seg.py --manifest manifest.json --epochs 40 --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
sys.path.insert(0, str(PROJECT_ROOT / "src"))
MODELS_DIR = PROJECT_ROOT / "models"
MANIFEST_PATH = MODELS_DIR / "model_manifest.json"
DEFAULT_OUTPUT = MODELS_DIR / "echonet_seg_resnet50_finetuned.onnx"
INPUT_SIZE = 112
MODEL_ID = "echonet_seg_resnet50_finetuned"


def rasterize_polygon(
    points: list[list[float]],
    shape: tuple[int, int],
) -> np.ndarray:
    pts = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    mask = np.zeros(shape, dtype=np.uint8)
    closed = np.vstack([pts, pts[:1]])
    cv2.fillPoly(mask, [closed.astype(np.int32)], 1)
    return mask


def load_lv_samples(manifest_path: Path) -> list[dict]:
    """Load LV gold samples from manifest + gold directory."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    gold_dir = manifest_path.parent / "gold"
    samples: list[dict] = []

    for study in manifest.get("studies", []):
        study_id = study["study_id"]
        instance_path = study["instance_path"]
        gold_path = gold_dir / f"lv_{study_id}.json"
        if not gold_path.is_file():
            continue

        with open(gold_path) as f:
            gold = json.load(f)

        for phase_key, frame_key in [("ED", "ed_frame"), ("ES", "es_frame")]:
            frame_index = study.get(frame_key)
            if frame_index is None:
                continue

            # Find matching gold frame
            gold_frame = None
            for gf in gold.get("frames", []):
                if gf.get("phase") == phase_key and gf.get("frame_index") == frame_index:
                    gold_frame = gf
                    break
            if gold_frame is None:
                continue

            points = gold_frame.get("points", [])
            if len(points) < 3:
                continue

            samples.append({
                "instance_path": instance_path,
                "frame_index": frame_index,
                "phase": phase_key,
                "points": points,
            })

    return samples


def _resolve_frame(instance_path: str, frame_index: int) -> np.ndarray | None:
    try:
        from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
        reader = DicomReaderImpl()
        frame = reader.read_pixels(Path(instance_path), frame_index)
        if frame.ndim == 3 and frame.shape[2] == 3:
            frame = np.mean(frame[..., :3], axis=2)
        # Normalize to uint8 — DICOM pixels may not be in 0-255 range
        frame = frame.astype(np.float32)
        fmin, fmax = frame.min(), frame.max()
        if fmax > fmin:
            frame = (frame - fmin) / (fmax - fmin) * 255.0
        else:
            frame = np.zeros_like(frame)
        return frame.astype(np.uint8)
    except Exception:
        return None


class LVGoldDataset(torch.utils.data.Dataset):
    def __init__(self, samples: list[dict], input_size: int = INPUT_SIZE) -> None:
        self._input_size = input_size
        self._cache: list[tuple[np.ndarray, np.ndarray]] = []

        from echo_personal_tool.domain.services.segment_roi import resolve_segment_roi_xyxy
        from echo_personal_tool.domain.services.segmentation_service import crop_frame_for_echonet

        for s in samples:
            frame = _resolve_frame(s["instance_path"], s["frame_index"])
            if frame is None:
                continue
            h, w = frame.shape[:2]
            mask = rasterize_polygon(s["points"], (h, w))
            roi_xyxy = resolve_segment_roi_xyxy(
                frame, media_format="dicom", instance_path=Path(s["instance_path"]),
            )
            cropped_frame, transform = crop_frame_for_echonet(
                frame, roi_xyxy=roi_xyxy, crop_mode="center_square",
            )
            cropped_mask = mask[
                transform.crop_y0 : transform.crop_y0 + transform.crop_height,
                transform.crop_x0 : transform.crop_x0 + transform.crop_width,
            ]
            self._cache.append((cropped_frame, cropped_mask))

    def __len__(self) -> int:
        return len(self._cache)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        frame, mask = self._cache[idx]
        frame_r = cv2.resize(frame, (self._input_size, self._input_size), interpolation=cv2.INTER_CUBIC)
        mask_r = cv2.resize(mask, (self._input_size, self._input_size), interpolation=cv2.INTER_NEAREST)
        frame_t = torch.from_numpy(frame_r).float().unsqueeze(0) / 255.0
        frame_t = frame_t.expand(3, -1, -1)
        mask_t = torch.from_numpy(mask_r).float().unsqueeze(0)
        return frame_t, mask_t


def augment_pair(
    frame: torch.Tensor, mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    if random.random() > 0.5:
        frame = torch.flip(frame, dims=[2])
        mask = torch.flip(mask, dims=[2])
    if random.random() > 0.5:
        gamma = random.uniform(0.7, 1.5)
        frame = frame.clamp(min=1e-6).pow(gamma)
    if random.random() > 0.5:
        noise = torch.randn_like(frame) * 0.05
        frame = (frame + noise * frame).clamp(0.0, 1.0)
    return frame, mask


def bce_dice_loss(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    bce = F.binary_cross_entropy_with_logits(logits, target)
    probs = torch.sigmoid(logits)
    intersection = (probs * target).sum(dim=(1, 2, 3))
    cardinality = probs.sum(dim=(1, 2, 3)) + target.sum(dim=(1, 2, 3))
    dice = 1.0 - (2.0 * intersection + 1.0) / (cardinality + 1.0)
    return bce + dice.mean()


def build_model() -> nn.Module:
    # ImageNet-pretrained backbone
    try:
        model = torchvision.models.segmentation.deeplabv3_resnet50(
            weights="DEFAULT",
        )
    except TypeError:
        model = torchvision.models.segmentation.deeplabv3_resnet50(
            pretrained=True,
        )
    # Replace classifier: 21-class → 1-class with positive bias (encourage foreground)
    classifier = model.classifier[-1]
    new_conv = nn.Conv2d(
        classifier.in_channels, 1, kernel_size=classifier.kernel_size,
    )
    nn.init.zeros_(new_conv.bias)
    nn.init.constant_(new_conv.bias, 1.0)  # positive bias → sigmoid(1)≈0.73 initially
    model.classifier[-1] = new_conv

    # Freeze backbone, train only classifier head (ASPP + new 1-class conv)
    for param in model.parameters():
        param.requires_grad = False
    for param in model.classifier.parameters():
        param.requires_grad = True

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Model: {trainable:,} trainable / {total:,} total params (classifier only)")
    return model


def train_model(
    model: nn.Module,
    dataset: LVGoldDataset,
    *,
    epochs: int = 40,
    batch_size: int = 8,
    lr: float = 1e-4,
    device: str = "cpu",
) -> None:
    if len(dataset) == 0:
        print("ERROR: No training samples")
        sys.exit(1)

    loader = torch.utils.data.DataLoader(
        dataset, batch_size=batch_size, shuffle=True,
        drop_last=len(dataset) >= batch_size,
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
            frames, masks = frames.to(device), masks.to(device)
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
            print(f"  Epoch {epoch:3d}/{epochs}: loss={avg:.4f}", flush=True)

    print("Training complete.")


class _Wrapper(nn.Module):
    def __init__(self, backbone: nn.Module) -> None:
        super().__init__()
        self.backbone = backbone

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.backbone(x)["out"]


def export_onnx(model: nn.Module, output_path: Path, input_size: int = INPUT_SIZE) -> None:
    model.cpu()
    model.eval()
    wrapper = _Wrapper(model)
    dummy = torch.randn(1, 3, input_size, input_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapper, dummy, str(output_path),
        export_params=True, opset_version=17,
        do_constant_folding=True,
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
    )
    print(f"ONNX exported: {output_path} ({output_path.stat().st_size:,} bytes)")


def verify_onnx(onnx_path: Path, input_size: int = INPUT_SIZE) -> None:
    try:
        import onnxruntime as ort
    except ImportError:
        return
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    sample = np.random.randn(1, 3, input_size, input_size).astype(np.float32)
    logits = session.run(None, {"input": sample})[0]
    print(f"Verify OK: shape={logits.shape}, range=[{logits.min():.3f}, {logits.max():.3f}]")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fine-tune LV segmentation decoder")
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "manifest.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    print(f"Loading LV gold from {args.manifest} ...")
    samples = load_lv_samples(args.manifest)
    print(f"Found {len(samples)} LV samples (ED+ES)")

    dataset = LVGoldDataset(samples, input_size=INPUT_SIZE)
    print(f"Training samples: {len(dataset)}")

    model = build_model()
    train_model(model, dataset, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr, device=args.device)
    export_onnx(model, args.output, input_size=INPUT_SIZE)

    if args.verify:
        verify_onnx(args.output, input_size=INPUT_SIZE)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
