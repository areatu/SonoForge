#!/usr/bin/env python3
"""Train 2-point heatmap regressor for mitral annulus landmark detection.

Exports: models/ma_landmark_224.onnx
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import cv2
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset

_CROP_SIZE = 224
_HEATMAP_SIGMA = 5.0
_NUM_KEYPOINTS = 2  # septal, lateral


def _make_heatmap(
    size: int,
    center: tuple[float, float],
    sigma: float,
) -> np.ndarray:
    """Generate a single Gaussian heatmap centered at (cx, cy)."""
    cx, cy = center
    yy, xx = np.mgrid[:size, :size].astype(np.float32)
    heatmap = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
    return heatmap


def _extract_training_samples(
    manifest_path: Path,
    gold_dir: Path,
) -> list[dict]:
    """Extract (frame, septal_xy, lateral_xy) samples from manifest + gold."""
    from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl

    with open(manifest_path) as f:
        manifest = json.load(f)

    reader = DicomReaderImpl()
    samples: list[dict] = []

    for study in manifest["studies"]:
        study_id = study["study_id"]
        instance_path = Path(study["instance_path"])
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

            ma = gold_frame.get("mitral_annulus")
            if ma is None:
                continue

            try:
                frame = reader.read_pixels(instance_path, frame_index)
            except Exception:
                continue

            gray = frame if frame.ndim == 2 else np.mean(frame[..., :3], axis=2).astype(np.uint8)

            septal = (float(ma[0][0]), float(ma[0][1]))
            lateral = (float(ma[1][0]), float(ma[1][1]))

            samples.append({
                "frame": gray,
                "septal": septal,
                "lateral": lateral,
                "study_id": study_id,
                "phase": phase_key,
            })

    return samples


class MADataset(Dataset):
    """Cropped annulus landmark dataset."""

    def __init__(self, samples: list[dict], crop_size: int = _CROP_SIZE) -> None:
        self.crop_size = crop_size
        self.data = self._prepare(samples)

    def _prepare(self, samples: list[dict]) -> list[tuple[np.ndarray, np.ndarray]]:
        prepared: list[tuple[np.ndarray, np.ndarray]] = []
        for s in samples:
            frame = s["frame"]
            h, w = frame.shape[:2]
            septal = s["septal"]
            lateral = s["lateral"]

            # Center crop on midpoint of annulus, clamped to frame
            mid_x = (septal[0] + lateral[0]) / 2.0
            mid_y = (septal[1] + lateral[1]) / 2.0
            half = self.crop_size / 2.0

            x0 = int(np.clip(mid_x - half, 0, max(w - self.crop_size, 0)))
            y0 = int(np.clip(mid_y - half, 0, max(h - self.crop_size, 0)))

            crop = frame[y0 : y0 + self.crop_size, x0 : x0 + self.crop_size]
            if crop.shape[0] < self.crop_size or crop.shape[1] < self.crop_size:
                padded = np.zeros((self.crop_size, self.crop_size), dtype=crop.dtype)
                padded[: crop.shape[0], : crop.shape[1]] = crop
                crop = padded

            # Normalize crop to [0, 1]
            crop_f = crop.astype(np.float32) / 255.0

            # Build 2-channel heatmap target
            septal_local = (septal[0] - x0, septal[1] - y0)
            lateral_local = (lateral[0] - x0, lateral[1] - y0)
            hm_septal = _make_heatmap(self.crop_size, septal_local, _HEATMAP_SIGMA)
            hm_lateral = _make_heatmap(self.crop_size, lateral_local, _HEATMAP_SIGMA)
            target = np.stack([hm_septal, hm_lateral], axis=0)  # (2, 224, 224)

            # Input: (1, 224, 224) grayscale
            inp = crop_f[np.newaxis, ...]
            prepared.append((inp, target))

        return prepared

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        inp, target = self.data[idx]
        return torch.from_numpy(inp), torch.from_numpy(target)


class MALandmarkNet(nn.Module):
    """Lightweight encoder → 2-channel heatmap head."""

    def __init__(self) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(128, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
        )
        self.decoder = nn.Sequential(
            nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False),
            nn.Conv2d(128, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False),
            nn.Conv2d(64, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False),
            nn.Conv2d(32, _NUM_KEYPOINTS, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(x))


def train(
    manifest_path: Path,
    gold_dir: Path,
    output_path: Path,
    *,
    epochs: int = 60,
    lr: float = 1e-3,
    batch_size: int = 16,
    val_split: float = 0.15,
) -> dict:
    """Train MA landmark model and export to ONNX."""
    print("Extracting training samples...")
    samples = _extract_training_samples(manifest_path, gold_dir)
    print(f"  {len(samples)} samples extracted")

    if len(samples) < 10:
        msg = f"Too few samples ({len(samples)}) for training"
        raise ValueError(msg)

    # Split train/val
    rng = np.random.default_rng(42)
    indices = rng.permutation(len(samples))
    val_count = max(1, int(len(samples) * val_split))
    val_idx = indices[:val_count]
    train_idx = indices[val_count:]

    train_samples = [samples[i] for i in train_idx]
    val_samples = [samples[i] for i in val_idx]
    print(f"  Train: {len(train_samples)}, Val: {len(val_samples)}")

    train_ds = MADataset(train_samples)
    val_ds = MADataset(val_samples)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    device = torch.device("cpu")
    model = MALandmarkNet().to(device)
    optimizer = optim.Adam(model.parameters(), lr=lr)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = nn.MSELoss()

    best_val_loss = float("inf")
    best_state = None

    print(f"Training for {epochs} epochs...")
    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        for inp, target in train_loader:
            inp, target = inp.to(device), target.to(device)
            pred = model(inp)
            loss = criterion(pred, target)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * inp.size(0)
        train_loss /= len(train_ds)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for inp, target in val_loader:
                inp, target = inp.to(device), target.to(device)
                pred = model(inp)
                val_loss += criterion(pred, target).item() * inp.size(0)
        val_loss /= len(val_ds)

        scheduler.step()

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}

        if epoch % 10 == 0 or epoch == 1:
            print(f"  Epoch {epoch:3d}: train={train_loss:.6f}  val={val_loss:.6f}")

    print(f"Best val loss: {best_val_loss:.6f}")
    model.load_state_dict(best_state)

    # Export to ONNX
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.randn(1, 1, _CROP_SIZE, _CROP_SIZE)
    torch.onnx.export(
        model,
        dummy,
        str(output_path),
        input_names=["input"],
        output_names=["heatmaps"],
        dynamic_axes={"input": {0: "batch"}, "heatmaps": {0: "batch"}},
        opset_version=17,
    )
    print(f"Exported: {output_path}")

    # Quick sanity: check predicted keypoints on val set
    model.eval()
    errors: list[float] = []
    sample_idx = 0
    with torch.no_grad():
        for inp, _ in val_loader:
            pred = model(inp.to(device))
            for b in range(pred.shape[0]):
                if sample_idx >= len(val_ds):
                    break
                _, gt_target = val_ds.data[sample_idx]
                for k in range(_NUM_KEYPOINTS):
                    hm = pred[b, k].cpu().numpy()
                    py, px = np.unravel_index(hm.argmax(), hm.shape)
                    gt_hm = gt_target[k]
                    gt_py, gt_px = np.unravel_index(gt_hm.argmax(), gt_hm.shape)
                    errors.append(float(np.hypot(px - gt_px, py - gt_py)))
                sample_idx += 1
    if errors:
        print(f"Val pixel error: median={np.median(errors):.1f} px, mean={np.mean(errors):.1f} px")

    return {"val_loss": best_val_loss, "output": str(output_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Train MA landmark ONNX model")
    parser.add_argument("--manifest", type=Path, default=Path("manifest.json"))
    parser.add_argument("--gold-dir", type=Path, default=Path("gold"))
    parser.add_argument("--output", type=Path, default=Path("models/ma_landmark_224.onnx"))
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()

    result = train(
        args.manifest,
        args.gold_dir,
        args.output,
        epochs=args.epochs,
        lr=args.lr,
    )
    print(f"\nDone. Val loss: {result['val_loss']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
