"""Atomic per-study storage for key images (#561).

The file carries references only: study/SOP/series UIDs, a frame index, an
optional measurement id and a stat-based file identity.  It deliberately has
no filesystem paths, patient fields or pixels, so the small record can live
next to the measurement documents without widening their privacy surface.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from echo_personal_tool.domain.models.key_image import KeyImage
from echo_personal_tool.infrastructure.measurement_codec import study_key
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository

FORMAT = "sonoforge.key-images"
VERSION = 1
MAX_IMAGES = 500
MAX_BYTES = 2 * 1024 * 1024
_ID = re.compile(r"^[0-9a-f]{32}$")

_KEYS = {
    "bookmark_id",
    "sop_instance_uid",
    "series_uid",
    "frame_index",
    "frame_count",
    "measurement_id",
    "source_size",
    "source_mtime_ns",
    "created_at",
}
_DOCUMENT_KEYS = {"format", "version", "study_uid", "images"}


class KeyImageStorageError(ValueError):
    """A key-image record is unreadable, unsafe or outside the schema."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _text(value: object, *, limit: int = 256) -> bool:
    return isinstance(value, str) and len(value) <= limit and "\x00" not in value


def _integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _decode_image(payload: object) -> KeyImage:
    if not isinstance(payload, dict) or set(payload) != _KEYS:
        raise KeyImageStorageError("schema")
    if not _text(payload["bookmark_id"], limit=64) or not _ID.fullmatch(payload["bookmark_id"]):
        raise KeyImageStorageError("identity")
    if not _text(payload["sop_instance_uid"]) or not _text(payload["series_uid"]):
        raise KeyImageStorageError("identity")
    if not _text(payload["measurement_id"], limit=128) or not _text(payload["created_at"], limit=40):
        raise KeyImageStorageError("schema")
    if not all(_integer(payload[name]) for name in ("frame_index", "frame_count", "source_size", "source_mtime_ns")):
        raise KeyImageStorageError("schema")
    frame_count = payload["frame_count"]
    frame_index = payload["frame_index"]
    if frame_count < 1 or frame_count > 1_000_000 or frame_index >= frame_count:
        raise KeyImageStorageError("range")
    return KeyImage(
        bookmark_id=payload["bookmark_id"],
        sop_instance_uid=payload["sop_instance_uid"],
        series_uid=payload["series_uid"],
        frame_index=frame_index,
        frame_count=frame_count,
        measurement_id=payload["measurement_id"],
        source_size=payload["source_size"],
        source_mtime_ns=payload["source_mtime_ns"],
        created_at=payload["created_at"],
    )


def _encode_image(image: KeyImage) -> dict[str, Any]:
    payload = {
        "bookmark_id": image.bookmark_id,
        "sop_instance_uid": image.sop_instance_uid,
        "series_uid": image.series_uid,
        "frame_index": image.frame_index,
        "frame_count": image.frame_count,
        "measurement_id": image.measurement_id,
        "source_size": image.source_size,
        "source_mtime_ns": image.source_mtime_ns,
        "created_at": image.created_at,
    }
    _decode_image(payload)  # the writer is held to the same schema as the reader
    return payload


class KeyImageRepository:
    """Read and atomically replace one study's key-image file."""

    def __init__(self, root: Path, max_bytes: int = MAX_BYTES) -> None:
        self.root = Path(root)
        self.max_bytes = max_bytes

    def _path(self, study_uid: str) -> Path:
        if self.root.is_symlink():
            raise KeyImageStorageError("unsafe_path")
        path = self.root / (study_key(study_uid) + ".json")
        if path.is_symlink():
            raise KeyImageStorageError("unsafe_path")
        return path

    def load(self, study_uid: str) -> tuple[KeyImage, ...]:
        path = self._path(study_uid)
        try:
            with path.open("rb") as file:
                raw = file.read(self.max_bytes + 1)
        except FileNotFoundError:
            return ()
        if len(raw) > self.max_bytes:
            raise KeyImageStorageError("limit")
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KeyImageStorageError("invalid") from exc
        if not isinstance(record, dict) or set(record) != _DOCUMENT_KEYS:
            raise KeyImageStorageError("schema")
        if record["format"] != FORMAT or record["version"] != VERSION:
            raise KeyImageStorageError("version")
        if record["study_uid"] != study_uid:
            raise KeyImageStorageError("identity")
        images = record["images"]
        if not isinstance(images, list) or len(images) > MAX_IMAGES:
            raise KeyImageStorageError("limit")
        return tuple(_decode_image(item) for item in images)

    def save(self, study_uid: str, images: tuple[KeyImage, ...]) -> None:
        if len(images) > MAX_IMAGES:
            raise KeyImageStorageError("limit")
        record = {
            "format": FORMAT,
            "version": VERSION,
            "study_uid": study_uid,
            "images": [_encode_image(image) for image in images],
        }
        payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(payload) > self.max_bytes:
            raise KeyImageStorageError("limit")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._path(study_uid)
        if path.is_symlink():
            raise KeyImageStorageError("unsafe_path")
        MeasurementRepository.atomic_write(path, payload)
