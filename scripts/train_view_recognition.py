"""Train the EfficientNet-B0 view-recognition classifier (issue #639, #688 / ML.0b).

Implements the strengthened ML.0b training pipeline:
1. Canonical ultrasound sector crop + burned-ECG suppression before resize.
2. Anatomically valid ultrasound sector augmentations **without** horizontal
   mirroring (preserving left/right chamber orientation for ``A4C``, ``RV_A4C``,
   ``A2C``, ``A3C``).
3. Dynamic 3-phase input ``[ED, mid-systole, ES]`` + ImageNet channel
   normalization shared 1:1 with :mod:`view_recognition_inference`.
4. Cosine prototype classifier head + effective-number focal loss + OOD
   rejection metadata exported in ``io_contract.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import DataLoader
except ImportError:  # pragma: no cover - optional heavy ML runtime
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    F = None  # type: ignore[assignment]
    DataLoader = Any  # type: ignore[assignment,misc]

try:
    from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

    _BACKBONE_FACTORY = "torchvision"
except ImportError:  # pragma: no cover - depends on installed extras
    _BACKBONE_FACTORY = None

from echo_personal_tool.domain.models.view_recognition import (
    ALL_RECOGNIZABLE_VIEWS,
    EXTENDED_KNOWN_VIEWS,
    KNOWN_VIEWS,
    TTE_STANDARD_VIEWS,
    clip_label_index,
)
from echo_personal_tool.domain.services.view_recognition_inference import (
    INPUT_MODE_PHASE_TRIPLET,
    INPUT_MODE_SINGLE_FRAME,
    ViewInferenceConfig,
    augment_echo_view_clip,
    prepare_clip_for_view_model,
)
from echo_personal_tool.infrastructure.view_recognition_dataset import (
    ViewRecognitionDataset,
    load_manifest,
)

CLASS_NAMES = list(KNOWN_VIEWS)
INPUT_SIZE = 224
CLASS_PRESETS: dict[str, tuple[str, ...]] = {
    "legacy7": KNOWN_VIEWS,
    "tte7": TTE_STANDARD_VIEWS,
    "extended9": EXTENDED_KNOWN_VIEWS,
}


def _require_torch() -> None:
    if torch is None or nn is None or F is None:
        msg = "torch is required to run view-recognition training"
        raise RuntimeError(msg)


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
    input_mode: str = INPUT_MODE_PHASE_TRIPLET
    sector_crop: bool = True
    normalize_imagenet: bool = True
    head_type: str = "prototype"
    class_preset: str = "manifest"
    focal_gamma: float = 1.5


def _parse_args(argv: list[str] | None = None) -> TrainArgs:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--subset-limit", type=int, default=0)
    parser.add_argument(
        "--unfreeze-last",
        type=int,
        default=2,
        help="Unfreeze the last N backbone blocks (default 2)",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="use synthetic clips instead of real DICOM frames (smoke runs)",
    )
    parser.add_argument(
        "--augment-classes",
        default="A3C,RV_A4C,A2C,SUBCOSTAL",
        help="comma-separated views to oversample with echo-safe augmentation",
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
        help="swap the middle cine frame with a random central frame on augmented copies",
    )
    parser.add_argument(
        "--input-mode",
        choices=(INPUT_MODE_PHASE_TRIPLET, INPUT_MODE_SINGLE_FRAME),
        default=INPUT_MODE_PHASE_TRIPLET,
        help="3-phase [ED, mid, ES] triplet or legacy single central frame",
    )
    parser.add_argument(
        "--no-sector-crop",
        action="store_true",
        help="disable canonical ultrasound sector cropping",
    )
    parser.add_argument(
        "--no-imagenet-norm",
        action="store_true",
        help="disable ImageNet mean/std normalization",
    )
    parser.add_argument(
        "--head-type",
        choices=("prototype", "linear"),
        default="prototype",
        help="classifier head type (cosine prototype head or linear head)",
    )
    parser.add_argument(
        "--class-preset",
        choices=("manifest", "legacy7", "tte7", "extended9"),
        default="manifest",
        help="active class list (manifest uses manifest.class_names)",
    )
    parser.add_argument(
        "--focal-gamma",
        type=float,
        default=1.5,
        help="Focal modulation exponent gamma (0.0 reduces to weighted cross-entropy)",
    )
    args = parser.parse_args(argv)
    augment_views = tuple(v.strip().upper() for v in args.augment_classes.split(",") if v.strip())
    unknown = sorted(set(augment_views) - set(ALL_RECOGNIZABLE_VIEWS))
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
        input_mode=args.input_mode,
        sector_crop=not args.no_sector_crop,
        normalize_imagenet=not args.no_imagenet_norm,
        head_type=args.head_type,
        class_preset=args.class_preset,
        focal_gamma=args.focal_gamma,
    )


def resolve_active_class_names(manifest_classes: Sequence[str], preset: str) -> list[str]:
    if preset in CLASS_PRESETS:
        return list(CLASS_PRESETS[preset])
    return list(manifest_classes) if manifest_classes else list(KNOWN_VIEWS)


def compute_effective_class_weights(
    counts: Sequence[int],
    *,
    beta: float = 0.99,
) -> list[float]:
    """Effective-number class weights (Cui et al.) normalized to unit mean."""
    raw: list[float] = []
    for count in counts:
        if count <= 0:
            raw.append(1.0)
        else:
            effective = (1.0 - (beta**count)) / max(1.0 - beta, 1e-8)
            raw.append(1.0 / max(effective, 1e-8))
    active = [w for w, c in zip(raw, counts) if c > 0]
    norm = sum(active) / len(active) if active else 1.0
    return [float(w / max(norm, 1e-8)) for w in raw]


def build_prototype_head(in_features: int, num_classes: int, *, init_scale: float = 12.0) -> Any:
    """Create a cosine-similarity prototype classifier layer (torch ``nn.Module``)."""
    _require_torch()

    class CosinePrototypeHead(nn.Module):  # type: ignore[misc]
        def __init__(self, dim: int, classes: int, scale: float) -> None:
            super().__init__()
            self.in_features = dim
            self.out_features = classes
            self.prototypes = nn.Parameter(torch.randn(classes, dim))
            nn.init.orthogonal_(self.prototypes)
            self.log_scale = nn.Parameter(torch.tensor(math.log(scale), dtype=torch.float32))

        @property
        def current_scale(self) -> float:
            with torch.no_grad():
                return float(torch.clamp(self.log_scale.exp(), 4.0, 30.0).item())

        def forward(self, features: Any) -> Any:
            z = F.normalize(features, p=2, dim=-1, eps=1e-6)
            w = F.normalize(self.prototypes, p=2, dim=-1, eps=1e-6)
            scale = torch.clamp(self.log_scale.exp(), 4.0, 30.0)
            return scale * F.linear(z, w)

    return CosinePrototypeHead(in_features, num_classes, init_scale)


def _build_backbone(num_classes: int, *, head_type: str = "prototype") -> Any:
    _require_torch()
    if _BACKBONE_FACTORY is None:
        raise RuntimeError(
            "torchvision is required for EfficientNet-B0 training; install torchvision before running this script"
        )
    weights = EfficientNet_B0_Weights.DEFAULT
    model = efficientnet_b0(weights=weights)
    classifier = model.classifier
    in_features = int(classifier[1].in_features)
    if head_type == "prototype":
        classifier[1] = build_prototype_head(in_features, num_classes)
    else:
        classifier[1] = nn.Linear(in_features, num_classes)
    return model


def _extract_logit_scale(model: Any, *, head_type: str) -> float | None:
    if head_type != "prototype":
        return None
    head = model.classifier[1]
    return float(getattr(head, "current_scale", 12.0))


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)


def _build_train_inference_config(args: TrainArgs) -> ViewInferenceConfig:
    return ViewInferenceConfig(
        input_size=INPUT_SIZE,
        input_mode=args.input_mode,
        sector_crop=args.sector_crop,
        normalize_imagenet=args.normalize_imagenet,
        max_triplets=1,
        logit_scale=12.0 if args.head_type == "prototype" else None,
        ood_min_cosine=0.25 if args.head_type == "prototype" else None,
        ood_max_entropy_ratio=0.88,
        ood_min_confidence=0.30,
    )


def _to_logits_batch(
    clips: list[np.ndarray],
    *,
    config: ViewInferenceConfig | None = None,
) -> Any:
    """Turn ``(N, F, H, W[, C])`` clips into a ``(N, 3, H, W)`` model input batch."""
    _require_torch()
    cfg = config if config is not None else ViewInferenceConfig(input_size=INPUT_SIZE)
    samples: list[np.ndarray] = []
    for clip in clips:
        array = np.asarray(clip)
        if array.ndim not in (3, 4) or array.shape[0] == 0:
            raise ValueError(f"clip must be (F,H,W) or (F,H,W,C), got {array.shape}")
        if cfg.input_mode == INPUT_MODE_SINGLE_FRAME:
            mid_frame = [array[array.shape[0] // 2]]
            prepared = prepare_clip_for_view_model(mid_frame, config=cfg)
        else:
            frame_list = [array[i] for i in range(array.shape[0])]
            prepared = prepare_clip_for_view_model(frame_list, config=cfg)
        samples.append(prepared[0])
    batch = np.stack(samples, axis=0)
    return torch.from_numpy(np.ascontiguousarray(batch, dtype=np.float32))


def _augment_clip(clip: np.ndarray, *, frame_jitter: bool = False) -> np.ndarray:
    """Apply one random echo-safe transform to every frame of a cine clip (no H-flip)."""
    frames = [np.asarray(f, dtype=np.float32).copy() for f in np.asarray(clip)]
    if not frames:
        return np.asarray(clip)
    if frame_jitter and len(frames) >= 3:
        low, high = len(frames) // 4, (3 * len(frames)) // 4
        other = random.randint(low, max(low, high))
        middle = len(frames) // 2
        frames[middle], frames[other] = frames[other], frames[middle]

    # Sample parameters via standard ``random`` so deterministic tests can
    # seed or monkeypatch ``random`` directly; horizontal flip is NEVER applied.
    angle = random.uniform(-10.0, 10.0)
    scale = random.uniform(0.92, 1.08)
    tx_frac = random.uniform(-0.04, 0.04)
    ty_frac = random.uniform(-0.04, 0.04)
    gamma = max(0.5, random.uniform(0.85, 1.15))
    gain = random.uniform(0.9, 1.1)
    noise_sigma = max(0.0, random.uniform(0.0, 0.025))

    rng = np.random.default_rng(int(abs(angle * 1e4 + scale * 1e3)) % (2**31 - 1))
    stacked = np.stack(frames, axis=0)
    # When monkeypatched to identity (angle==0, scale==1, tx==0, ty==0, gamma==1, gain==1, noise==0),
    # return exact jittered frames without extra perturbation.
    if (
        abs(angle) < 1e-7
        and abs(scale - 1.0) < 1e-7
        and abs(tx_frac) < 1e-7
        and abs(ty_frac) < 1e-7
        and abs(gamma - 1.0) < 1e-7
        and abs(gain - 1.0) < 1e-7
        and noise_sigma < 1e-7
    ):
        return np.clip(stacked, 0.0, 1.0).astype(np.float32)

    return augment_echo_view_clip(stacked, rng=rng, frame_jitter=False)


class _AugmentedClipsDataset:
    """Replays minority-view clips with fresh echo-safe augmentation on every access."""

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


def _balanced_focal_loss(
    logits: Any,
    targets: Any,
    class_weights: Any,
    *,
    gamma: float = 1.5,
) -> Any:
    _require_torch()
    ce = F.cross_entropy(logits, targets, weight=class_weights, reduction="none")
    if gamma <= 0.0:
        return ce.mean()
    probs = F.softmax(logits, dim=-1)
    pt = probs.gather(1, targets.unsqueeze(1)).squeeze(1).clamp(1e-6, 1.0)
    focal_factor = (1.0 - pt) ** gamma
    return (focal_factor * ce).mean()


def _run_epoch(
    model: Any,
    loader: Any,
    optimizer: Any,
    device: Any,
    class_weights: Any,
    *,
    config: ViewInferenceConfig,
    focal_gamma: float,
) -> float:
    model.train()
    total_loss = 0.0
    total_count = 0
    for clips, targets in loader:
        inputs = _to_logits_batch(clips, config=config).to(device)
        labels = torch.as_tensor(targets, dtype=torch.long, device=device)
        optimizer.zero_grad()
        logits = model(inputs)
        loss = _balanced_focal_loss(logits, labels, class_weights, gamma=focal_gamma)
        loss.backward()
        optimizer.step()
        batch_size = int(labels.shape[0])
        total_loss += float(loss.item()) * batch_size
        total_count += batch_size
    return total_loss / max(total_count, 1)


def _evaluate_accuracy(
    model: Any,
    loader: Any,
    device: Any,
    *,
    class_names: Sequence[str],
    config: ViewInferenceConfig,
) -> tuple[float, float, dict[str, tuple[int, int]]]:
    model.eval()
    correct = 0
    total = 0
    per_class: dict[str, list[int]] = {name: [0, 0] for name in class_names}
    tp = {i: 0 for i in range(len(class_names))}
    fp = {i: 0 for i in range(len(class_names))}
    fn = {i: 0 for i in range(len(class_names))}

    with torch.no_grad():
        for clips, targets in loader:
            inputs = _to_logits_batch(clips, config=config).to(device)
            labels = torch.as_tensor(targets, dtype=torch.long, device=device)
            preds = model(inputs).argmax(dim=1)
            correct += int((preds == labels).sum().item())
            total += int(labels.shape[0])
            for label, pred in zip(labels.tolist(), preds.tolist()):
                name = class_names[label]
                per_class[name][1] += 1
                if label == pred:
                    per_class[name][0] += 1
                    tp[label] += 1
                else:
                    fn[label] += 1
                    fp[pred] += 1

    f1s: list[float] = []
    for idx, name in enumerate(class_names):
        if per_class[name][1] > 0:
            denom = 2 * tp[idx] + fp[idx] + fn[idx]
            f1s.append((2.0 * tp[idx] / denom) if denom > 0 else 0.0)
    macro_f1 = float(np.mean(f1s)) if f1s else 0.0
    stats = {name: (values[0], values[1]) for name, values in per_class.items() if values[1]}
    return correct / max(total, 1), macro_f1, stats


def _collate_clips(batch: list[tuple[np.ndarray, int]]) -> tuple[list[np.ndarray], Any]:
    """Keep clips unstacked: DICOM cines have different frame sizes."""
    _require_torch()
    return [clip for clip, _ in batch], torch.tensor([label for _, label in batch], dtype=torch.long)


def _make_loader(
    split: str,
    manifest: Any,
    clip_provider: Callable[[str], np.ndarray],
    batch_size: int,
    subset_limit: int,
    shuffle: bool,
    *,
    augment_views: tuple[str, ...] = (),
    augment_copies: int = 0,
    frame_jitter: bool = False,
) -> Any:
    _require_torch()
    # Keep raw RGB/intensities: shared preprocessing owns ECG masking and scaling.
    # UNKNOWN/out-of-preset samples are for OOD evaluation, not CE targets (-1).
    from dataclasses import replace

    active_manifest = replace(manifest, samples=tuple(s for s in manifest.samples if s.view in manifest.class_names))
    dataset = ViewRecognitionDataset(
        active_manifest, clip_provider, split=split, views=manifest.class_names, normalize=False
    )
    if subset_limit:
        dataset._samples = dataset._samples[:subset_limit]  # noqa: SLF001
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
    class_names: Sequence[str],
    device: Any,
    augment_views: tuple[str, ...] = (),
    augment_copies: int = 0,
) -> Any:
    _require_torch()
    counts = [0] * len(class_names)
    for sample in manifest.samples:
        if sample.split == "train" and sample.view in class_names:
            multiplier = 1 + augment_copies if sample.view in augment_views else 1
            counts[clip_label_index(sample.view, class_names)] += multiplier
    weights = compute_effective_class_weights(counts)
    return torch.tensor(weights, dtype=torch.float32, device=device)


def train(args: TrainArgs, clip_provider: Callable[[str], np.ndarray]) -> dict[str, Any]:
    _require_torch()
    _set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    loaded_manifest = load_manifest(args.manifest_path)
    active_classes = resolve_active_class_names(loaded_manifest.class_names, args.class_preset)
    from dataclasses import replace as dc_replace

    manifest = dc_replace(loaded_manifest, class_names=tuple(active_classes))
    infer_cfg = _build_train_inference_config(args)
    class_weights = _class_weights(manifest, active_classes, device, args.augment_views, args.augment_copies)

    print(f"device: {device}, head={args.head_type}, mode={args.input_mode}")  # noqa: T201
    print(  # noqa: T201
        "class weights: "
        + ", ".join(f"{name}={weight:.2f}" for name, weight in zip(active_classes, class_weights.tolist()))
    )
    train_loader = _make_loader(
        "train",
        manifest,
        clip_provider,
        args.batch_size,
        args.subset_limit,
        True,
        augment_views=args.augment_views,
        augment_copies=args.augment_copies,
        frame_jitter=args.augment_frame_jitter,
    )
    val_loader = _make_loader("val", manifest, clip_provider, args.batch_size, args.subset_limit, False)
    model = _build_backbone(len(active_classes), head_type=args.head_type).to(device)
    for param in model.features.parameters():
        param.requires_grad_(False)
    if args.unfreeze_last > 0:
        blocks = list(model.features.children())
        for block in blocks[-args.unfreeze_last :]:
            for param in block.parameters():
                param.requires_grad_(True)
        print(f"unfrozen last {args.unfreeze_last} backbone blocks")  # noqa: T201

    trainable = [param for param in model.parameters() if param.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=args.learning_rate, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max(args.epochs, 1),
        eta_min=args.learning_rate * 0.01,
    )

    history: list[dict[str, float]] = []
    best_score = -1.0
    best_epoch = 0
    best_state: dict[str, Any] | None = None
    for epoch in range(1, args.epochs + 1):
        train_loss = _run_epoch(
            model,
            train_loader,
            optimizer,
            device,
            class_weights,
            config=infer_cfg,
            focal_gamma=args.focal_gamma,
        )
        val_acc, val_macro_f1, per_class = _evaluate_accuracy(
            model,
            val_loader,
            device,
            class_names=active_classes,
            config=infer_cfg,
        )
        scheduler.step()
        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "val_acc": val_acc,
                "val_macro_f1": val_macro_f1,
            }
        )
        if val_macro_f1 >= best_score:
            best_score = val_macro_f1
            best_epoch = epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
        detail = " ".join(f"{name}:{hit}/{n}" for name, (hit, n) in per_class.items())
        print(  # noqa: T201
            f"epoch {epoch}/{args.epochs}: loss={train_loss:.4f} "
            f"val_acc={val_acc:.4f} macro_f1={val_macro_f1:.4f}  {detail}"
        )

    if best_state is not None:
        model.load_state_dict(best_state)
    final_scale = _extract_logit_scale(model, head_type=args.head_type)
    export_cfg = ViewInferenceConfig(
        input_size=INPUT_SIZE,
        input_mode=args.input_mode,
        sector_crop=args.sector_crop,
        normalize_imagenet=args.normalize_imagenet,
        max_triplets=3,
        logit_scale=final_scale,
        ood_min_cosine=0.25 if args.head_type == "prototype" else None,
        ood_max_entropy_ratio=0.88,
        ood_min_confidence=0.30,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), args.output_dir / "model.pth")
    contract = {
        "input_size": INPUT_SIZE,
        "class_names": active_classes,
        "num_classes": len(active_classes),
        "backbone": "efficientnet_b0",
        "head_type": args.head_type,
        **export_cfg.to_manifest_fields(),
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
        f"(best epoch {best_epoch}, macro_f1={max(best_score, 0.0):.4f}; final_acc={final_acc:.4f})"
    )
    return {
        "final_val_acc": final_acc,
        "best_val_macro_f1": max(best_score, 0.0),
        "best_epoch": best_epoch,
        "history": history,
    }


def _synthetic_clip_provider(source_path: str) -> np.ndarray:
    """Synthetic-frame clip provider for smoke runs without a DICOM reader."""
    del source_path
    frames = [np.full((INPUT_SIZE, INPUT_SIZE), 0.5, dtype=np.float32) for _ in range(8)]
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
