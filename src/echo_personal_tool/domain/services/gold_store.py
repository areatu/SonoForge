"""Gold annotation I/O — load/save per-study JSON matching Tier-1 schema."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_VALID_CHAMBERS = ("LV", "LA", "RA", "RV")


def _validate_frame(frame: dict[str, Any]) -> None:
    required = ("frame_index", "phase", "points")
    for key in required:
        if key not in frame:
            msg = f"gold frame missing required key: {key}"
            raise ValueError(msg)
    if frame["phase"] not in ("ED", "ES"):
        msg = f"gold frame phase must be 'ED' or 'ES', got {frame['phase']!r}"
        raise ValueError(msg)
    chamber = frame.get("chamber")
    if chamber is not None and chamber.upper() not in _VALID_CHAMBERS:
        msg = f"gold frame chamber must be one of {_VALID_CHAMBERS}, got {chamber!r}"
        raise ValueError(msg)
    points = frame["points"]
    if not isinstance(points, list) or len(points) < 3:
        msg = "gold frame 'points' must be a list with at least 3 [x, y] pairs"
        raise ValueError(msg)


def gold_filename(study_uid: str, chamber: str) -> str:
    """Return gold JSON filename with chamber prefix: ``la_<uid>.json``."""
    return f"{chamber.lower()}_{study_uid}.json"


def parse_chamber_from_gold_path(path: Path) -> str:
    """Extract chamber prefix from gold filename. Defaults to ``LV``."""
    name = path.stem
    for chamber in ("la", "lv", "ra", "rv"):
        prefix = f"{chamber}_"
        if name.startswith(prefix):
            return chamber.upper()
    return "LV"


def save_gold(path: Path, data: dict[str, Any]) -> None:
    """Save gold annotation as JSON matching Tier-1 schema (spec 1.2)."""
    for key in ("study_id", "frames"):
        if key not in data:
            msg = f"gold data missing required key: {key}"
            raise ValueError(msg)
    for frame in data.get("frames", []):
        _validate_frame(frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def try_load_gold(path: Path) -> dict[str, Any] | None:
    """Load gold JSON if the file exists and contains valid data."""
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        return load_gold(path)
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def load_gold(path: Path) -> dict[str, Any]:
    """Load and validate gold annotation from JSON."""
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    for key in ("study_id", "frames"):
        if key not in data:
            msg = f"gold file missing required key: {key}"
            raise ValueError(msg)
    for frame in data.get("frames", []):
        _validate_frame(frame)
    return data


def frame_instance_key(frame: dict[str, Any], *, study: dict[str, Any] | None = None) -> str:
    """Stable per-DICOM identity for merge/dedup within a multi-instance gold study."""
    sop_uid = frame.get("sop_instance_uid")
    if sop_uid:
        return str(sop_uid)
    instance_path = frame.get("instance_path")
    if instance_path:
        return Path(str(instance_path)).name
    if study is not None:
        top = study.get("instance_path")
        if top:
            return Path(str(top)).name
    return ""


def backfill_frame_instance_paths(study: dict[str, Any]) -> None:
    """Pin legacy frames without ``instance_path`` to the study-level path in-place."""
    top = study.get("instance_path")
    if not top:
        return
    for frame in study.get("frames", []):
        if frame.get("instance_path") or frame.get("sop_instance_uid"):
            continue
        frame["instance_path"] = top


def frame_merge_key(frame: dict[str, Any], *, study: dict[str, Any] | None = None) -> tuple[str, str]:
    """Dedup key: one ED + one ES per DICOM instance, regardless of frame_index."""
    return (frame_instance_key(frame, study=study), str(frame["phase"]).upper())


def dedupe_gold_frames(
    frames: list[dict[str, Any]],
    *,
    study: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Keep the latest frame per (instance, phase); drop global (frame_index, phase) collisions."""
    study_copy = {**(study or {}), "frames": list(frames)}
    backfill_frame_instance_paths(study_copy)
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for frame in study_copy.get("frames", []):
        _validate_frame(frame)
        key = frame_merge_key(frame, study=study_copy)
        prev = latest.get(key)
        if prev is None:
            latest[key] = frame
            continue
        prev_at = str(prev.get("annotated_at", ""))
        new_at = str(frame.get("annotated_at", ""))
        if new_at >= prev_at:
            latest[key] = frame
    return list(latest.values())


def merge_frame_into_gold(
    existing: dict[str, Any],
    frame_data: dict[str, Any],
) -> dict[str, Any]:
    """Merge a new frame, deduplicating by (instance, phase) — not global frame_index.

    Multiple DICOM cines in one study may share frame numbers; each instance keeps
    its own ED/ES pair. Re-saving the same phase on the same DICOM replaces it.

    Legacy frames without ``instance_path`` are pinned to the current study path
    before merge so a later study-level path update cannot re-key them.

    If the frame has a different instance_path than the study-level one,
    update the study-level instance_path to the most recent file.
    """
    _validate_frame(frame_data)
    existing = {**existing, "frames": list(existing.get("frames", []))}
    backfill_frame_instance_paths(existing)
    frames: list[dict[str, Any]] = existing["frames"]
    key = frame_merge_key(frame_data, study=existing)
    for i, f in enumerate(frames):
        if frame_merge_key(f, study=existing) == key:
            frames[i] = frame_data
            result = {**existing, "frames": frames}
            frame_path = frame_data.get("instance_path")
            if frame_path and frame_path != existing.get("instance_path"):
                result["instance_path"] = frame_path
            return result
    frames.append(frame_data)

    result = {**existing, "frames": frames}
    frame_path = frame_data.get("instance_path")
    if frame_path and frame_path != existing.get("instance_path"):
        result["instance_path"] = frame_path
    return result


def make_gold_frame(
    *,
    frame_index: int,
    phase: str,
    points: list[list[float]],
    mitral_annulus: list[list[float]],
    chamber: str = "LV",
    apex_landmark: list[float] | None = None,
    source: str = "ai_corrected",
    annotator: str = "",
    view: str = "A4C",
    sop_instance_uid: str | None = None,
    instance_path: str | None = None,
) -> dict[str, Any]:
    """Build a single gold frame dict ready for merge_frame_into_gold."""
    frame: dict[str, Any] = {
        "frame_index": frame_index,
        "phase": phase,
        "view": view,
        "chamber": chamber.upper(),
        "points": points,
        "mitral_annulus": mitral_annulus,
        "source": source,
        "annotator": annotator,
        "annotated_at": datetime.now(UTC).isoformat(),
    }
    if apex_landmark is not None:
        frame["apex_landmark"] = apex_landmark
    if sop_instance_uid is not None:
        frame["sop_instance_uid"] = sop_instance_uid
    if instance_path is not None:
        frame["instance_path"] = instance_path
    return frame


def make_gold_study(
    *,
    study_id: str,
    instance_path: str,
    pixel_spacing_mm: list[float],
    chamber: str = "LV",
    sop_instance_uid: str | None = None,
    scanner_vendor: str | None = None,
) -> dict[str, Any]:
    """Build an empty gold study dict ready for frame merges."""
    data: dict[str, Any] = {
        "study_id": study_id,
        "instance_path": instance_path,
        "pixel_spacing_mm": pixel_spacing_mm,
        "chamber": chamber.upper(),
        "frames": [],
    }
    if sop_instance_uid is not None:
        data["sop_instance_uid"] = sop_instance_uid
    optional: dict[str, Any] = {}
    if scanner_vendor is not None:
        optional["scanner_vendor"] = scanner_vendor
    if optional:
        data["optional"] = optional
    return data


def rebuild_manifest_from_gold_dir(gold_root: Path) -> dict[str, Any]:
    """Rebuild ``manifest.json`` from all ``gold/*_{study_uid}.json`` files."""
    gold_dir = gold_root / "gold"
    manifest: dict[str, Any] = {"studies": []}
    if not gold_dir.is_dir():
        manifest_path = gold_root / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return manifest

    by_study: dict[str, dict[str, Any]] = {}
    for path in sorted(gold_dir.glob("*.json")):
        gold = try_load_gold(path)
        if gold is None:
            continue
        study_id = str(gold.get("study_id", ""))
        if not study_id:
            continue
        chamber = str(gold.get("chamber") or parse_chamber_from_gold_path(path)).upper()
        if study_id not in by_study:
            by_study[study_id] = {
                "study_id": study_id,
                "instance_path": gold.get("instance_path", ""),
                "tags": {},
            }
        entry = by_study[study_id]
        if gold.get("instance_path"):
            entry["instance_path"] = gold["instance_path"]
        for frame in gold.get("frames", []):
            phase = frame.get("phase")
            frame_index = frame.get("frame_index")
            if frame_index is None:
                continue
            if phase == "ED" and chamber == "LV":
                entry["ed_frame"] = frame_index
            elif phase == "ES":
                if chamber == "LV":
                    entry["es_frame"] = frame_index
                elif "es_frame" not in entry:
                    entry["es_frame"] = frame_index

    manifest["studies"] = sorted(by_study.values(), key=lambda s: s.get("study_id", ""))
    manifest_path = gold_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def remove_gold_frame(
    gold_path: Path,
    *,
    frame_index: int,
    phase: str,
    instance_path: str | None = None,
    sop_instance_uid: str | None = None,
) -> bool:
    """Remove one annotated frame from a gold file.

    When ``instance_path`` or ``sop_instance_uid`` is given, only that DICOM's
    frame is removed (required for multi-instance LV gold files).

    If ``frames`` becomes empty, deletes the gold file.
    Returns True when a matching frame was removed.
    """
    gold = try_load_gold(gold_path)
    if gold is None:
        return False
    phase = phase.upper()
    frames = gold.get("frames", [])
    target_identity: str | None = None
    if sop_instance_uid:
        target_identity = sop_instance_uid
    elif instance_path:
        target_identity = Path(instance_path).name

    def _matches(frame: dict[str, Any]) -> bool:
        if frame.get("frame_index") != frame_index or frame.get("phase") != phase:
            return False
        if target_identity is None:
            return True
        return frame_instance_key(frame, study=gold) == target_identity

    kept = [frame for frame in frames if not _matches(frame)]
    if len(kept) == len(frames):
        return False
    if not kept:
        gold_path.unlink(missing_ok=True)
        return True
    gold["frames"] = kept
    save_gold(gold_path, gold)
    return True


def audit_gold_instance_completeness(
    gold: dict[str, Any],
    *,
    phases: tuple[str, ...] = ("ED", "ES"),
) -> dict[str, Any]:
    """Per-DICOM ED/ES coverage report for a gold study dict."""
    by_instance: dict[str, dict[str, Any]] = {}
    for frame in gold.get("frames", []):
        inst = frame_instance_key(frame, study=gold)
        if not inst:
            inst = "<unknown>"
        entry = by_instance.setdefault(inst, {"instance": inst, "phases": {}})
        entry["phases"][str(frame.get("phase")).upper()] = {
            "frame_index": frame.get("frame_index"),
            "annotated_at": frame.get("annotated_at"),
            "instance_path": frame.get("instance_path"),
        }

    complete: list[str] = []
    incomplete: list[dict[str, Any]] = []
    for inst, entry in sorted(by_instance.items()):
        have = set(entry["phases"])
        missing = [p for p in phases if p not in have]
        if missing:
            incomplete.append({"instance": inst, "missing": missing, "have": entry["phases"]})
        else:
            complete.append(inst)

    return {
        "total_instances": len(by_instance),
        "complete": complete,
        "incomplete": incomplete,
        "complete_count": len(complete),
        "incomplete_count": len(incomplete),
    }


def repair_gold_from_backup(
    current: dict[str, Any],
    backup: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Merge frames from *backup* into *current* using per-instance phase keys.

    Returns ``(repaired_gold, recovered_frames)`` where *recovered_frames* lists
    frames present in backup but absent from current for the same (instance, phase).
    """
    current_keys = {frame_merge_key(frame, study=current) for frame in current.get("frames", [])}
    recovered: list[dict[str, Any]] = []
    merged = {**current, "frames": list(current.get("frames", []))}
    for frame in backup.get("frames", []):
        key = frame_merge_key(frame, study=backup)
        if key in current_keys:
            continue
        merged = merge_frame_into_gold(merged, frame)
        current_keys.add(key)
        recovered.append(frame)
    merged["frames"] = dedupe_gold_frames(merged.get("frames", []), study=merged)
    return merged, recovered
