#!/usr/bin/env python3
"""ML.3 synthetic pretrain -> local gold fine-tune, with explicit grouped holdouts.

No clinical datasets are downloaded. An untrained backbone requires explicit
--allow-random-init; generic torchvision ImageNet init is opt-in. Outputs local.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT, ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import numpy as np  # noqa: E402
from scripts.echo_template_data import TemplateDataset, assign_group_splits, load_gold_samples, load_synthetic_samples  # noqa: E402
from scripts.echo_template_losses import atlas_bank_arrays, multitask_loss  # noqa: E402
from scripts.echo_template_network import build_template_network  # noqa: E402
from scripts.generate_synthetic_echo_corpus import load_atlases, validate_output  # noqa: E402

from echo_personal_tool.domain.services.echo_template_contract import TEMPLATE_VIEWS, default_atlases  # noqa: E402


def run_epoch(model, loader, bank, *, optimizer=None, class_weights=None):
    import torch

    model.train(optimizer is not None)
    total, count = 0.0, 0
    confusion = np.zeros((len(TEMPLATE_VIEWS), len(TEMPLATE_VIEWS)), dtype=int)
    for batch in loader:
        with torch.set_grad_enabled(optimizer is not None):
            outputs = model(batch["image"].float())
            loss, _ = multitask_loss(outputs, batch, bank, class_weights)
            if not torch.isfinite(loss):
                raise ValueError("nonfinite training loss")
            if optimizer is not None:
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                optimizer.step()
        size = len(batch["image"])
        total += float(loss.detach()) * size
        count += size
        for label, prediction in zip(batch["view"].tolist(), outputs[2].detach().argmax(-1).tolist()):
            if label >= 0:
                confusion[label, prediction] += 1
    f1 = []
    for index in range(len(TEMPLATE_VIEWS)):
        tp = confusion[index, index]
        denominator = confusion[index].sum() + confusion[:, index].sum()
        if confusion[index].sum():
            f1.append(float(2 * tp / max(denominator, 1)))
    return {
        "loss": total / max(count, 1),
        "macro_f1_present_classes": float(np.mean(f1)) if f1 else None,
        "samples": count,
    }


def train(args) -> Path:
    import torch
    from torch.utils.data import DataLoader

    output = validate_output(args.output)
    if args.epochs < 1 or args.batch_size < 2 or args.lr <= 0 or not 1 <= args.threads <= 16:
        raise ValueError("invalid training configuration")
    if not 64 <= args.input_size <= 512 or args.input_size % 32:
        raise ValueError("input size must be 64..512 divisible by 32")
    if sum(bool(x) for x in (args.checkpoint, args.imagenet, args.allow_random_init)) != 1:
        raise ValueError("select exactly one initialization source")
    if not (args.checkpoint or args.imagenet or args.allow_random_init):
        raise ValueError("select a local checkpoint, --imagenet, or explicit --allow-random-init")
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    np.random.seed(args.seed)
    atlases = default_atlases()
    supplied = load_atlases(args.atlas)
    atlases.update(supplied)
    if "A4C" in supplied:
        atlases["SUBCOSTAL"] = supplied["A4C"]
    model = build_template_network(imagenet=args.imagenet)
    if args.checkpoint:
        checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
        if checkpoint["class_names"] != list(TEMPLATE_VIEWS) or checkpoint["input_size"] != args.input_size:
            raise ValueError("incompatible checkpoint contract")
        if checkpoint["atlases"] != {k: v.to_dict() for k, v in atlases.items()}:
            raise ValueError("checkpoint atlas differs; provide matching --atlas inputs")
        model.load_state_dict(checkpoint["state_dict"], strict=True)
    samples = load_synthetic_samples(args.synthetic_manifest) if args.synthetic_manifest else []
    samples += load_gold_samples(args.gold)
    if not samples:
        raise ValueError("no local training samples")
    assign_group_splits(samples, seed=args.seed)
    stages = []
    for source in ("synthetic", "gold"):
        selected = [sample for sample in samples if sample.source == source and sample.split == "train"]
        if selected:
            stages.append((source, selected))
    val = [sample for sample in samples if sample.split == "val"]
    if not stages or (not val and not args.allow_no_val_for_smoke):
        raise ValueError("training needs train and held-out val groups; --allow-no-val-for-smoke is technical only")
    bank = {name: torch.from_numpy(values) for name, values in atlas_bank_arrays(atlases).items()}
    output.mkdir(parents=True)
    history, best = [], float("inf")
    for stage, selected in stages:
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
        generator = torch.Generator().manual_seed(args.seed)
        loader = DataLoader(
            TemplateDataset(selected, atlases, input_size=args.input_size),
            batch_size=args.batch_size,
            shuffle=True,
            generator=generator,
            num_workers=0,
        )
        stage_val = [sample for sample in val if sample.source == stage]
        if not stage_val and not args.allow_no_val_for_smoke:
            raise ValueError("each stage needs its own held-out validation groups")
        val_loader = (
            DataLoader(TemplateDataset(stage_val, atlases, input_size=args.input_size), batch_size=args.batch_size)
            if stage_val
            else None
        )
        counts = np.bincount(
            [TEMPLATE_VIEWS.index(s.view) for s in selected if s.view in TEMPLATE_VIEWS], minlength=len(TEMPLATE_VIEWS)
        )
        weights = torch.tensor(1 / np.maximum(counts, 1), dtype=torch.float32)
        weights /= weights.mean()
        # Gold fine-tuning selects within its own stage; never keep a synthetic-only checkpoint silently.
        best = float("inf")
        for epoch in range(args.epochs):
            training = run_epoch(model, loader, bank, optimizer=optimizer, class_weights=weights)
            validation = run_epoch(model, val_loader, bank) if val_loader is not None else None
            history.append({"stage": stage, "epoch": epoch + 1, "train": training, "validation": validation})
            score = validation["loss"] if validation else training["loss"]
            if score < best:
                best = score
                torch.save(
                    {
                        "schema_version": 1,
                        "architecture": "mobilenet_v3_small_fpn_template_v1",
                        "state_dict": model.state_dict(),
                        "input_size": args.input_size,
                        "class_names": list(TEMPLATE_VIEWS),
                        "atlases": {k: v.to_dict() for k, v in atlases.items()},
                        "seed": args.seed,
                        "stage": stage,
                        "clinical_validated": False,
                    },
                    output / "checkpoint.pt",
                )
        # Start the next stage from the selected checkpoint, not the last epoch.
        model.load_state_dict(torch.load(output / "checkpoint.pt", map_location="cpu", weights_only=True)["state_dict"])
    report = {
        "schema_version": 1,
        "clinical_validated": False,
        "seed": args.seed,
        "torch_version": str(torch.__version__),
        "history": history,
        "test_samples_not_used": sum(s.split == "test" for s in samples),
        "parameters": sum(p.numel() for p in model.parameters()),
        "split_counts": {key: sum(s.split == key for s in samples) for key in ("train", "val", "test")},
        "limitations": "No clinical metrics established. Macro-F1 covers only present validation classes.",
    }
    (output / "training_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return output / "checkpoint.pt"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic-manifest", type=Path)
    parser.add_argument("--gold", type=Path, action="append", default=[])
    parser.add_argument("--atlas", type=Path, action="append", default=[])
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--imagenet", action="store_true")
    parser.add_argument("--allow-random-init", action="store_true")
    parser.add_argument("--allow-no-val-for-smoke", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--input-size", type=int, default=224)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--threads", type=int, default=1)
    return parser.parse_args(argv)


def main(argv=None):
    try:
        checkpoint = train(parse_args(argv))
    except (ValueError, OSError, ImportError, KeyError) as exc:
        sys.stderr.write(f"Template training failed: {type(exc).__name__}\n")
        return 2
    sys.stdout.write(f"Candidate checkpoint: {checkpoint}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
