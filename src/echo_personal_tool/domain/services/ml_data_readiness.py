"""Evidence inventory, not a claim of sample-size sufficiency or clinical safety."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from echo_personal_tool.domain.services.training_archive_export import reviewed_atlas_record, split_archive_records


def record_fingerprint(record: Mapping[str, Any]) -> str:
    # Origin IDs and source paths are inventory context, not annotation content.
    body = {k: v for k, v in record.items() if k not in {"origins", "namespace", "fingerprint"}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()


def combine_sources(sources: Sequence[tuple[str, str, Sequence[Mapping[str, Any]]]]) -> dict[str, Any]:
    """No cross-PC last-write-wins. Tombstones participate in conflict detection."""
    by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
    seen: dict[tuple[str, str], str] = {}
    conflicts: set[str] = set()
    namespaces: set[str] = set()
    for namespace, origin, records in sources:
        if records:
            namespaces.add(namespace)
        for item in records:
            record = dict(item)
            identity = (namespace, str(record["sample_id"]))
            fingerprint = record_fingerprint(record)
            if identity in seen and seen[identity] != fingerprint:
                conflicts.add(str(record["sample_id"]))
            seen[identity] = fingerprint
            variant = (*identity, fingerprint)
            previous = by_identity.get(variant)
            if previous is not None:
                previous["origins"].append(origin)
                continue
            # Keep BOTH variants inspectable; never hide one behind a newer
            # local revision or a curation decision on the other computer.
            by_identity[variant] = {**record, "namespace": namespace, "origins": [origin], "fingerprint": fingerprint}
    return {
        "records": sorted(by_identity.values(), key=lambda r: (r["namespace"], r["sample_id"])),
        "conflicts": sorted(conflicts),
        "namespaces": sorted(namespaces),
    }


def data_readiness(
    inventory: Mapping[str, Any], decisions: Mapping[str, Any], *, seed: str = "sonoforge-local-v1"
) -> dict[str, Any]:
    """Count evidence by stratum; every release stays blocked without evaluation.

    Reviewed is an explicit corpus-curation decision for a content+revision
    fingerprint, not a second confirmation during ordinary clinical measurement.
    """
    records = inventory["records"]
    selected = [
        r for r in records if not r["excluded"] and not decisions.get(r["fingerprint"], {}).get("excluded", False)
    ]
    blockers = []
    if not selected:
        blockers.append("empty_corpus")
    if len(inventory["namespaces"]) > 1:
        blockers.append("cross_namespace_patient_linkage_unverified")
    if inventory["conflicts"]:
        blockers.append("conflicting_cross_device_revisions")
    if any(not r.get("patient_identity_known", False) for r in selected):
        blockers.append("patient_identity_unknown")
    # A split preview is NOT a frozen corpus and cannot override these blockers.
    split = split_archive_records(selected, seed=seed)
    split_counts = Counter(r["split"] for r in split)
    if any(split_counts[s] == 0 for s in ("train", "val", "test")):
        blockers.append("independent_train_val_test_missing")
    reasons: Counter[str] = Counter()
    strata: Counter[tuple[str, ...]] = Counter()
    patients: dict[tuple[str, ...], set[str]] = {}
    reviewed_strata: Counter[tuple[str, ...]] = Counter()
    reviewed_count = 0
    for record in split:
        reviewed = decisions.get(record["fingerprint"], {}).get("reviewed", False) is True
        reviewed_count += int(reviewed)
        key = tuple(str(record[k]) for k in ("chamber", "view", "phase_semantics", "origin", "geometry_kind", "split"))
        strata[key] += 1
        reviewed_strata[key] += int(reviewed)
        if record.get("patient_identity_known", False):
            patients.setdefault(key, set()).add(record["patient_key"])
        try:
            reviewed_atlas_record(record, {record["sample_id"]: record["revision"]} if reviewed else {})
        except ValueError as exc:
            reasons[str(exc)] += 1
        else:
            reasons["reviewed_train_adapter_eligible"] += 1
    if reasons["reviewed_train_adapter_eligible"] == 0:
        blockers.append("no_reviewed_train_shapes_supported_by_adapter")
    return {
        "schema_version": 1,
        "clinical_validated": False,
        "release_status": "BLOCKED_NO_INDEPENDENT_CLINICAL_EVALUATION",
        "split_preview_only": True,
        "split_seed": seed,
        "collection_records": len(records),
        "identity_namespaces": len(inventory["namespaces"]),
        "conflicting_measurements": len(inventory["conflicts"]),
        "selected_records": len(selected),
        "deduplicated_split_records": len(split),
        "unique_frames": len({r["frame_hash"] for r in selected}),
        "patient_groups": len({r["patient_key"] for r in selected if r.get("patient_identity_known", False)}),
        "reviewed_current_records": reviewed_count,
        "split_counts": dict(split_counts),
        "independent_split_groups": {
            name: len({r["split_group"] for r in split if r["split"] == name}) for name in ("train", "val", "test")
        },
        "preparation_blockers": blockers,
        "atlas_adapter_status": dict(reasons),
        "strata": [
            {
                **dict(zip(("chamber", "view", "phase", "origin", "geometry_kind", "split", "count"), (*key, count))),
                "unique_known_patients": len(patients.get(key, set())),
                "reviewed_current": reviewed_strata[key],
            }
            for key, count in sorted(strata.items())
        ],
    }
