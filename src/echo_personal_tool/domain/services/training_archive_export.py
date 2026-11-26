"""Offline archive split and reviewed atlas adapter; no fitting before splitting."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from echo_personal_tool.domain.services.training_archive import atlas_phase


def split_archive_records(
    records: Sequence[Mapping[str, Any]], *, seed: str = "sonoforge-local-v1"
) -> list[dict[str, Any]]:
    """Union patient, study AND identical frames before assigning a stable split.

    Even bridge records (same patient, another study/pixel) cannot leak. Missing
    patient identity is conservatively one shared group; never split by clip.
    """
    selected = sorted((dict(r) for r in records if not r.get("excluded", False)), key=lambda r: str(r["sample_id"]))
    parent = list(range(len(selected)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen: dict[tuple[str, str], int] = {}
    for i, record in enumerate(selected):
        for key in ("patient_key", "study_key", "frame_hash"):
            value = str(record.get(key) or "UNKNOWN")
            identity = (key, value)
            if identity in seen:
                parent[root(i)] = root(seen[identity])
            seen[identity] = i
    if any(not r.get("patient_identity_known", True) for r in selected):
        # A patient with missing identity could also occur in any named study.
        # Do not advertise a leakage-free holdout in that situation.
        parent = [0] * len(selected)
    groups: dict[int, list[str]] = {}
    for i, record in enumerate(selected):
        groups.setdefault(root(i), []).append(str(record["sample_id"]))
    assignments = {}
    for group, ids in groups.items():
        digest = hashlib.sha256((seed + ":" + min(ids)).encode()).hexdigest()
        bucket = int(digest[:8], 16) % 10
        assignments[group] = ("test" if bucket == 0 else "val" if bucket == 1 else "train", digest)
    output, signatures = [], set()
    for i, record in enumerate(selected):
        # Dedup only after union: duplicated frames across patients must still
        # link their other studies, even if the duplicate itself is discarded.
        signature = json.dumps(
            [record["frame_hash"], record["chamber"], record["phase_semantics"], record["points"]], sort_keys=True
        )
        if signature in signatures:
            continue
        signatures.add(signature)
        split, group_id = assignments[root(i)]
        output.append({**record, "split": split, "split_group": group_id})
    return output


def reviewed_atlas_record(record: Mapping[str, Any], reviewed: Mapping[str, int]) -> dict[str, Any]:
    """Reviewed real open arcs only; no mean filling and no held-out PCA input."""
    if record.get("split") != "train":
        raise ValueError("held_out")
    if reviewed.get(str(record["sample_id"])) != record["revision"]:
        raise ValueError("review_required_for_current_revision")
    if record["geometry_kind"] != "trace":
        raise ValueError("sparse_prior_not_strong_label")
    if record["chamber"] == "RA":
        raise ValueError("RA_archive_supported_training_adapter_not_yet_supported")
    from echo_personal_tool.domain.services.cardiac_atlas import ATLAS_VIEWS

    if record["view"] not in ATLAS_VIEWS:
        raise ValueError("unsupported_atlas_view")
    if record["mitral_annulus"] is None or record["apex_landmark"] is None:
        raise ValueError("reviewed_open_arc_and_landmarks_required")
    phase = atlas_phase(str(record["phase_semantics"]))
    annulus = record["mitral_annulus"]
    return {
        "view": record["view"],
        "phase": phase,
        "reference_chamber": record["chamber"],
        "contours": {record["chamber"]: record["points"]},
        "anchors": {"septal": annulus[0], "lateral": annulus[1], "apex": record["apex_landmark"]},
        "pixel_spacing_mm": record["pixel_spacing_mm"],
    }
