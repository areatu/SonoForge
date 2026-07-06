"""Gold annotation I/O — load/save per-study JSON matching Tier-1 schema."""

from __future__ import annotations

import json
from datetime import datetime, timezone
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
    """Merge a new frame into existing gold data, deduplicating by frame_index + phase.

    If the frame has a different instance_path than the study-level one,
    update the study-level instance_path to the most recent file.
    """
    _validate_frame(frame_data)
    frames: list[dict[str, Any]] = existing.get("frames", [])
    key = (frame_data["frame_index"], frame_data["phase"])
    for i, f in enumerate(frames):
        if (f.get("frame_index"), f.get("phase")) == key:
            frames[i] = frame_data
            return {**existing, "frames": frames}
    frames.append(frame_data)

    # Update top-level instance_path if frame comes from a different file
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
        "annotated_at": datetime.now(timezone.utc).isoformat(),
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
