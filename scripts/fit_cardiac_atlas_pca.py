#!/usr/bin/env python3
"""Fit a numeric cardiac atlas from explicitly supplied local annotations (#689).

Accepts gold files (reviewed open arcs), or an atlas_samples JSON containing
phase-labelled canonical meshes/local contours. Teaching sidecars are NEVER
scanned automatically: --teaching-manifest is an explicit offline opt-in with
reviewed phases and landmark/arc correspondences, separate from the app UI.
No DICOM/media is read, no network is used, no identifiers enter the artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from echo_personal_tool.domain.services.cardiac_atlas import (  # noqa: E402
    ATLAS_VIEWS,
    CoupledShapeModel,
    build_cardiac_atlas,
)
from echo_personal_tool.domain.services.cardiac_atlas_geometry import points_array  # noqa: E402
from echo_personal_tool.domain.services.cardiac_atlas_pca import (  # noqa: E402
    AtlasObservation,
    align_local_contours,
    fit_atlas_pca,
)

MAX_JSON_BYTES = 8 * 1024 * 1024


def read_json(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("annotation exceeds 8 MiB")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("annotation root must be an object")
    return data


def observation_from_record(model: CoupledShapeModel, record: dict[str, Any]) -> AtlasObservation:
    phase = str(record.get("phase", "")).upper()
    if phase not in {"ED", "ES"}:
        raise ValueError("explicit ED/ES phase is required")
    if "canonical_points_mm" in record:
        # null denotes an unobserved node, not a zero-valued coordinate.
        arr = np.asarray(record["canonical_points_mm"], dtype=np.float64)
        return AtlasObservation(phase, arr)
    anchors = record["anchors"]
    spacing = record.get("pixel_spacing_mm")
    return align_local_contours(
        model,
        record["contours"],
        reference_chamber=str(record.get("reference_chamber", "LV")).upper(),
        septal=tuple(anchors["septal"]),
        lateral=tuple(anchors["lateral"]),
        apex=tuple(anchors["apex"]),
        phase=phase,
        pixel_spacing_mm=tuple(spacing) if spacing is not None else None,
    )


def gold_records(data: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    """Adapt existing gold_store open arcs; never infer phase or chamber from pixels."""
    chamber_default = path.stem.split("_", 1)[0].upper()
    records = []
    for frame in data.get("frames", []):
        chamber = str(frame.get("chamber", data.get("chamber", chamber_default))).upper()
        points = points_array(frame["points"])
        annulus = frame.get("mitral_annulus")
        if annulus is None:
            raise ValueError("gold training requires reviewed mitral_annulus anchors")
        apex = frame.get("apex_landmark")
        if apex is None:
            raise ValueError("gold training requires a reviewed apex_landmark")
        records.append(
            {
                "view": frame.get("view", data.get("view", "")),
                "phase": frame.get("phase", ""),
                "contours": {chamber: points.tolist()},
                "reference_chamber": chamber,
                "anchors": {"septal": annulus[0], "lateral": annulus[1], "apex": apex},
                "pixel_spacing_mm": frame.get("pixel_spacing_mm", data.get("pixel_spacing_mm")),
            }
        )
    return records


def teaching_records(manifest_path: Path) -> list[dict[str, Any]]:
    """Explicit, reviewed teaching export only; original sidecars remain untouched.

    Each manifest entry names a sidecar/frame, ED/ES, reference chamber, anchors
    in pixels and per-structure node_order (indices selecting the reviewed open
    arc, dropping the basal chord). This avoids guessing from arbitrary closed
    teaching polygons, which have no cardiac phase or anatomical node order.
    """
    output: list[dict[str, Any]] = []
    for entry in read_json(manifest_path).get("teaching_samples", []):
        path = manifest_path.parent / entry["path"]
        data = read_json(path)
        if data.get("version") != 1 or not isinstance(data.get("frames"), dict):
            raise ValueError("unsupported prepared_anatomy sidecar")
        width, height = int(data["width"]), int(data["height"])
        if not 16 <= min(width, height) <= max(width, height) <= 8192:
            raise ValueError("invalid teaching image dimensions")
        shapes = data["frames"][str(entry["frame_index"])]
        order_map = entry["node_order"]
        contours: dict[str, Any] = {}
        for shape in shapes:
            key = str(shape["id"]).upper()
            if key not in order_map:
                continue
            points = points_array(shape["points"])
            if np.any((points < 0) | (points > 1)):
                raise ValueError("teaching coordinates must be normalized")
            indices = order_map[key]
            if not isinstance(indices, list) or any(type(i) is not int or i < 0 or i >= len(points) for i in indices):
                raise ValueError("invalid reviewed teaching node order")
            contours[key] = (points[indices] * [width - 1, height - 1]).tolist()
        if not contours:
            raise ValueError("no explicitly reviewed teaching structures")
        output.append(
            {
                "view": data["view"],
                "phase": entry["phase"],
                "reference_chamber": entry["reference_chamber"],
                "anchors": entry["anchors"],
                "contours": contours,
                "pixel_spacing_mm": entry.get("pixel_spacing_mm"),
            }
        )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, action="append", default=[], help="Explicit local gold/atlas_samples JSON"
    )
    parser.add_argument("--teaching-manifest", type=Path, help="Explicit opt-in to reviewed teaching exports")
    parser.add_argument("--view", choices=ATLAS_VIEWS, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="External working directory; no raw annotations copied"
    )
    parser.add_argument("--max-modes", type=int, default=8)
    args = parser.parse_args(argv)
    model = build_cardiac_atlas(args.view)
    try:
        protected = [path.resolve() for path in args.input]
        if args.teaching_manifest is not None:
            protected.append(args.teaching_manifest.resolve())
            review = read_json(args.teaching_manifest)
            protected.extend(
                (args.teaching_manifest.parent / entry["path"]).resolve()
                for entry in review.get("teaching_samples", [])
            )
        if args.output.resolve() in protected:
            raise ValueError("output must not overwrite source annotations")
        records: list[dict[str, Any]] = []
        for path in sorted(set(args.input)):
            data = read_json(path)
            if isinstance(data.get("frames"), dict):
                raise ValueError("teaching sidecars require --teaching-manifest with reviewed correspondences")
            records.extend(data["atlas_samples"] if "atlas_samples" in data else gold_records(data, path))
        if args.teaching_manifest is not None:
            records.extend(teaching_records(args.teaching_manifest))
        selected = [r for r in records if str(r.get("view", "")).upper() == args.view]
        observations = [observation_from_record(model, record) for record in selected]
        fitted = fit_atlas_pca(model, observations, max_modes=args.max_modes)
        result = fitted.to_dict()
        result["training_summary"] = {
            "observations": len(observations),
            "ed": sum(s.phase == "ED" for s in observations),
            "es": sum(s.phase == "ES" for s in observations),
            "calibrated_or_canonical": sum(
                "canonical_points_mm" in r or r.get("pixel_spacing_mm") is not None for r in selected
            ),
            "teaching_opt_in": args.teaching_manifest is not None,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        # Do not echo patient-containing input records/exception values to CI logs.
        sys.stderr.write(f"atlas fitting failed ({type(exc).__name__}); verify local annotation contracts\n")
        return 2
    print(f"Atlas fitted: {len(observations)} observations, {len(fitted.eigenvalues)} modes")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
