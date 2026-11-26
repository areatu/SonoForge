#!/usr/bin/env python3
"""Local accepted measurements -> anonymous WEAK atlas shape targets, never gold.

No DICOM reads, inference, patient tags, image writes or model activation. Source
identities are used only in RAM to join the existing measurement/decision stores.
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
from scripts.generate_synthetic_echo_corpus import load_atlases, validate_output  # noqa: E402

from echo_personal_tool.domain.models.view_recognition import ViewDecisionSource  # noqa: E402
from echo_personal_tool.domain.services.echo_template_contract import default_atlases  # noqa: E402
from echo_personal_tool.domain.services.echo_weak_labels import reconstruct_weak_shape  # noqa: E402
from echo_personal_tool.infrastructure.measurement_codec import MeasurementStorageError
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository  # noqa: E402
from echo_personal_tool.infrastructure.view_decision_store import JsonViewDecisionStore  # noqa: E402


def accepted_anchors(data, instance_to_series, decisions):
    """Missing landmarks and pending/automatic view decisions are NOT labels.

    The current store's accepted state (review_pending=False), explicit anchors
    and a MANUAL view are all required. Do not derive an apex from a dense arc.
    Conflicting repeats at the same chamber/frame are excluded rather than
    choosing a convenient physician contour silently.
    """
    candidates = {}
    for contour in data.contours:
        series = instance_to_series.get(contour.sop_instance_uid)
        decision = decisions.get(series)
        if (
            contour.review_pending
            or contour.chamber not in {"LV", "LA", "RV"}
            or contour.phase not in {"ED", "ES"}
            or contour.frame_index is None
            or contour.frame_index < 0
            or contour.mitral_annulus is None
            or contour.apex_landmark is None
            or decision is None
            or decision.source is not ViewDecisionSource.MANUAL
            or decision.view != contour.view
        ):
            continue
        key = (contour.sop_instance_uid, contour.frame_index, contour.chamber, contour.phase)
        candidates.setdefault(key, []).append(contour)
    selected = []
    for group in candidates.values():
        signatures = {(*c.mitral_annulus, c.apex_landmark) for c in group}
        if len(signatures) == 1:
            selected.append(group[-1])
    # LV and LA measured on the same frame share the mitral valve. Never
    # average away conflicting real anchors to manufacture coupled anatomy.
    valves = {}
    for contour in selected:
        if contour.chamber in {"LV", "LA"}:
            key = (contour.sop_instance_uid, contour.frame_index, contour.phase)
            valves.setdefault(key, set()).add(contour.mitral_annulus)
    return [c for c in selected if c.chamber == "RV" or len(valves[(c.sop_instance_uid, c.frame_index, c.phase)]) == 1]


def anonymous_sector(study, uid, frame_index, root):
    relative = study.get("sectors", {}).get(uid)
    if relative is None:
        return None
    path = Path(relative)
    path = path if path.is_absolute() else root / path
    if path.suffix != ".npy" or path.is_symlink() or path.stat().st_size > 128 * 1024**2:
        raise ValueError("invalid anonymous sector array")
    frames = np.load(path, allow_pickle=False, mmap_mode="r")
    if (
        frames.ndim != 3
        or frames.dtype.kind not in "uif"
        or max(frames.shape[1:]) > 1024
        or not 0 <= frame_index < len(frames)
    ):
        raise ValueError("invalid sector shape/frame")
    return np.asarray(frames[frame_index])


def harvest(args):
    output = validate_output(args.output)
    if args.index.stat().st_size > 1024**2:
        raise ValueError("oversized local index")
    index = json.loads(args.index.read_text())
    if (
        set(index) != {"schema_version", "studies"}
        or index["schema_version"] != 1
        or not 1 <= len(index["studies"]) <= 128
    ):
        raise ValueError("invalid bounded study index")
    repository = MeasurementRepository(args.measurements_dir)
    store = JsonViewDecisionStore(args.view_decisions_dir)
    atlases = default_atlases()
    if len(getattr(args, "atlas", [])) > 7:
        raise ValueError("too many local atlases")
    atlases.update(load_atlases(getattr(args, "atlas", [])))
    examples, seen, counts = [], set(), {"accepted_anchor_sets": 0, "rejected_geometry": 0, "missing_sector": 0}
    for study in index["studies"]:
        if not {"study_uid", "instance_to_series"} <= study.keys() or set(study) - {
            "study_uid",
            "instance_to_series",
            "sectors",
        }:
            raise ValueError("invalid study index entry")
        uid = study["study_uid"]
        if uid in seen:
            raise ValueError("duplicate study index entry")
        seen.add(uid)
        record = repository.load(uid)
        if record is None:
            continue
        mapping = study["instance_to_series"]
        if len(mapping) > 4096:
            raise ValueError("too many indexed instances")
        decisions = {series: store.load(uid, series) for series in set(mapping.values())}
        if any(d is not None and (d.study_uid != uid or d.series_uid != series) for series, d in decisions.items()):
            raise ValueError("view decision identity mismatch")
        for contour in accepted_anchors(record["data"], mapping, decisions):
            if len(examples) >= 4096:
                raise ValueError("too many weak examples")
            counts["accepted_anchor_sets"] += 1
            sector = anonymous_sector(study, contour.sop_instance_uid, contour.frame_index, args.index.parent)
            if sector is None and args.require_gradient:
                counts["missing_sector"] += 1
                continue
            anchors = np.asarray([*contour.mitral_annulus, contour.apex_landmark])
            try:
                target = reconstruct_weak_shape(
                    atlases[contour.view], contour.chamber, anchors, phase=contour.phase, image=sector
                )
            except (ValueError, KeyError, np.linalg.LinAlgError):
                counts["rejected_geometry"] += 1
                continue
            examples.append(
                {
                    "sample_index": len(examples),
                    "view": target.view,
                    "chamber": target.chamber,
                    "phase": target.phase,
                    "units": target.units,
                    "points": target.points.tolist(),
                    "node_weights": target.node_weights.tolist(),
                    "anchor_indices": list(target.anchor_indices),
                    "source": target.source,
                    "gradient_refined": target.gradient_refined,
                }
            )
    output.mkdir(parents=True)
    path = output / "weak_shapes.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "weak_shape_targets_not_image_gold",
                "clinical_validated": False,
                "examples": examples,
                "counts": counts,
            },
            allow_nan=False,
            indent=2,
        )
    )
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True, help="explicit local study/instance-to-series index")
    parser.add_argument("--measurements-dir", type=Path, required=True)
    parser.add_argument("--view-decisions-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--atlas", type=Path, action="append", default=[], help="optional local numeric ML.1 atlas (repeatable)"
    )
    parser.add_argument(
        "--require-gradient", action="store_true", help="exclude atlas-only shapes without anonymous sectors"
    )
    return parser.parse_args(argv)


def main(argv=None):
    try:
        harvest(parse_args(argv))
    except (ValueError, OSError, KeyError, TypeError, AttributeError, ImportError, MeasurementStorageError):
        sys.stderr.write("Weak-label harvest failed; check local configuration and accepted inputs.\n")
        return 2
    sys.stdout.write("Anonymous weak shape targets written; no pixels, gold or model activation.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
