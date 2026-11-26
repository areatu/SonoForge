#!/usr/bin/env python3
"""Fine-tune DeepLabV3-ResNet50 decoder on LV gold segmentation masks (issue #687 / ML.0a).

Aligns LV fine-tuning with serve-time ``OnnxInferenceEngine``:
1. Preserves pretrained ResNet50/ASPP weights via shape-checked state-dict filtering.
2. Uses :func:`prepare_training_pair` (burned-ECG masking + ``center_square`` ROI
   crop + ``prepare_tensor`` z-score/fixed normalization) so ``train == serve``.
3. Removes horizontal mirroring and splits train/val by ``study_id`` without leakage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torchvision
except ImportError:  # pragma: no cover - optional heavy ML runtime
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    F = None  # type: ignore[assignment]
    torchvision = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from echo_personal_tool.domain.services.segment_roi import resolve_segment_roi_xyxy
from echo_personal_tool.domain.services.segmentation_preprocess import (
    filter_segmentation_backbone_state_dict,
    prepare_training_pair,
    split_samples_by_study,
)
from echo_personal_tool.infrastructure.dicom_frame_panels import try_parse_from_path

MODELS_DIR = PROJECT_ROOT / "models"
MANIFEST_PATH = MODELS_DIR / "model_manifest.json"
DEFAULT_WEIGHTS = MODELS_DIR / "deeplabv3_resnet50_random.pt"
DEFAULT_OUTPUT = MODELS_DIR / "echonet_seg_resnet50_finetuned.onnx"
DEFAULT_A2C_OUTPUT = MODELS_DIR / "echonet_a2c_resnet50.onnx"
INPUT_SIZE = 112
MODEL_ID = "echonet_seg_resnet50_finetuned"
BACKBONE_INIT_CHOICES = ("manifest", "imagenet_torchvision", "random")


def _require_torch() -> None:
    if torch is None or nn is None or F is None or torchvision is None:
        msg = "torch and torchvision are required to run LV segmentation training"
        raise RuntimeError(msg)
A2C_MODEL_ID = "echonet_a2c_resnet50"


def rasterize_polygon(
    points: list[list[float]],
    shape: tuple[int, int],
) -> np.ndarray:
    pts = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    mask = np.zeros(shape, dtype=np.uint8)
    closed = np.vstack([pts, pts[:1]])
    cv2.fillPoly(mask, [closed.astype(np.int32)], 1)
    return mask


def resolve_manifest_normalization(
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[list[float] | None, list[float] | None]:
    if not manifest_path.is_file():
        return None, None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    preprocessing = manifest.get("preprocessing", {})
    if not isinstance(preprocessing, dict):
        return None, None
    if preprocessing.get("normalization_mode", "per_frame") == "per_frame":
        return None, None
    fixed_mean = preprocessing.get("fixed_mean")
    fixed_std = preprocessing.get("fixed_std")
    if fixed_mean is None or fixed_std is None:
        return None, None
    return [float(v) for v in fixed_mean], [float(v) for v in fixed_std]


def load_lv_samples(manifest_path: Path) -> list[dict[str, Any]]:
    """Load LV gold samples from manifest + gold directory preserving ``study_id``."""
    with manifest_path.open(encoding="utf-8") as f:
        manifest = json.load(f)

    gold_dir = manifest_path.parent / "gold"
    samples: list[dict[str, Any]] = []

    for study in manifest.get("studies", []):
        study_id = str(study["study_id"])
        instance_path = str(study["instance_path"])
        gold_path = gold_dir / f"lv_{study_id}.json"
        if not gold_path.is_file():
            continue

        with gold_path.open(encoding="utf-8") as f:
            gold = json.load(f)

        for phase_key, frame_key in [("ED", "ed_frame"), ("ES", "es_frame")]:
            frame_index = study.get(frame_key)
            if frame_index is None:
                continue

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

            samples.append(
                {
                    "study_id": study_id,
                    "study_uid": str(study.get("study_uid") or study_id),
                    "instance_path": instance_path,
                    "frame_index": int(frame_index),
                    "phase": phase_key,
                    "points": points,
                }
            )
def load_lv_samples(
    manifest_path: Path,
    *,
    view: str = "A4C",
    gold_dir: Path | None = None,
) -> list[dict]:
    """Load LV gold samples from manifest + gold directory, filtered by view."""
    view_norm = (view or "A4C").strip().upper()
    resolved_gold_dir = gold_dir if gold_dir is not None else (manifest_path.parent / "gold")
    samples: list[dict] = []

    if manifest_path.is_file():
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        for study in manifest.get("studies", []):
            study_id = study["study_id"]
            instance_path = study["instance_path"]
            gold_path = resolved_gold_dir / f"lv_{study_id}.json"
            if not gold_path.is_file():
                continue

            with open(gold_path, encoding="utf-8") as f:
                gold = json.load(f)

            for phase_key, frame_key in [("ED", "ed_frame"), ("ES", "es_frame")]:
                frame_index = study.get(frame_key)
                if frame_index is None:
                    continue

                gold_frame = None
                for gf in gold.get("frames", []):
                    gf_view = str(gf.get("view", "A4C")).upper()
                    if view_norm != "ALL" and gf_view != view_norm:
                        continue
                    if gf.get("phase") == phase_key and gf.get("frame_index") == frame_index:
                        gold_frame = gf
                        break
                if gold_frame is None:
                    continue

                points = gold_frame.get("points", [])
                if len(points) < 3:
                    continue

                samples.append(
                    {
                        "instance_path": gold_frame.get("instance_path") or instance_path,
                        "frame_index": frame_index,
                        "phase": phase_key,
                        "view": str(gold_frame.get("view", "A4C")).upper(),
                        "points": points,
                    }
                )
        return samples

    if resolved_gold_dir.is_dir():
        for gold_path in sorted(resolved_gold_dir.glob("lv_*.json")):
            with open(gold_path, encoding="utf-8") as f:
                gold = json.load(f)
            default_inst = gold.get("instance_path", "")
            for gf in gold.get("frames", []):
                gf_view = str(gf.get("view", "A4C")).upper()
                if view_norm != "ALL" and gf_view != view_norm:
                    continue
                phase_key = str(gf.get("phase", "")).upper()
                if phase_key not in {"ED", "ES"}:
                    continue
                points = gf.get("points", [])
                inst_path = gf.get("instance_path") or default_inst
                frame_idx = gf.get("frame_index")
                if len(points) < 3 or not inst_path or frame_idx is None:
                    continue
                samples.append(
                    {
                        "instance_path": inst_path,
                        "frame_index": int(frame_idx),
                        "phase": phase_key,
                        "view": gf_view,
                        "points": points,
                    }
                )

    return samples


def _resolve_frame(instance_path: str, frame_index: int) -> np.ndarray | None:
    """Read DICOM frame preserving RGB channels when present so ECG strip masking fires."""
    try:
        from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl

        reader = DicomReaderImpl()
        frame = reader.read_pixels(Path(instance_path), frame_index)
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = frame[..., :3]
        frame_f = frame.astype(np.float32)
        fmin, fmax = float(frame_f.min()), float(frame_f.max())
        if fmax > fmin:
            frame_f = (frame_f - fmin) / (fmax - fmin) * 255.0
        else:
            frame_f = np.zeros_like(frame_f)
        return frame_f.astype(np.uint8)
    except Exception:
        return None


class LVGoldDataset:
    def __init__(
        self,
        samples: list[dict[str, Any]],
        *,
        input_size: int = INPUT_SIZE,
        augment: bool = False,
        fixed_mean: list[float] | None = None,
        fixed_std: list[float] | None = None,
        seed: int = 42,
    ) -> None:
        self._input_size = input_size
        self._augment = augment
        self._fixed_mean = fixed_mean
        self._fixed_std = fixed_std
        self._rng = np.random.default_rng(seed)
        self._cache: list[tuple[np.ndarray, np.ndarray, tuple[float, float, float, float] | None]] = []
        self._cache: list[tuple[np.ndarray, np.ndarray]] = []

        from echo_personal_tool.domain.services.segment_roi import resolve_segment_roi_xyxy
        from echo_personal_tool.domain.services.segmentation_service import crop_frame_for_echonet
        from echo_personal_tool.infrastructure.dicom_frame_panels import try_parse_from_path

        for s in samples:
            frame = _resolve_frame(str(s["instance_path"]), int(s["frame_index"]))
            if frame is None:
                continue
            h, w = frame.shape[:2]
            mask = rasterize_polygon(s["points"], (h, w))
            roi_xyxy = resolve_segment_roi_xyxy(
                frame,
                media_format="dicom",
                panel_layout=try_parse_from_path(Path(s["instance_path"])),
            )
            self._cache.append((frame, mask, roi_xyxy))

    def __len__(self) -> int:
        return len(self._cache)

    def __getitem__(self, idx: int) -> tuple[Any, Any]:
        _require_torch()
        frame, mask, roi_xyxy = self._cache[idx]
        input_chw, mask_1hw = prepare_training_pair(
            frame,
            mask,
            roi_xyxy=roi_xyxy,
            crop_mode="center_square",
            target_size=self._input_size,
            fixed_mean=self._fixed_mean,
            fixed_std=self._fixed_std,
            augment=self._augment,
            rng=self._rng,
        )
        return torch.from_numpy(input_chw), torch.from_numpy(mask_1hw)


def bce_dice_loss(logits: Any, target: Any) -> Any:
    _require_torch()
    bce = F.binary_cross_entropy_with_logits(logits, target)
    probs = torch.sigmoid(logits)
    intersection = (probs * target).sum(dim=(1, 2, 3))
    cardinality = probs.sum(dim=(1, 2, 3)) + target.sum(dim=(1, 2, 3))
    dice = 1.0 - (2.0 * intersection + 1.0) / (cardinality + 1.0)
    return bce + dice.mean()


def _load_checkpoint_dict(weights_path: Path) -> dict[str, Any]:
    _require_torch()
    try:
        raw = torch.load(weights_path, map_location="cpu", weights_only=False)
    except TypeError:
        raw = torch.load(weights_path, map_location="cpu")
    if isinstance(raw, dict) and "state_dict" in raw and isinstance(raw["state_dict"], dict):
        return raw["state_dict"]
    if isinstance(raw, dict):
        return raw
    msg = f"Unsupported checkpoint format at {weights_path}: {type(raw)}"
    raise ValueError(msg)


def build_model(
    *,
    backbone_init: str = "manifest",
    weights_path: Path = DEFAULT_WEIGHTS,
) -> Any:
    _require_torch()
    if backbone_init not in BACKBONE_INIT_CHOICES:
        msg = f"backbone_init must be one of {BACKBONE_INIT_CHOICES}, got {backbone_init!r}"
        raise ValueError(msg)

    use_tv_imagenet = backbone_init == "imagenet_torchvision" or (
        backbone_init == "manifest" and not weights_path.is_file()
    )
    if use_tv_imagenet:
        model = torchvision.models.segmentation.deeplabv3_resnet50(weights="DEFAULT")
        init_source = "torchvision_imagenet"
    else:
        model = torchvision.models.segmentation.deeplabv3_resnet50(weights=None, aux_loss=False)
        init_source = "random"

    classifier = model.classifier[-1]
    new_conv = nn.Conv2d(
        classifier.in_channels,
        1,
        kernel_size=classifier.kernel_size,
    )
    nn.init.constant_(new_conv.bias, 0.5)
    model.classifier[-1] = new_conv
    model.aux_classifier = None

    if backbone_init == "manifest" and weights_path.is_file():
        ckpt_state = _load_checkpoint_dict(weights_path)
        filtered, skipped = filter_segmentation_backbone_state_dict(ckpt_state, model.state_dict())
        model.load_state_dict(filtered, strict=False)
        init_source = f"manifest:{weights_path.name} ({len(filtered)} loaded, {len(skipped)} skipped)"

    for param in model.parameters():
        param.requires_grad = False
    for param in model.classifier.parameters():
        param.requires_grad = True

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Model ({init_source}): {trainable:,} trainable / {total:,} total params")  # noqa: T201
    return model


def _evaluate_iou(model: Any, dataset: LVGoldDataset, *, batch_size: int, device: str) -> float:
    _require_torch()
    if len(dataset) == 0:
        return 0.0
    loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=False)
    model.eval()
    ious: list[float] = []
    with torch.no_grad():
        for frames, masks in loader:
            frames_d = frames.to(device)
            preds = (torch.sigmoid(model(frames_d)["out"]).cpu() >= 0.5).float()
            inter = (preds * masks).sum(dim=(1, 2, 3))
            union = ((preds + masks) > 0).float().sum(dim=(1, 2, 3))
            batch_iou = torch.where(union > 0, inter / union, torch.ones_like(union))
            ious.extend(float(v) for v in batch_iou)
    return float(np.mean(ious)) if ious else 0.0


def train_model(
    model: Any,
    dataset: LVGoldDataset,
    *,
    val_dataset: LVGoldDataset | None = None,
    epochs: int = 40,
    batch_size: int = 8,
    lr: float = 1e-4,
    device: str = "cpu",
) -> dict[str, float]:
    _require_torch()
    if len(dataset) == 0:
        print("ERROR: No training samples")  # noqa: T201
        sys.exit(1)

    loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        drop_last=len(dataset) >= batch_size,
    )
    optimizer = torch.optim.Adam(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=lr,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(epochs, 1))

    model.to(device)
    best_iou = -1.0
    best_state: dict[str, Any] | None = None
    last_loss = 0.0

    print(f"Training: {len(dataset)} samples, {epochs} epochs, lr={lr}")  # noqa: T201
    for epoch in range(1, epochs + 1):
        model.train()
        if hasattr(model, "backbone"):
            model.backbone.eval()
        total_loss = 0.0
        n_batches = 0
        for frames, masks in loader:
            frames_d, masks_d = frames.to(device), masks.to(device)
            optimizer.zero_grad()
            output = model(frames_d)["out"]
            loss = bce_dice_loss(output, masks_d)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item())
            n_batches += 1

        scheduler.step()
        last_loss = total_loss / max(n_batches, 1)
        val_iou = (
            _evaluate_iou(model, val_dataset, batch_size=batch_size, device=device)
            if val_dataset is not None and len(val_dataset) > 0
            else 0.0
        )
        if val_dataset is not None and len(val_dataset) > 0 and val_iou >= best_iou:
            best_iou = val_iou
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        if epoch % 5 == 0 or epoch == 1:
            print(f"  Epoch {epoch:3d}/{epochs}: loss={last_loss:.4f} val_iou={val_iou:.4f}", flush=True)  # noqa: T201

    if best_state is not None:
        model.load_state_dict(best_state)
    print("Training complete.")  # noqa: T201
    return {"final_train_loss": last_loss, "best_val_iou": max(best_iou, 0.0)}


def export_onnx(model: Any, output_path: Path, input_size: int = INPUT_SIZE) -> None:
    _require_torch()

    class _Wrapper(nn.Module):  # type: ignore[misc]
        def __init__(self, backbone: Any) -> None:
            super().__init__()
            self.backbone = backbone

        def forward(self, x: Any) -> Any:
            return self.backbone(x)["out"]

    model.cpu()
    model.eval()
    wrapper = _Wrapper(model)
    dummy = torch.randn(1, 3, input_size, input_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapper,
        dummy,
        str(output_path),
        export_params=True,
        opset_version=17,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
    )
    print(f"ONNX exported: {output_path} ({output_path.stat().st_size:,} bytes)")  # noqa: T201


def verify_onnx(onnx_path: Path, input_size: int = INPUT_SIZE) -> None:
    try:
        import onnxruntime as ort
    except ImportError:
        return
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    sample = np.random.randn(1, 3, input_size, input_size).astype(np.float32)
    logits = session.run(None, {"input": sample})[0]
    print(f"Verify OK: shape={logits.shape}, range=[{logits.min():.3f}, {logits.max():.3f}]")  # noqa: T201


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune LV segmentation decoder")
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "manifest.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--backbone-init", choices=BACKBONE_INIT_CHOICES, default="manifest")
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
def update_model_manifest(onnx_path: Path, model_id: str, manifest_path: Path = MANIFEST_PATH) -> None:
    if not manifest_path.is_file() or not onnx_path.is_file():
        return
    digest = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    size = onnx_path.stat().st_size
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    models = data.setdefault("models", {})
    entry = models.setdefault(model_id, {"id": model_id, "filename": onnx_path.name})
    entry["filename"] = onnx_path.name
    entry["status"] = "exported"
    entry["sha256"] = digest
    entry["file_size_bytes"] = size
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest updated for {model_id}: sha256={digest[:16]}… ({size:,} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fine-tune LV segmentation decoder (A4C / A2C)")
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "manifest.json")
    parser.add_argument("--gold-dir", type=Path, default=None)
    parser.add_argument("--view", choices=("A4C", "A2C", "ALL"), default="A4C")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--update-manifest", action="store_true")
    parser.add_argument("--device", default="cpu")
    return parser.parse_args(argv)

    output_path = args.output
    if output_path is None:
        output_path = DEFAULT_A2C_OUTPUT if args.view == "A2C" else DEFAULT_OUTPUT
    model_id = A2C_MODEL_ID if args.view == "A2C" else MODEL_ID

    print(f"Loading LV gold ({args.view}) from {args.manifest} ...")
    samples = load_lv_samples(args.manifest, view=args.view, gold_dir=args.gold_dir)
    print(f"Found {len(samples)} LV samples (ED+ES, view={args.view})")

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print(f"Loading LV gold from {args.manifest} ...")  # noqa: T201
    samples = load_lv_samples(args.manifest)
    print(f"Found {len(samples)} LV samples (ED+ES)")  # noqa: T201

    train_samples, val_samples = split_samples_by_study(
        samples,
        val_ratio=args.val_ratio,
        seed=args.seed,
    )
    fixed_mean, fixed_std = resolve_manifest_normalization(MANIFEST_PATH)
    train_ds = LVGoldDataset(
        train_samples,
        input_size=INPUT_SIZE,
        augment=True,
        fixed_mean=fixed_mean,
        fixed_std=fixed_std,
        seed=args.seed,
    )
    val_ds = LVGoldDataset(
        val_samples,
        input_size=INPUT_SIZE,
        augment=False,
        fixed_mean=fixed_mean,
        fixed_std=fixed_std,
        seed=args.seed,
    )
    print(f"Split by study_id: train={len(train_ds)}, val={len(val_ds)}")  # noqa: T201

    model = build_model(backbone_init=args.backbone_init, weights_path=args.weights)
    train_model(
        model,
        train_ds,
        val_dataset=val_ds,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        device=args.device,
    )
    export_onnx(model, args.output, input_size=INPUT_SIZE)
    model = build_model()
    train_model(model, dataset, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr, device=args.device)
    export_onnx(model, output_path, input_size=INPUT_SIZE)

    if args.verify:
        verify_onnx(output_path, input_size=INPUT_SIZE)
    if args.update_manifest:
        update_model_manifest(output_path, model_id=model_id)

    print("Done.")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
