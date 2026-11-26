#!/usr/bin/env python3
"""Offline ML.4 EMA adaptation of a LOCAL ML.3 checkpoint; never activates weights.

Raw DICOM pixels/identities and pseudo-targets exist only in RAM. No downloads,
no external clinical datasets, no automatic corpus scan outside explicit input.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import pickle
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import numpy as np  # noqa: E402
from scripts.echo_ssl_data import check_gold_separation, load_raw_inventory, read_raw_clip  # noqa: E402
from scripts.echo_ssl_losses import cycle_prototype_loss, mesh_areas, physiology_loss, update_ema, warp_loss  # noqa: E402
from scripts.echo_ssl_training import (  # noqa: E402
    clip_geometry,
    evaluate_gold,
    forward_clip,
    motion_evidence,
    motion_landmark_ids,
    pixels_from_mesh,
    teacher_support,
    warp_pairs,
    warp_to_normalized,
)
from scripts.echo_template_data import TemplateDataset, load_gold_samples  # noqa: E402
from scripts.echo_template_losses import atlas_bank_arrays, multitask_loss  # noqa: E402
from scripts.echo_template_network import build_template_network  # noqa: E402
from scripts.generate_synthetic_echo_corpus import validate_output  # noqa: E402

from echo_personal_tool.domain.services.cardiac_atlas import CoupledShapeModel  # noqa: E402
from echo_personal_tool.domain.services.echo_ssl_objectives import candidate_reject_reasons, trusted_cycles  # noqa: E402
from echo_personal_tool.domain.services.echo_template_contract import TEMPLATE_VIEWS, validate_atlases  # noqa: E402


def teacher_context(model, loaded, bank, atlases, requested_view):
    import torch

    gray, tensors, transforms, field = loaded
    with torch.no_grad():
        outputs = forward_clip(model, torch.from_numpy(tensors))
        mesh, phase_weights, view = clip_geometry(outputs, bank, field, view=requested_view)
    pixels = pixels_from_mesh(mesh.numpy(), transforms)
    supported = teacher_support(outputs, pixels, atlases[view], view, gray.shape[1:])
    warped, weights = warp_pairs(gray, pixels, supported, atlases[view])
    return outputs, mesh, phase_weights, view, pixels, supported, warped, weights


def adapt_clip(student, teacher, anchor, loaded, bank, atlases, view, optimizer, decay):
    import torch
    from torch.nn import functional as f

    gray, tensors, transforms, field = loaded
    target, teacher_mesh, phase_weights, view, pixels, supported, warped, weights = teacher_context(
        teacher, loaded, bank, atlases, view
    )
    if not np.any(weights > 0):
        return {"trained": False, "valid_warp_nodes": 0, "phase_active": False}
    student.eval()  # Freeze BN/dropout statistics: no scanner shortcut in batch statistics.
    original = torch.from_numpy(tensors)
    noisy = original.clone()
    h = noisy.shape[-2]
    tgc = torch.linspace(0.9, 1.1, h)[None, :, None]
    # Tissue intensity is z-scored by the canonical preprocessor, NOT [0,1].
    # Clamping it would erase half the speckle rather than augment it.
    import cv2

    tissue = np.stack(
        [
            cv2.resize(
                (gray[i][t.crop_y0 : t.crop_y0 + t.crop_height, t.crop_x0 : t.crop_x0 + t.crop_width] > 1e-6).astype(
                    np.uint8
                ),
                (noisy.shape[-1], h),
                interpolation=cv2.INTER_NEAREST,
            )
            for i, t in enumerate(transforms)
        ]
    )
    changed = noisy[:, 0] * tgc + torch.randn_like(noisy[:, 0]) * 0.02
    noisy[:, 0] = torch.where(torch.from_numpy(tissue.astype(bool)), changed, original[:, 0])
    outputs = forward_clip(student, noisy)
    predicted, _, _ = clip_geometry(outputs, bank, field, view=view, phase_weights=phase_weights)
    warped_normalized = torch.from_numpy(warp_to_normalized(warped, transforms))
    temporal = warp_loss(predicted[1:], warped_normalized, torch.from_numpy(weights.astype(np.float32)))
    with torch.no_grad():
        initial = forward_clip(anchor, original)
        initial_mesh, _, _ = clip_geometry(initial, bank, field, view=view, phase_weights=phase_weights)
    preservation = f.smooth_l1_loss(predicted, initial_mesh)
    preservation = preservation + f.kl_div(outputs[2].log_softmax(-1), initial[2].softmax(-1), reduction="batchmean")
    preservation = preservation + 0.1 * f.mse_loss(outputs[1], initial[1]) + 0.1 * f.mse_loss(outputs[0], initial[0])
    atlas = atlases[view]
    # Never derive physiology from chamber predictions the teacher rejected.
    scale = torch.tensor(
        [[t.crop_width / gray.shape[2], t.crop_height / gray.shape[1]] for t in transforms], dtype=torch.float32
    )
    origin = torch.tensor(
        [[t.crop_x0 / gray.shape[2], t.crop_y0 / gray.shape[1]] for t in transforms], dtype=torch.float32
    )
    image_mesh = predicted * scale[:, None] + origin[:, None]
    areas = mesh_areas(image_mesh, atlas)
    reliable = {c: v for c, v in areas.items() if supported[:, list(atlas.structures[c])].all()}
    anatomy_zero = predicted.sum() * 0
    terms = physiology_loss(reliable, field) if reliable else {}
    physiology = sum(terms.values(), anatomy_zero)
    landmark_ids = motion_landmark_ids(atlas, supported)
    if landmark_ids:
        # Include measured time only, normalized image coordinate bounds.
        motion_terms = physiology_loss({}, field, landmarks=image_mesh[:, landmark_ids])
        physiology = physiology + motion_terms["landmark_motion"]
    contrastive = cycle_prototype_loss(outputs[3], target[3], field)
    loss = 20 * temporal + preservation + 0.05 * physiology + 0.1 * contrastive
    if not bool(torch.isfinite(loss)):
        raise ValueError("nonfinite SSL loss")
    optimizer.zero_grad()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
    optimizer.step()
    update_ema(teacher, student, decay)
    return {
        "trained": True,
        "loss": float(loss.detach()),
        "warp_loss": float(temporal.detach()),
        "valid_warp_nodes": int((weights > 0).sum()),
        "phase_active": bool((reliable or landmark_ids) and trusted_cycles(field)),
        "physiology_loss": float(physiology.detach()),
        "cycle_loss": float(contrastive.detach()),
    }


def fixed_validation_context(model, clips, args, bank, atlases):
    contexts = []
    for clip in clips:
        loaded = read_raw_clip(clip, input_size=args.input_size, max_frames=args.max_frames)
        data = teacher_context(model, loaded, bank, atlases, clip.view)
        # Cache only anonymous coordinates/quality. Re-read each validation cine
        # sequentially; keeping every decoded clip/tensor would defeat RAM limits.
        _, _, phase_weights, view, pixels, _, warped, weights = data
        contexts.append((clip, phase_weights, view, pixels, warped, weights))
    return contexts


def evaluate_motion(model, contexts, bank, atlases, args):
    import torch

    values = {c: [] for c in ("LV", "LA", "RV")}
    for clip, phase_weights, view, pixels, warped, weights in contexts:
        loaded = read_raw_clip(clip, input_size=args.input_size, max_frames=args.max_frames)
        with torch.no_grad():
            current = forward_clip(model, torch.from_numpy(loaded[1]))
            predicted, _, _ = clip_geometry(current, bank, loaded[3], view=view, phase_weights=phase_weights)
        current_pixels = pixels_from_mesh(predicted.numpy(), loaded[2])
        evidence = motion_evidence(current_pixels, pixels, warped, weights, atlases[view])
        for chamber, value in evidence.items():
            if value is not None:
                values[chamber].append(value)
    return {c: float(np.mean(v)) if v and np.isfinite(v).all() else None for c, v in values.items()}


def validate_arguments(args):
    if (
        not 1 <= args.epochs <= 50
        or not 4 <= args.max_frames <= 48
        or not 64 <= args.input_size <= 224
        or args.input_size % 32
        or not 0 < args.lr <= 0.01
        or not 0 <= args.ema_decay < 1
        or not 1 <= args.threads <= 16
    ):
        raise ValueError("invalid SSL configuration")


def train(args):
    import torch
    from torch.utils.data import DataLoader

    validate_arguments(args)
    output = validate_output(args.output)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(args.threads)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    if (
        checkpoint.get("schema_version") != 1
        or checkpoint.get("architecture") != "mobilenet_v3_small_fpn_template_v1"
        or checkpoint["class_names"] != list(TEMPLATE_VIEWS)
        or checkpoint["input_size"] != args.input_size
    ):
        raise ValueError("incompatible LOCAL ML.3 checkpoint")
    atlases = {k: CoupledShapeModel.from_dict(v) for k, v in checkpoint["atlases"].items()}
    validate_atlases(atlases)
    bank = {k: torch.from_numpy(v) for k, v in atlas_bank_arrays(atlases).items()}
    student = build_template_network().eval()
    student.load_state_dict(checkpoint["state_dict"], strict=True)
    teacher, anchor = copy.deepcopy(student).eval(), copy.deepcopy(student).eval()
    for model in (teacher, anchor):
        model.requires_grad_(False)
    clips = load_raw_inventory(
        manifest=args.manifest, dicom_dir=args.dicom_dir, seed=args.seed, max_clips=args.max_clips
    )
    gold = load_gold_samples(args.gold)
    if len(gold) > 128:
        raise ValueError("gold exceeds bounded validation/rehearsal size")
    check_gold_separation(clips, gold)
    training, validation = [c for c in clips if c.split == "train"], [c for c in clips if c.split == "val"]
    gold_train, gold_val = [s for s in gold if s.split == "train"], [s for s in gold if s.split == "val"]
    if not training or (not args.smoke and (not validation or not gold_val)):
        raise ValueError("SSL needs train raw and held-out raw/gold val; smoke is not acceptance")
    contexts = fixed_validation_context(anchor, validation, args, bank, atlases)
    before = evaluate_motion(anchor, contexts, bank, atlases, args)
    gold_before = evaluate_gold(anchor, gold_val, atlases, bank, args.input_size)
    rehearsal = (
        DataLoader(TemplateDataset(gold_train, atlases, input_size=args.input_size), batch_size=2) if gold_train else ()
    )
    optimizer = torch.optim.AdamW(student.parameters(), lr=args.lr, weight_decay=1e-4)
    output.mkdir(parents=True)
    history, best, accepted = [], float("inf"), False
    best_state, best_evidence = None, None
    for epoch in range(args.epochs):
        stats = []
        for clip in training:
            loaded = read_raw_clip(clip, input_size=args.input_size, max_frames=args.max_frames)
            stats.append(
                adapt_clip(student, teacher, anchor, loaded, bank, atlases, clip.view, optimizer, args.ema_decay)
            )
        for batch in rehearsal:
            student.eval()
            loss, _ = multitask_loss(student(batch["image"]), batch, bank)
            if not bool(torch.isfinite(loss)):
                raise ValueError("nonfinite gold rehearsal")
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
            optimizer.step()
            update_ema(teacher, student, args.ema_decay)
        student.eval()
        after = evaluate_motion(student, contexts, bank, atlases, args)
        gold_after = evaluate_gold(student, gold_val, atlases, bank, args.input_size)
        reasons = candidate_reject_reasons(before, after, gold_before, gold_after)
        evidence = {
            "jitter_before_px": before,
            "jitter_after_px": after,
            "gold_before": gold_before,
            "gold_after": gold_after,
            "reject_reasons": list(reasons),
            "accepted": not reasons,
            "epoch": epoch + 1,
        }
        history.append({**evidence, "training": stats})
        score = sum(v for v in after.values() if v is not None)
        if not reasons and score < best:
            best, best_state, best_evidence, accepted = score, copy.deepcopy(student.state_dict()), evidence, True
    # Always preserve a diagnostic candidate; only a passed gate gets the normal
    # checkpoint name. Never write source/group identities, optimizer batches or pixels.
    final = {
        k: v
        for k, v in checkpoint.items()
        if k in {"schema_version", "architecture", "input_size", "class_names", "atlases"}
    }
    final["atlases"] = {k: {**v.to_dict(), "provenance": "local_ssl_unvalidated"} for k, v in atlases.items()}
    final.update(
        state_dict=best_state if accepted else student.state_dict(),
        stage="ssl",
        clinical_validated=False,
        ssl_acceptance=best_evidence if accepted else history[-1],
    )
    target = output / ("checkpoint.pt" if accepted else "candidate_rejected.pt")
    torch.save(final, target)
    report = {
        "schema_version": 1,
        "clinical_validated": False,
        "accepted": accepted,
        "smoke": args.smoke,
        "seed": args.seed,
        "torch_version": str(torch.__version__),
        "history": history,
        "raw_split_counts": {s: sum(c.split == s for c in clips) for s in ("train", "val", "test")},
        "test_pixels_used": False,
        "ema_decay": args.ema_decay,
        "optional_atlas_image_ncc_loss": False,
        "limitations": "Technical local gate, not clinical validation. No activation.",
    }
    (output / "ssl_report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    return target


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path)
    source.add_argument("--dicom-dir", type=Path)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gold", type=Path, action="append", default=[])
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--max-clips", type=int, default=64)
    parser.add_argument("--max-frames", type=int, default=48)
    parser.add_argument("--input-size", type=int, default=224)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--ema-decay", type=float, default=0.99)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--smoke", action="store_true", help="allow missing val evidence, never waive acceptance")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    previous_logging_threshold = logging.root.manager.disable
    try:
        # DICOM decoders may include tag values/filenames in library diagnostics.
        # Standalone CLI emits only its fixed aggregate status, even on failure.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            logging.disable(logging.CRITICAL)
            train(args)
    except (
        ValueError,
        OSError,
        ImportError,
        KeyError,
        RuntimeError,
        TypeError,
        IndexError,
        AttributeError,
        pickle.UnpicklingError,
        EOFError,
        OverflowError,
    ):
        # No paths, UIDs, patient data or arbitrary DICOM exception text on stderr.
        sys.stderr.write("Local SSL adaptation failed; check local inputs and configuration.\n")
        return 2
    finally:
        logging.disable(previous_logging_threshold)
    sys.stdout.write("Local experimental SSL candidate/report written; no model activated.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
