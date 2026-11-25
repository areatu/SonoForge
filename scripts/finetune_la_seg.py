#!/usr/bin/env python3
"""Fine-tune DeepLabV3-ResNet50 on LA gold segmentation masks (issue #687 / ML.0a).

Fixes the three baseline LA segmentation training defects:
1. Preserves pretrained ResNet50/ASPP weights from ``deeplabv3_resnet50_random.pt``
   (or torchvision ImageNet weights) via shape-checked head filtering instead of
   resetting the encoder to ``weights=None`` random noise.
2. Uses :func:`prepare_training_pair` from :mod:`segmentation_preprocess` so
   burned-in ECG masking, ROI cropping, and per-frame/fixed normalization match
   :class:`OnnxInferenceEngine` 1:1 (``max(|T_train - T_serve|) < 1e-6``).
3. Replaces anatomy-breaking horizontal flips with echo-safe sector augmentations,
   splits train/val by ``study_uid`` without patient leakage, and supports both
   ``A4C`` and ``A2C`` views for biplane LA volume (#548).
"""

from __future__ import annotations

import argparse
import hashlib
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
    LA_SUPPORTED_VIEWS,
    filter_segmentation_backbone_state_dict,
    prepare_training_pair,
    split_samples_by_study,
)
from echo_personal_tool.infrastructure.dicom_frame_panels import try_parse_from_path

MODELS_DIR = PROJECT_ROOT / "models"
MANIFEST_PATH = MODELS_DIR / "model_manifest.json"
DEFAULT_WEIGHTS = MODELS_DIR / "deeplabv3_resnet50_random.pt"
DEFAULT_OUTPUT = MODELS_DIR / "echonet_la_resnet50_224.onnx"
INPUT_SIZE = 224
MODEL_ID = "echonet_la_resnet50_224"
BACKBONE_INIT_CHOICES = ("manifest", "imagenet_torchvision", "random")


def _require_torch() -> None:
    if torch is None or nn is None or F is None or torchvision is None:
        msg = "torch and torchvision are required to run LA segmentation training"
        raise RuntimeError(msg)


def rasterize_polygon(
    points: list[list[float]],
    shape: tuple[int, int],
) -> np.ndarray:
    """Rasterize open-arc contour to filled binary mask."""
    pts = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    mask = np.zeros(shape, dtype=np.uint8)
    closed = np.vstack([pts, pts[:1]])
    cv2.fillPoly(mask, [closed.astype(np.int32)], 1)
    return mask


def resolve_manifest_normalization(
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[list[float] | None, list[float] | None]:
    """Read normalization parameters matching ``OnnxInferenceEngine``."""
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


def load_la_gold(gold_root: Path) -> list[dict[str, Any]]:
    """Load all LA gold JSON files from ``gold_root/gold/la_*.json``."""
    gold_dir = gold_root / "gold"
    if not gold_dir.is_dir():
        msg = f"gold directory not found: {gold_dir}"
        raise FileNotFoundError(msg)

    studies: list[dict[str, Any]] = []
    for path in sorted(gold_dir.glob("la_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  SKIP {path.name}: {exc}")  # noqa: T201
            continue
        if str(data.get("chamber", "")).upper() != "LA":
            continue
        if "study_id" not in data and path.stem.startswith("la_"):
            data = {**data, "study_id": path.stem.removeprefix("la_")}
        studies.append(data)
    return studies


def extract_la_samples(
    studies: list[dict[str, Any]],
    *,
    allowed_views: frozenset[str] = LA_SUPPORTED_VIEWS,
) -> list[dict[str, Any]]:
    """Flatten study records into frame samples preserving ``study_uid`` and ``view``."""
    samples: list[dict[str, Any]] = []
    for study in studies:
        default_path = str(study.get("instance_path", "") or "")
        study_uid = str(study.get("study_uid") or study.get("study_id") or "")
        study_view = str(study.get("view", "A4C") or "A4C").upper()
        for frame in study.get("frames", []):
            if str(frame.get("chamber", "LA")).upper() != "LA":
                continue
            view = str(frame.get("view") or study_view).upper()
            if allowed_views and view not in allowed_views:
                continue
            points = frame.get("points", [])
            if len(points) < 3:
                continue
            instance_path = str(frame.get("instance_path") or default_path)
            if not instance_path:
                continue
            samples.append(
                {
                    "study_uid": study_uid,
                    "sop_instance_uid": str(frame.get("sop_instance_uid") or study.get("sop_instance_uid") or ""),
                    "instance_path": instance_path,
                    "frame_index": int(frame.get("frame_index", 0)),
                    "view": view,
                    "points": points,
                    "mitral_annulus": frame.get("mitral_annulus"),
                    "pixel_spacing_mm": study.get("pixel_spacing_mm", [0.15, 0.15]),
                }
            )
    return samples


def _resolve_dicom_frame(
    instance_path: str,
    frame_index: int,
) -> np.ndarray | None:
    """Load a single DICOM frame preserving RGB channels when present for ECG masking."""
    try:
        import pydicom
    except ImportError:
        return None

    try:
        pixel_array = pydicom.dcmread(instance_path).pixel_array
    except Exception:
        return None

    if pixel_array.ndim == 4:
        idx = frame_index if frame_index < pixel_array.shape[0] else -1
        frame = pixel_array[idx]
    elif pixel_array.ndim == 3:
        if pixel_array.shape[-1] in (3, 4):
            frame = pixel_array[..., :3]
        else:
            idx = frame_index if frame_index < pixel_array.shape[0] else -1
            frame = pixel_array[idx]
    else:
        frame = pixel_array

    if frame.ndim == 3 and frame.shape[-1] == 4:
        frame = frame[..., :3]

    frame_f = frame.astype(np.float32)
    fmin, fmax = float(frame_f.min()), float(frame_f.max())
    if fmax > fmin:
        frame_f = (frame_f - fmin) / (fmax - fmin) * 255.0
    else:
        frame_f = np.zeros_like(frame_f)
    return frame_f.astype(np.uint8)


class LaGoldDataset:
    """Dataset of ``(tensor_chw, mask_1hw)`` pairs matching serve-time preprocessing."""

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

        for sample in samples:
            instance_path = Path(sample["instance_path"])
            frame = _resolve_dicom_frame(str(instance_path), int(sample["frame_index"]))
            if frame is None:
                frame = np.zeros((input_size, input_size), dtype=np.uint8)
            h, w = frame.shape[:2]
            mask = rasterize_polygon(sample["points"], (h, w))
            roi_xyxy = resolve_segment_roi_xyxy(
                frame,
                media_format="dicom",
                panel_layout=try_parse_from_path(instance_path),
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
            crop_mode="full_roi",
            target_size=self._input_size,
            fixed_mean=self._fixed_mean,
            fixed_std=self._fixed_std,
            augment=self._augment,
            rng=self._rng,
        )
        return torch.from_numpy(input_chw), torch.from_numpy(mask_1hw)


def bce_dice_loss(logits: Any, target: Any) -> Any:
    """Combined BCE + Dice loss for binary segmentation."""
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


def build_la_model(
    *,
    backbone_init: str = "manifest",
    weights_path: Path = DEFAULT_WEIGHTS,
) -> Any:
    """Build 1-class DeepLabV3-ResNet50 preserving pretrained encoder weights."""
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
    new_head = nn.Conv2d(
        classifier.in_channels,
        1,
        kernel_size=classifier.kernel_size,
    )
    nn.init.constant_(new_head.bias, -1.0)
    model.classifier[-1] = new_head
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


def _evaluate_iou(model: Any, dataset: LaGoldDataset, *, batch_size: int, device: str) -> float:
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


def train(
    model: Any,
    train_dataset: LaGoldDataset,
    *,
    val_dataset: LaGoldDataset | None = None,
    epochs: int = 40,
    batch_size: int = 4,
    lr: float = 1e-4,
    device: str = "cpu",
) -> dict[str, float]:
    """Train the decoder head on LA gold masks with study-level validation tracking."""
    _require_torch()
    if len(train_dataset) == 0:
        print("ERROR: No training samples found. Need >=1 LA gold file.")  # noqa: T201
        sys.exit(1)

    loader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        drop_last=len(train_dataset) >= batch_size,
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

    print(f"Training: {len(train_dataset)} train samples, {epochs} epochs, lr={lr}")  # noqa: T201
    for epoch in range(1, epochs + 1):
        model.train()
        if hasattr(model, "backbone"):
            model.backbone.eval()
        total_loss = 0.0
        n_batches = 0
        for frames, masks in loader:
            frames_d = frames.to(device)
            masks_d = masks.to(device)
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


def export_onnx(
    model: Any,
    output_path: Path,
    *,
    input_size: int = INPUT_SIZE,
    opset: int = 17,
) -> None:
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
        opset_version=opset,
        do_constant_folding=True,
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
    )
    print(f"ONNX exported: {output_path} ({output_path.stat().st_size:,} bytes)")  # noqa: T201


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def update_manifest(onnx_path: Path, *, input_size: int = INPUT_SIZE) -> None:
    """Add or update LA model slot in ``model_manifest.json``."""
    if not MANIFEST_PATH.exists():
        print(f"Manifest not found: {MANIFEST_PATH}")  # noqa: T201
        return
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    models = manifest.setdefault("models", {})
    if MODEL_ID not in models:
        models[MODEL_ID] = {
            "id": MODEL_ID,
            "filename": onnx_path.name,
            "architecture": "deeplabv3_resnet50",
            "description": "LA cavity segmentation A4C+A2C (fine-tuned, parity-aligned)",
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
    print(f"Manifest updated: {MANIFEST_PATH}")  # noqa: T201


def verify_onnx(onnx_path: Path, input_size: int = INPUT_SIZE) -> None:
    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime not installed, skipping verify")  # noqa: T201
        return
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    sample = np.random.randn(1, 3, input_size, input_size).astype(np.float32)
    outputs = session.run(None, {"input": sample})
    logits = outputs[0]
    print(f"Verify OK: shape={logits.shape}, range=[{logits.min():.3f}, {logits.max():.3f}]")  # noqa: T201


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fine-tune LA segmentation + ONNX export")
    p.add_argument("--gold-root", type=Path, required=True, help="Gold dataset root")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="ONNX output path")
    p.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS, help="Base checkpoint path")
    p.add_argument(
        "--backbone-init",
        choices=BACKBONE_INIT_CHOICES,
        default="manifest",
        help="Encoder initialization source (manifest checkpoint or torchvision ImageNet)",
    )
    p.add_argument("--views", default="A4C,A2C", help="Comma-separated LA views to include")
    p.add_argument("--val-ratio", type=float, default=0.2, help="Study-level validation split ratio")
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    p.add_argument("--epochs", type=int, default=40, help="Training epochs")
    p.add_argument("--batch-size", type=int, default=4, help="Batch size")
    p.add_argument("--lr", type=float, default=1e-4, help="Learning rate")
    p.add_argument("--input-size", type=int, default=INPUT_SIZE, help="Model input size")
    p.add_argument("--verify", action="store_true", help="Verify ONNX after export")
    p.add_argument("--no-manifest", action="store_true", help="Skip manifest update")
    p.add_argument("--device", default="cpu", help="Device (cpu/cuda)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    allowed_views = frozenset(v.strip().upper() for v in args.views.split(",") if v.strip())

    print(f"Loading LA gold from {args.gold_root} ...")  # noqa: T201
    studies = load_la_gold(args.gold_root)
    samples = extract_la_samples(studies, allowed_views=allowed_views)
    print(f"Found {len(studies)} LA gold studies -> {len(samples)} frame samples")  # noqa: T201

    if not samples:
        print("No LA gold data found. Collect gold annotations first.")  # noqa: T201
        return 1

    train_samples, val_samples = split_samples_by_study(
        samples,
        val_ratio=args.val_ratio,
        seed=args.seed,
    )
    fixed_mean, fixed_std = resolve_manifest_normalization(MANIFEST_PATH)
    train_ds = LaGoldDataset(
        train_samples,
        input_size=args.input_size,
        augment=True,
        fixed_mean=fixed_mean,
        fixed_std=fixed_std,
        seed=args.seed,
    )
    val_ds = LaGoldDataset(
        val_samples,
        input_size=args.input_size,
        augment=False,
        fixed_mean=fixed_mean,
        fixed_std=fixed_std,
        seed=args.seed,
    )
    print(f"Split by study_uid: train={len(train_ds)}, val={len(val_ds)}")  # noqa: T201

    model = build_la_model(backbone_init=args.backbone_init, weights_path=args.weights)
    train(
        model,
        train_ds,
        val_dataset=val_ds,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        device=args.device,
    )
    export_onnx(model, args.output, input_size=args.input_size)

    if args.verify:
        verify_onnx(args.output, input_size=args.input_size)

    if not args.no_manifest:
        update_manifest(args.output, input_size=args.input_size)

    print("Done.")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
