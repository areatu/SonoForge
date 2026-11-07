"""Bounded teaching sidecars and in-memory edits; never measurement or AI input.

A prepared JSON sidecar binds to one local clip by SHA-256 and image size.
Only explicit, zero-based frames are rendered. No patient text is accepted.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STRUCTURES = ("lv", "la", "rv", "ra", "lv_wall", "aorta")
VIEWS = ("A4C", "A2C", "A3C", "PLAX", "PSAX", "SUBCOSTAL")
POSITIONS = ("left_lateral", "supine", "subcostal", "other")
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_MEDIA_BYTES = 1024 * 1024 * 1024


class AnnotationError(ValueError):
    """Sidecar cannot be safely rendered on the currently open clip."""


@dataclass(frozen=True)
class Shape:
    structure: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Annotation:
    source_sha256: str
    width: int
    height: int
    view: str
    position: str
    frames: dict[int, tuple[Shape, ...]]


def parse_annotation(raw: Any) -> Annotation:
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "source_sha256",
        "width",
        "height",
        "view",
        "position",
        "frames",
    }:
        raise AnnotationError("Invalid teaching manifest fields")
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise AnnotationError("Unsupported teaching manifest version")
    digest = raw["source_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise AnnotationError("Invalid source digest")
    width, height = raw["width"], raw["height"]
    if any(type(n) is not int or not 16 <= n <= 8192 for n in (width, height)):
        raise AnnotationError("Invalid image dimensions")
    view, position = raw["view"], raw["position"]
    if not isinstance(view, str) or view not in VIEWS or not isinstance(position, str) or position not in POSITIONS:
        raise AnnotationError("Unknown view or position")
    frames = raw["frames"]
    if not isinstance(frames, dict) or len(frames) > 2000:
        raise AnnotationError("Invalid frames")
    parsed: dict[int, tuple[Shape, ...]] = {}
    for index, shapes in frames.items():
        if (
            not isinstance(index, str)
            or not 1 <= len(index) <= 7
            or not index.isascii()
            or not index.isdecimal()
            or index != str(int(index))
        ):
            raise AnnotationError("Invalid frame index")
        if int(index) > 1_000_000 or not isinstance(shapes, list) or len(shapes) > len(STRUCTURES):
            raise AnnotationError("Invalid frame content")
        seen: set[str] = set()
        result: list[Shape] = []
        for entry in shapes:
            if not isinstance(entry, dict) or set(entry) != {"id", "points"}:
                raise AnnotationError("Invalid structure")
            name, vertices = entry["id"], entry["points"]
            if not isinstance(name, str) or name not in STRUCTURES or name in seen:
                raise AnnotationError("Unknown or repeated structure")
            seen.add(name)
            if not isinstance(vertices, list) or not 3 <= len(vertices) <= 512:
                raise AnnotationError("Invalid polygon")
            coords: list[tuple[float, float]] = []
            for point in vertices:
                if (
                    not isinstance(point, list)
                    or len(point) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in point)
                ):
                    raise AnnotationError("Coordinates must be normalized and finite")
                coords.append((float(point[0]), float(point[1])))
            result.append(Shape(name, tuple(coords)))
        parsed[int(index)] = tuple(result)
    return Annotation(digest, width, height, view, position, parsed)


def load_annotation(path: Path) -> Annotation:
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_JSON_BYTES + 1)
        if len(payload) > MAX_JSON_BYTES:
            raise AnnotationError("Annotation too large")
        return parse_annotation(json.loads(payload.decode("utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnnotationError("Cannot read annotation") from exc


def fingerprint_source(source: Path) -> tuple[str, tuple[int, int, int, int, int]]:
    """Hash the actual clip bytes, not pixels (one-time operation)."""
    try:
        before = source.stat()
        if before.st_size > MAX_MEDIA_BYTES or not source.is_file():
            raise AnnotationError("Source missing or too large")
        digest = hashlib.sha256()
        total = 0
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                total += len(block)
                if total > MAX_MEDIA_BYTES:
                    raise AnnotationError("Source too large")
                digest.update(block)
        after = source.stat()
    except OSError as exc:
        raise AnnotationError("Cannot read source") from exc
    identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    if before_identity != identity or total != after.st_size:
        raise AnnotationError("Source changed while hashing")
    return digest.hexdigest(), identity


def bind_to_source(
    annotation: Annotation, source: Path, image_size: tuple[int, int] | None
) -> tuple[int, int, int, int, int]:
    """Check the selected file once, on explicit load (not during playback)."""
    if image_size != (annotation.height, annotation.width):
        raise AnnotationError("Image size mismatch")
    digest, identity = fingerprint_source(source)
    if digest != annotation.source_sha256:
        raise AnnotationError("Source content does not match annotation")
    return identity


def create_annotation(
    source: Path, image_size: tuple[int, int], view: str, position: str
) -> tuple[Annotation, tuple[int, int, int, int, int]]:
    height, width = image_size
    digest, identity = fingerprint_source(source)
    annotation = parse_annotation(
        {
            "version": 1,
            "source_sha256": digest,
            "width": width,
            "height": height,
            "view": view,
            "position": position,
            "frames": {},
        }
    )
    return annotation, identity


def replace_shape(annotation: Annotation, frame: int, shape: Shape | None, structure: str) -> Annotation:
    """Replace just one structure of one explicit frame; no measured-contour DTOs."""
    if frame < 0 or frame > 1_000_000 or structure not in STRUCTURES:
        raise AnnotationError("Invalid teaching frame or structure")
    frames = dict(annotation.frames)
    shapes = [entry for entry in frames.get(frame, ()) if entry.structure != structure]
    if shape is not None:
        if shape.structure != structure:
            raise AnnotationError("Structure mismatch")
        shapes.append(shape)
    if shapes:
        frames[frame] = tuple(shapes)
    else:
        frames.pop(frame, None)
    result = Annotation(
        annotation.source_sha256, annotation.width, annotation.height, annotation.view, annotation.position, frames
    )
    parse_annotation(annotation_to_dict(result))  # same rules as imported sidecars
    return result


def annotation_to_dict(annotation: Annotation) -> dict:
    return {
        "version": 1,
        "source_sha256": annotation.source_sha256,
        "width": annotation.width,
        "height": annotation.height,
        "view": annotation.view,
        "position": annotation.position,
        "frames": {
            str(frame): [{"id": shape.structure, "points": [list(point) for point in shape.points]} for shape in shapes]
            for frame, shapes in sorted(annotation.frames.items())
        },
    }


def save_annotation(annotation: Annotation, path: Path) -> None:
    """Explicit atomic export only; never write into the study or session."""
    data = annotation_to_dict(annotation)
    parse_annotation(data)
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_JSON_BYTES:
        raise AnnotationError("Annotation too large")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=".teaching-", suffix=".tmp", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise AnnotationError("Cannot save annotation") from exc
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
