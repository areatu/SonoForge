#!/usr/bin/env python3
"""Offline local review queue: prototype distance + NCC-supported warp disagreement.

No downloads, pseudo-gold, model activation or copied patient identifiers/paths.
Queue clip_index refers back to the user's explicit input manifest in place.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT, ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import numpy as np  # noqa: E402
from scripts.echo_ssl_data import load_raw_inventory, read_raw_clip  # noqa: E402
from scripts.generate_synthetic_echo_corpus import validate_output  # noqa: E402

from echo_personal_tool.domain.services.echo_active_mining import (  # noqa: E402
    ClipUncertainty,
    normalized_warp_disagreement,
    prototype_distance,
    rank_uncertain_clips,
)
from echo_personal_tool.domain.services.echo_ssl_tracking import track_ssl_nodes  # noqa: E402
from echo_personal_tool.domain.services.echo_template_service import decode_template_prediction  # noqa: E402


def clip_evidence(engine, clip, clip_index, *, max_frames):
    gray, _, _, _ = read_raw_clip(clip, input_size=engine.input_size, max_frames=max_frames)
    cosines, observations, targets, qualities = [], [], [], []
    previous = None
    for i, frame in enumerate(gray):
        heads, transform = engine.raw(frame)
        # ED/ES head is an explicit estimate here, not a measured clinical phase.
        phase = "ED" if int(heads["phase_logits"][0].argmax()) == 0 else "ES"
        prediction = decode_template_prediction(
            heads,
            engine.atlases,
            transform,
            frame,
            phase=phase,
            frame_index=i,
            pixel_spacing=None,
            sector_mask=frame > 1e-6,
            requested_view=clip.view,
            refine_rv=False,
            **engine.ood,
        )
        cosines.append(heads["view_cosines"][0])
        visibility = 1 / (1 + np.exp(-np.clip(heads["visibility"][0], -40, 40)))
        required = {"LV": (0, 1, 5), "LA": (0, 1, 7), "RV": (2, 3, 6)}
        contours = {
            c.chamber: np.asarray(c.points)
            for c in prediction.contours
            if c.chamber in required and np.min(visibility[list(required[c.chamber])]) >= 0.5
        }
        if previous is not None:
            old_view, old = previous
            for chamber, points in contours.items():
                start = old.get(chamber)
                if prediction.view != old_view or start is None or start.shape != points.shape:
                    continue
                warp = track_ssl_nodes(
                    gray[i - 1], frame, start, reference_sector=gray[i - 1] > 1e-6, target_sector=frame > 1e-6
                )
                observations.append(points)
                targets.append(warp.positions)
                qualities.append(warp.weights)
        previous = prediction.view, contours
    weights = np.concatenate(qualities) if qualities else np.empty(0)
    disagreement = (
        normalized_warp_disagreement(
            np.concatenate(observations),
            np.concatenate(targets),
            weights,
            image_diagonal=float(np.hypot(*gray.shape[1:])),
        )
        if qualities
        else None
    )
    return ClipUncertainty(
        clip_index, prototype_distance(np.stack(cosines)), disagreement, int(np.count_nonzero(weights))
    )


def load_evidence(path):
    if path.stat().st_size > 1024**2:
        raise ValueError("oversized numeric evidence")
    data = json.loads(path.read_text())
    if set(data) != {"schema_version", "clips"} or data["schema_version"] != 1 or len(data["clips"]) > 4096:
        raise ValueError("invalid evidence schema")
    result = []
    for row in data["clips"]:
        if set(row) != {"clip_index", "cosines", "warp_disagreement", "valid_warp_nodes"}:
            raise ValueError("only numeric mining evidence is accepted")
        result.append(
            ClipUncertainty(
                row["clip_index"],
                prototype_distance(np.asarray(row["cosines"])),
                row["warp_disagreement"],
                row["valid_warp_nodes"],
            )
        )
    return result


def mine(args):
    output = validate_output(args.output)
    if not 4 <= args.max_frames <= 48 or not 1 <= args.max_clips <= 1024:
        raise ValueError("invalid mining memory limits")
    if args.evidence is not None:
        if args.bundle is not None:
            raise ValueError("choose numeric evidence or local inference, not both")
        evidence = load_evidence(args.evidence)
    else:
        if args.bundle is None:
            raise ValueError("raw mining needs a local verified template bundle")
        from echo_personal_tool.infrastructure.echo_template_engine import EchoTemplateEngine

        engine = EchoTemplateEngine(args.bundle, allow_unvalidated=args.allow_unvalidated)
        clips = load_raw_inventory(manifest=args.manifest, dicom_dir=None, max_clips=args.max_clips)
        # Do not mine validation/test clips into a potential training-review queue.
        evidence = [
            clip_evidence(engine, c, index, max_frames=args.max_frames)
            for index, c in enumerate(clips)
            if c.split == "train"
        ]
    ranked = rank_uncertain_clips(evidence, top_k=args.top_k)
    output.mkdir(parents=True)
    path = output / "review_queue.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "expert_review_only",
                "clinical_validated": False,
                "scored_clips": len(evidence),
                "queue": [asdict(c) for c in ranked],
            },
            allow_nan=False,
            indent=2,
        )
    )
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path, help="ML.4 raw manifest; mine train split only")
    source.add_argument("--evidence", type=Path, help="bounded numeric inference evidence (no paths/UIDs)")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--allow-unvalidated", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-clips", type=int, default=64)
    parser.add_argument("--max-frames", type=int, default=24)
    return parser.parse_args(argv)


def main(argv=None):
    previous = logging.root.manager.disable
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            logging.disable(logging.CRITICAL)
            mine(parse_args(argv))
    except (ValueError, OSError, ImportError, RuntimeError, KeyError, TypeError, AttributeError, IndexError):
        sys.stderr.write("Local active mining failed; check configuration and evidence.\n")
        return 2
    finally:
        logging.disable(previous)
    sys.stdout.write("Local expert-review queue written; no labels or model activation.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
