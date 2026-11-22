"""Train a baseline EfficientNet-B0 view-recognition classifier (#639 step 2).

Consumes the point-1 v2 manifest (``view_recognition`` split assignments)
via the infrastructure :class:`ViewRecognitionDataset`, which decodes clips
through an injected :data:`ClipProvider` and returns normalized ``(clip, label)``
pairs. Fine-tunes an EfficientNet-B0 feature extractor + a fresh classifier
head for the 7 standard cardiac views.

Usage::

    python scripts/train_view_recognition.py \
        --manifest models/view_recognition_manifest.json \
        --output-dir models/view_recognition \
        --epochs 12 --batch-size 8 --learning-rate 1e-4

The script saves a checkpoint (``model.pth``), the expected I/O contract
(``io_contract.json``) and the training history, so the ONNX export step
(``scripts/export_view_recognition_onnx.py``) stays model-shape agnostic.
"""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

# torchvision is an optional heavy dependency; import lazily so the script
# reports a clear message instead of an ImportError traceback when absent.
try:
    from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

    _BACKBONE_FACTORY = "torchvision"
except ImportError:  # pragma: no cover - depends on installed extras
    _BACKBONE_FACTORY = None

from echo_personal_tool.domain.models.view_recognition import KNOWN_VIEWS, clip_label_index
from echo_personal_tool.domain.services.view_recognition_inference import (
    batch_to_channels,
    clip_to_batch,
)
from echo_personal_tool.infrastructure.view_recognition_dataset import (
    ViewRecognitionDataset,
    load_manifest,
)

CLASS_NAMES = list(KNOWN_VIEWS)
INPUT_SIZE = 224


@dataclass(frozen=True)
class TrainArgs:
    """Parsed training arguments."""

    manifest_path: Path
    output_dir: Path
    epochs: int
    batch_size: int
    learning_rate: float
    weight_decay: float
    seed: int
    subset_limit: int
    synthetic: bool
    unfreeze_last: int
    augment_views: tuple[str, ...]
    augment_copies: int
    augment_frame_jitter: bool


def _parse_args(argv: list[str] | None = None) -> TrainArgs:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--subset-limit", type=int, default=0)
    parser.add_argument(
        "--unfreeze-last",
        type=int,
        default=0,
        help="Unfreeze the last N backbone blocks (default 0, head only)",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="use synthetic clips instead of real DICOM frames (smoke runs)",
    )
    parser.add_argument(
        "--augment-classes",
        default="A3C",
        help="comma-separated views to oversample with augmentation (default A3C; empty disables)",
    )
    parser.add_argument(
        "--augment-copies",
        type=int,
        default=3,
        help="extra augmented copies per clip of an augmented view (default 3)",
    )
    parser.add_argument(
        "--augment-frame-jitter",
        action="store_true",
        help="use a random central cine frame for augmented copies instead of the middle one",
    )
    args = parser.parse_args(argv)
    augment_views = tuple(v.strip().upper() for v in args.augment_classes.split(",") if v.strip())
    unknown = sorted(set(augment_views) - set(CLASS_NAMES))
    if unknown:
        parser.error(f"unknown --augment-classes: {', '.join(unknown)}")
    if args.augment_copies < 0:
        parser.error("--augment-copies must be >= 0")
    return TrainArgs(
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        seed=args.seed,
        subset_limit=args.subset_limit,
        synthetic=args.synthetic,
        unfreeze_last=args.unfreeze_last,
        augment_views=augment_views,
        augment_copies=args.augment_copies,
        augment_frame_jitter=args.augment_frame_jitter,
    )


def _build_backbone(num_classes: int) -> nn.Module:
    if _BACKBONE_FACTORY is None:
        raise RuntimeError(
            "torchvision is required for EfficientNet-B0 training; "
            "install torchvision before running this script"
        )
    weights = EfficientNet_B0_Weights.DEFAULT
    model = efficientnet_b0(weights=weights)
    classifier = model.classifier
    in_features = classifier[1].in_features
    classifier[1] = nn.Linear(in_features, num_classes)
    return model


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _to_logits_batch(clips: list[np.ndarray]) -> torch.Tensor:
    """Turn ``(N, F, H, W[, C])`` clips into a ``(N, 3, H, W)`` frame batch.

    A clip carries one view label, so a representative frame from the middle
    of each clip is used. ``clip_to_batch`` / ``batch_to_channels`` are the same
    preprocessing helpers the ONNX adapter uses at inference time.
    """
    frames: list[np.ndarray] = []
    for clip in clips:
        array = np.asarray(clip)
        if array.ndim not in (3, 4) or array.shape[0] == 0:
            raise ValueError(f"clip must be (F,H,W) or (F,H,W,C), got {array.shape}")
        frames.append(array[array.shape[0] // 2])
    batch = batch_to_channels(clip_to_batch(frames, INPUT_SIZE))
    return torch.from_numpy(np.ascontiguousarray(batch))


def _augment_clip(clip: np.ndarray, *, frame_jitter: bool = False) -> np.ndarray:
    """Apply one random echo-safe transform to every frame of a cine clip.

    The same geometric/photometric parameters are shared by all frames so the
    temporal structure is preserved. With ``frame_jitter`` the clip's middle
    frame (the one used for training) is swapped with a random central frame,
    which exposes the classifier to different cardiac phases.
    """
    from torchvision.transforms import functional as TF

    frames = list(np.asarray(clip))
    if not frames:
        return np.asarray(clip)
    if frame_jitter and len(frames) >= 3:
        low, high = len(frames) // 4, (3 * len(frames)) // 4
        other = random.randint(low, max(low, high))
        middle = len(frames) // 2
        frames[middle], frames[other] = frames[other], frames[middle]

    angle = random.uniform(-10.0, 10.0)
    translate_x = random.uniform(-0.05, 0.05)
    translate_y = random.uniform(-0.05, 0.05)
    scale = random.uniform(0.92, 1.08)
    flip = random.random() < 0.5
    gamma = random.uniform(0.85, 1.15)
    gain = random.uniform(0.9, 1.1)
    noise = random.uniform(0.0, 0.02)

    augmented: list[np.ndarray] = []
    for frame in frames:
        array = np.ascontiguousarray(frame, dtype=np.float32)
        grayscale = array.ndim == 2
        tensor = torch.from_numpy(array)
        tensor = tensor.unsqueeze(0) if grayscale else tensor.permute(2, 0, 1)
        height, width = tensor.shape[-2:]
        tensor = TF.affine(
            tensor,
            angle=angle,
            translate=(round(translate_x * width), round(translate_y * height)),
            scale=scale,
            shear=0.0,
            fill=0.0,
        )
        if flip:
            tensor = torch.flip(tensor, dims=[-1])
        tensor = tensor.clamp(0.0, 1.0).pow(gamma) * gain
        if noise:
            tensor = tensor + torch.randn_like(tensor) * noise
        tensor = tensor.clamp(0.0, 1.0)
        augmented.append(
            tensor[0].numpy() if grayscale else tensor.permute(1, 2, 0).numpy()
        )
    return np.stack(augmented)


class _AugmentedClipsDataset:
    """Replays minority-view clips with fresh augmentation on every access."""

    def __init__(
        self,
        base: ViewRecognitionDataset,
        views: tuple[str, ...],
        copies: int,
        frame_jitter: bool,
    ) -> None:
        self._base = base
        self._frame_jitter = frame_jitter
        self._entries: list[tuple[int, bool]] = []
        for index in range(len(base)):
            sample = base._samples[index]  # noqa: SLF001 - script-local wrapper
            self._entries.append((index, False))
            if sample.view in views:
                self._entries.extend([(index, True)] * copies)

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(self, index: int) -> tuple[np.ndarray, int]:
        source, augment = self._entries[index]
        clip, label = self._base[source]
        if augment:
            clip = _augment_clip(clip, frame_jitter=self._frame_jitter)
        return clip, label


def _run_epoch(
    model: nn.Module,
    loader: DataLoader[tuple[np.ndarray, int]],
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    class_weights: torch.Tensor,
) -> float:
    model.train()
    total_loss = 0.0
    total_count = 0
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    for clips, targets in loader:
        inputs = _to_logits_batch(clips).to(device)
        labels = torch.as_tensor(targets, dtype=torch.long, device=device)
        optimizer.zero_grad()
        logits = model(inputs)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        batch_size = int(labels.shape[0])
        total_loss += float(loss.item()) * batch_size
        total_count += batch_size
    return total_loss / max(total_count, 1)


def _evaluate_accuracy(
    model: nn.Module,
    loader: DataLoader[tuple[np.ndarray, int]],
    device: torch.device,
) -> tuple[float, dict[str, tuple[int, int]]]:
    model.eval()
    correct = 0
    total = 0
    per_class: dict[str, list[int]] = {name: [0, 0] for name in CLASS_NAMES}
    with torch.no_grad():
        for clips, targets in loader:
            inputs = _to_logits_batch(clips).to(device)
            labels = torch.as_tensor(targets, dtype=torch.long, device=device)
            preds = model(inputs).argmax(dim=1)
            correct += int((preds == labels).sum().item())
            total += int(labels.shape[0])
            for label, pred in zip(labels.tolist(), preds.tolist()):
                name = CLASS_NAMES[label]
                per_class[name][1] += 1
                if label == pred:
                    per_class[name][0] += 1
    stats = {name: (values[0], values[1]) for name, values in per_class.items() if values[1]}
    return correct / max(total, 1), stats


def _collate_clips(batch: list[tuple[np.ndarray, int]]) -> tuple[list[np.ndarray], torch.Tensor]:
    """Keep clips unstacked: DICOM cines have different frame sizes."""
    return [clip for clip, _ in batch], torch.tensor([label for _, label in batch], dtype=torch.long)


def _make_loader(
    split: str,
    manifest_path: Path,
    clip_provider: Callable[[str], np.ndarray],
    batch_size: int,
    subset_limit: int,
    shuffle: bool,
    *,
    augment_views: tuple[str, ...] = (),
    augment_copies: int = 0,
    frame_jitter: bool = False,
) -> DataLoader[tuple[np.ndarray, int]]:
    manifest = load_manifest(manifest_path)
    dataset = ViewRecognitionDataset(manifest, clip_provider, split=split)
    if subset_limit:
        dataset._samples = dataset._samples[:subset_limit]  # noqa: SLF001 - script-local trim
    if split == "train" and augment_views and augment_copies:
        dataset = _AugmentedClipsDataset(  # type: ignore[assignment]
            dataset, augment_views, augment_copies, frame_jitter
        )
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=0,
        drop_last=False,
        collate_fn=_collate_clips,
    )


def _class_weights(
    manifest: Any,
    device: torch.device,
    augment_views: tuple[str, ...] = (),
    augment_copies: int = 0,
) -> torch.Tensor:
    """Inverse-frequency weights from the effective train split.

    Augmented copies are counted, otherwise oversampling a class and weighting
    it inversely at the same time would over-correct several times over.
    """
    counts = [0] * len(CLASS_NAMES)
    for sample in manifest.samples:
        if sample.split == "train" and sample.view in CLASS_NAMES:
            multiplier = 1 + augment_copies if sample.view in augment_views else 1
            counts[clip_label_index(sample.view, CLASS_NAMES)] += multiplier
    total = sum(counts) or 1
    weights = [
        total / (len(CLASS_NAMES) * count) if count else 1.0 for count in counts
    ]
    return torch.tensor(weights, dtype=torch.float, device=device)


def train(args: TrainArgs, clip_provider: Callable[[str], np.ndarray]) -> dict[str, Any]:
    _set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    manifest = load_manifest(args.manifest_path)
    class_weights = _class_weights(
        manifest, device, args.augment_views, args.augment_copies
    )
    print(f"device: {device}")  # noqa: T201
    print(  # noqa: T201
        "class weights: "
        + ", ".join(f"{name}={weight:.2f}" for name, weight in zip(CLASS_NAMES, class_weights.tolist()))
    )
    if args.augment_views and args.augment_copies:
        print(  # noqa: T201
            f"augment: views={','.join(args.augment_views)} "
            f"copies={args.augment_copies} frame_jitter={args.augment_frame_jitter}"
        )
    train_loader = _make_loader(
        "train",
        args.manifest_path,
        clip_provider,
        args.batch_size,
        args.subset_limit,
        True,
        augment_views=args.augment_views,
        augment_copies=args.augment_copies,
        frame_jitter=args.augment_frame_jitter,
    )
    val_loader = _make_loader(
        "val", args.manifest_path, clip_provider, args.batch_size, args.subset_limit, False
    )
    model = _build_backbone(len(CLASS_NAMES)).to(device)
    # Transfer learning: freeze the feature extractor, train only the new
    # classifier head.
    for param in model.features.parameters():
        param.requires_grad_(False)
    if args.unfreeze_last > 0:
        blocks = list(model.features.children())
        for block in blocks[-args.unfreeze_last :]:
            for param in block.parameters():
                param.requires_grad_(True)
        print(f"unfrozen last {args.unfreeze_last} backbone blocks")  # noqa: T201
    trainable = [param for param in model.parameters() if param.requires_grad]
    optimizer = torch.optim.Adam(trainable, lr=args.learning_rate)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max(args.epochs, 1),
        eta_min=args.learning_rate * 0.01,
    )

    history: list[dict[str, float]] = []
    best_acc = -1.0
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    for epoch in range(1, args.epochs + 1):
        train_loss = _run_epoch(model, train_loader, optimizer, device, class_weights)
        val_acc, per_class = _evaluate_accuracy(model, val_loader, device)
        scheduler.step()
        history.append({"epoch": epoch, "train_loss": train_loss, "val_acc": val_acc})
        if val_acc > best_acc:
            best_acc = val_acc
            best_epoch = epoch
            best_state = {
                name: value.detach().cpu().clone()
                for name, value in model.state_dict().items()
            }
        detail = " ".join(f"{name}:{hit}/{n}" for name, (hit, n) in per_class.items())
        print(  # noqa: T201
            f"epoch {epoch}/{args.epochs}: "
            f"loss={train_loss:.4f} val_acc={val_acc:.4f}  {detail}"
        )

    if best_state is not None:
        model.load_state_dict(best_state)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), args.output_dir / "model.pth")
    contract = {
        "input_size": INPUT_SIZE,
        "class_names": CLASS_NAMES,
        "num_classes": len(CLASS_NAMES),
        "backbone": "efficientnet_b0",
    }
    (args.output_dir / "io_contract.json").write_text(
        json.dumps(contract, indent=2),
        encoding="utf-8",
    )
    (args.output_dir / "training_history.json").write_text(
        json.dumps(history, indent=2),
        encoding="utf-8",
    )
    final_acc = history[-1]["val_acc"] if history else 0.0
    print(  # noqa: T201
        f"saved checkpoint to {args.output_dir} "
        f"(best epoch {best_epoch}, val_acc={max(best_acc, 0.0):.4f}; "
        f"final={final_acc:.4f})"
    )
    return {
        "final_val_acc": final_acc,
        "best_val_acc": max(best_acc, 0.0),
        "best_epoch": best_epoch,
        "history": history,
    }


def _synthetic_clip_provider(source_path: str) -> np.ndarray:
    """Synthetic-frame clip provider for smoke runs without a DICOM reader."""
    frames = [
        np.full((INPUT_SIZE, INPUT_SIZE), 0.5, dtype=np.float32)
        for _ in range(8)
    ]
    return np.stack(frames)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.synthetic:
        clip_provider: Callable[[str], np.ndarray] = _synthetic_clip_provider
    else:
        from echo_personal_tool.infrastructure.dicom_reader import DicomReaderImpl
        from echo_personal_tool.infrastructure.view_recognition_dataset import (
            build_dicom_clip_provider,
        )

        clip_provider = build_dicom_clip_provider(DicomReaderImpl())
    train(args, clip_provider)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
