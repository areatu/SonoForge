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

from echo_personal_tool.domain.models.view_recognition import KNOWN_VIEWS
from echo_personal_tool.domain.services.view_recognition_inference import preprocess_frame
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
        "--synthetic",
        action="store_true",
        help="use synthetic clips instead of real DICOM frames (smoke runs)",
    )
    args = parser.parse_args(argv)
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
    """Turn ``(N, H, W)`` normalized clips into a ``(N, 3, H, W)`` float tensor.

    Each frame is resized to ``INPUT_SIZE`` and expanded to 3 channels, matching
    the ONNX preprocessing contract used by the adapter.
    """
    batch = np.stack(
        [np.stack([preprocess_frame(frame) for frame in clip]) for clip in clips],
        axis=0,
    ).astype(np.float32)
    return torch.from_numpy(batch).permute(0, 3, 1, 2).contiguous()


def _run_epoch(
    model: nn.Module,
    loader: DataLoader[tuple[np.ndarray, int]],
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> float:
    model.train()
    total_loss = 0.0
    total_count = 0
    criterion = nn.CrossEntropyLoss()
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
) -> float:
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for clips, targets in loader:
            inputs = _to_logits_batch(clips).to(device)
            labels = torch.as_tensor(targets, dtype=torch.long, device=device)
            preds = model(inputs).argmax(dim=1)
            correct += int((preds == labels).sum().item())
            total += int(labels.shape[0])
    return correct / max(total, 1)


def _make_loader(
    split: str,
    manifest_path: Path,
    clip_provider: Callable[[str], np.ndarray],
    batch_size: int,
    subset_limit: int,
    shuffle: bool,
) -> DataLoader[tuple[np.ndarray, int]]:
    manifest = load_manifest(manifest_path)
    dataset = ViewRecognitionDataset(manifest, clip_provider, split=split)
    if subset_limit:
        dataset._samples = dataset._samples[:subset_limit]  # noqa: SLF001 - script-local trim
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=0,
        drop_last=False,
    )


def train(args: TrainArgs, clip_provider: Callable[[str], np.ndarray]) -> dict[str, Any]:
    _set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_loader = _make_loader(
        "train", args.manifest_path, clip_provider, args.batch_size, args.subset_limit, True
    )
    val_loader = _make_loader(
        "val", args.manifest_path, clip_provider, args.batch_size, args.subset_limit, False
    )
    model = _build_backbone(len(CLASS_NAMES)).to(device)
    # Transfer learning: freeze the feature extractor, train only the new
    # classifier head.
    for param in model.features.parameters():
        param.requires_grad_(False)
    trainable = [param for param in model.parameters() if param.requires_grad]
    optimizer = torch.optim.Adam(trainable, lr=args.learning_rate)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max(args.epochs, 1),
        eta_min=args.learning_rate * 0.01,
    )

    history: list[dict[str, float]] = []
    for epoch in range(1, args.epochs + 1):
        train_loss = _run_epoch(model, train_loader, optimizer, device)
        val_acc = _evaluate_accuracy(model, val_loader, device)
        scheduler.step()
        history.append({"epoch": epoch, "train_loss": train_loss, "val_acc": val_acc})
        print(
            f"epoch {epoch}/{args.epochs}: "
            f"loss={train_loss:.4f} val_acc={val_acc:.4f}"
        )

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
    print(f"saved checkpoint to {args.output_dir} (final val_acc={final_acc:.4f})")
    return {"final_val_acc": final_acc, "history": history}


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
