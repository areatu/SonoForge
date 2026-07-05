"""Gold annotation I/O — load/save per-study JSON matching Tier-1 schema."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _validate_frame(frame: dict[str, Any]) -> None:
    required = ("frame_index", "phase", "points")
    for key in required:
        if key not in frame:
            msg = f"gold frame missing required key: {key}"
            raise ValueError(msg)
    if frame["phase"] not in ("ED", "ES"):
        msg = f"gold frame phase must be 'ED' or 'ES', got {frame['phase']!r}"
        raise ValueError(msg)
    points = frame["points"]
    if not isinstance(points, list) or len(points) < 3:
        msg = "gold frame 'points' must be a list with at least 3 [x, y] pairs"
        raise ValueError(msg)


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


def merge_frame_into_gold(
    existing: dict[str, Any],
    frame_data: dict[str, Any],
) -> dict[str, Any]:
    """Merge a new frame into existing gold data, deduplicating by frame_index + phase."""
    _validate_frame(frame_data)
    frames: list[dict[str, Any]] = existing.get("frames", [])
    key = (frame_data["frame_index"], frame_data["phase"])
    for i, f in enumerate(frames):
        if (f.get("frame_index"), f.get("phase")) == key:
            frames[i] = frame_data
            return {**existing, "frames": frames}
    frames.append(frame_data)
    return {**existing, "frames": frames}


def make_gold_frame(
    *,
    frame_index: int,
    phase: str,
    points: list[list[float]],
    mitral_annulus: list[list[float]],
    apex_landmark: list[float] | None = None,
    source: str = "ai_corrected",
    annotator: str = "",
    view: str = "A4C",
    sop_instance_uid: str | None = None,
) -> dict[str, Any]:
    """Build a single gold frame dict ready for merge_frame_into_gold."""
    frame: dict[str, Any] = {
        "frame_index": frame_index,
        "phase": phase,
        "view": view,
        "points": points,
        "mitral_annulus": mitral_annulus,
        "source": source,
        "annotator": annotator,
        "annotated_at": datetime.now(timezone.utc).isoformat(),
    }
    if apex_landmark is not None:
        frame["apex_landmark"] = apex_landmark
    if sop_instance_uid is not None:
        frame["sop_instance_uid"] = sop_instance_uid
    return frame


def make_gold_study(
    *,
    study_id: str,
    instance_path: str,
    pixel_spacing_mm: list[float],
    sop_instance_uid: str | None = None,
    scanner_vendor: str | None = None,
) -> dict[str, Any]:
    """Build an empty gold study dict ready for frame merges."""
    data: dict[str, Any] = {
        "study_id": study_id,
        "instance_path": instance_path,
        "pixel_spacing_mm": pixel_spacing_mm,
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
