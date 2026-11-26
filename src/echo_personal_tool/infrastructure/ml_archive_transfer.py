"""Checked directory snapshots for removable media. No ZIP extraction or network.

Identity keys are sensitive pseudonymisation material, not anonymisation. Each
writable archive has its OWN origin; only the identity salt is shared across PCs.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np

from echo_personal_tool.infrastructure.local_ml_storage import atomic_json, external_path
from echo_personal_tool.infrastructure.training_archive import SqliteMeasurementArchive

MAX_SNAPSHOT_BYTES = 64 * 1024**3
HEX_ID = re.compile(r"[0-9a-f]{64}")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_identity(archive: SqliteMeasurementArchive) -> str:
    with archive._connection() as db:
        salt = db.execute("SELECT value FROM settings WHERE key='salt'").fetchone()[0]
    if not isinstance(salt, bytes) or len(salt) != 32:
        raise ValueError("invalid_identity_key")
    return hashlib.sha256(salt).hexdigest()


def export_identity(archive: SqliteMeasurementArchive, output: Path) -> None:
    output = external_path(output)
    if output.exists():
        raise ValueError("new_destination_required")
    with archive._connection() as db:
        salt = db.execute("SELECT value FROM settings WHERE key='salt'").fetchone()[0]
    atomic_json(output, {"format": "sonoforge-local-identity-v1", "salt": salt.hex()})


def initialize_identity(archive: SqliteMeasurementArchive, source: Path) -> None:
    """Only before collection. Never relabel existing records with a different key."""
    source = external_path(source)
    if source.stat().st_size > 4096:
        raise ValueError("invalid_identity_key")
    data = json.loads(source.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("format") != "sonoforge-local-identity-v1"
        or HEX_ID.fullmatch(str(data.get("salt"))) is None
    ):
        raise ValueError("invalid_identity_key")
    with archive._connection() as db:
        if (
            db.execute("SELECT 1 FROM samples LIMIT 1").fetchone()
            or db.execute("SELECT 1 FROM settings WHERE key='export_sequence'").fetchone()
        ):
            raise ValueError("identity_requires_empty_unexported_archive")
        db.execute("UPDATE settings SET value=? WHERE key='salt'", (bytes.fromhex(data["salt"]),))


def _snapshot(archive: SqliteMeasurementArchive, target: Path) -> dict[str, Any]:
    # Reserve export order while blocking clinical writes, but never copy a live
    # SQLite file with shutil (journal/WAL may contain the most recent records).
    with archive._connection() as db:
        db.commit()  # schema/salt initialization precedes the explicit snapshot transaction
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT OR IGNORE INTO settings VALUES('origin', ?)", (uuid.uuid4().hex,))
        origin = db.execute("SELECT value FROM settings WHERE key='origin'").fetchone()[0]
        row = db.execute("SELECT value FROM settings WHERE key='export_sequence'").fetchone()
        sequence = int(row[0]) + 1 if row else 1
        db.execute("INSERT OR REPLACE INTO settings VALUES('export_sequence', ?)", (str(sequence),))
        # Backup reader sees committed clinical data; uncommitted bookkeeping is
        # intentionally copied into the destination separately below.
        with closing(sqlite3.connect(archive.path.resolve().as_uri() + "?mode=ro", uri=True)) as reader:
            with closing(sqlite3.connect(target)) as destination:
                reader.backup(destination)
                destination.execute("INSERT OR REPLACE INTO settings VALUES('origin', ?)", (origin,))
                destination.execute("INSERT OR REPLACE INTO settings VALUES('export_sequence', ?)", (str(sequence),))
                destination.commit()
    target.chmod(0o600)
    return {"origin": origin, "sequence": sequence}


def export_snapshot(archive: SqliteMeasurementArchive, output: Path) -> dict[str, Any]:
    output = external_path(output)
    if output.exists() or archive.read_only:
        raise ValueError("new_destination_and_writable_origin_required")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    estimate = archive.path.stat().st_size if archive.path.exists() else 1024**2
    if estimate > MAX_SNAPSHOT_BYTES or shutil.disk_usage(output.parent).free < estimate + 1024**2:
        raise ValueError("insufficient_transfer_disk_space")
    with tempfile.TemporaryDirectory(prefix=".ml-transfer-", dir=output.parent) as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir(mode=0o700)
        target = stage / "archive.sqlite3"
        history = _snapshot(archive, target)
        if target.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise ValueError("oversized_transfer")
        manifest = {
            "format": "sonoforge-local-archive-v1",
            "privacy": "LOCAL_NOT_ANONYMISED",
            **history,
            "namespace": archive_identity(SqliteMeasurementArchive(target, read_only=True)),
            "bytes": target.stat().st_size,
            "sha256": file_digest(target),
        }
        atomic_json(stage / "transfer.json", manifest)
        verify_snapshot(stage)
        stage.rename(output)
    return manifest


def _verify_frame_blob(digest: str, payload: bytes) -> tuple[int, ...]:
    if HEX_ID.fullmatch(digest) is None or hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("frame_hash_mismatch")
    stream = io.BytesIO(payload)
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
    elif version == (2, 0):
        shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
    else:
        raise ValueError("unsupported_frame_format")
    if (
        len(shape) not in {2, 3}
        or dtype.kind not in "uif"
        or dtype.itemsize > 8
        or min(shape[:2]) < 2
        or max(shape[:2]) > 8192
        or (len(shape) == 3 and shape[2] not in {1, 3, 4})
    ):
        raise ValueError("invalid_frame_shape")
    expected = int(np.prod(shape)) * dtype.itemsize
    if expected > 128 * 1024**2 or stream.tell() + expected != len(payload):
        raise ValueError("invalid_frame_size")
    stream.seek(0)
    if not np.isfinite(np.load(stream, allow_pickle=False)).all():
        raise ValueError("nonfinite_frame")
    return tuple(int(value) for value in shape)


def _verify_annotation(record: dict[str, Any], shape: tuple[int, ...]) -> None:
    from echo_personal_tool.domain.services.training_archive import CHAMBERS, phase_semantics

    for key in ("sample_id", "patient_key", "study_key", "series_key", "instance_key", "measurement_key"):
        if HEX_ID.fullmatch(str(record.get(key))) is None:
            raise ValueError("invalid_annotation_identity")
    if (
        record.get("chamber") not in CHAMBERS
        or record.get("origin") not in {"MANUAL", "AUTO_EDITED", "AUTO_ACCEPTED"}
        or record.get("source") not in {"manual", "model", "ai", "ai_edited", "ste_auto"}
        or record.get("geometry_kind") not in {"trace", "landmark_prior"}
        or type(record.get("patient_identity_known")) is not bool
        or record.get("partial_annotation") is not True
        or record.get("frame_shape") != list(shape)
        or not {"mitral_annulus", "apex_landmark"}.issubset(record)
        or type(record.get("frame_index")) is not int
        or record["frame_index"] < 0
        or not isinstance(record.get("view"), str)
        or len(record["view"]) > 128
        or not isinstance(record.get("phase"), str)
        or record.get("phase_semantics") != phase_semantics(record["chamber"], record["phase"])
    ):
        raise ValueError("invalid_annotation_contract")
    points = np.asarray(record.get("points"), dtype=float)
    if (
        points.ndim != 2
        or points.shape[1] != 2
        or not 3 <= len(points) <= 10000
        or not np.isfinite(points).all()
        or np.any(points < 0)
        or np.any(points > [shape[1] - 1, shape[0] - 1])
    ):
        raise ValueError("invalid_annotation_coordinates")
    for key, expected in (("mitral_annulus", (2, 2)), ("apex_landmark", (2,))):
        if record.get(key) is not None:
            landmark = np.asarray(record[key], dtype=float)
            if landmark.shape != expected or not np.isfinite(landmark).all():
                raise ValueError("invalid_annotation_landmark")


def _verify_database(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA quick_check").fetchone() != ("ok",) or db.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("invalid_database")
    if db.execute("SELECT 1 FROM frames WHERE length(pixels)>? LIMIT 1", (128 * 1024**2 + 65536,)).fetchone():
        raise ValueError("oversized_frame")
    if db.execute("SELECT 1 FROM samples WHERE length(metadata)>? LIMIT 1", (4 * 1024**2,)).fetchone():
        raise ValueError("oversized_annotation")
    shapes = {}
    for digest, payload in db.execute("SELECT hash,pixels FROM frames"):
        shapes[digest] = _verify_frame_blob(digest, payload)
    for sid, revision, excluded, metadata, frame in db.execute(
        "SELECT id,revision,excluded,metadata,frame FROM samples"
    ):
        if HEX_ID.fullmatch(sid) is None or type(revision) is not int or revision < 1 or excluded not in (0, 1):
            raise ValueError("invalid_sample")
        record = json.loads(metadata)
        if not isinstance(record, dict) or record.get("sample_id") != sid or record.get("schema_version") != 1:
            raise ValueError("invalid_sample_metadata")
        _verify_annotation(record, shapes[frame])


def verify_snapshot(package: Path) -> dict[str, Any]:
    package = external_path(package)
    manifest_path, database = package / "transfer.json", package / "archive.sqlite3"
    if manifest_path.is_symlink() or database.is_symlink() or manifest_path.stat().st_size > 8192:
        raise ValueError("invalid_transfer")
    data: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid_transfer")
    if (
        data.get("format") != "sonoforge-local-archive-v1"
        or re.fullmatch(r"[0-9a-f]{32}", str(data.get("origin"))) is None
        or type(data.get("sequence")) is not int
        or data["sequence"] < 1
        or HEX_ID.fullmatch(str(data.get("namespace"))) is None
        or HEX_ID.fullmatch(str(data.get("sha256"))) is None
        or type(data.get("bytes")) is not int
        or not 1 <= data["bytes"] <= MAX_SNAPSHOT_BYTES
        or database.stat().st_size != data["bytes"]
        or file_digest(database) != data["sha256"]
    ):
        raise ValueError("invalid_transfer")
    archive = SqliteMeasurementArchive(database, read_only=True)
    if archive_identity(archive) != data["namespace"]:
        raise ValueError("identity_mismatch")
    with archive._connection() as db:
        _verify_database(db)
        for key in ("origin", "export_sequence"):
            actual = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            expected = data["origin"] if key == "origin" else str(data["sequence"])
            if actual != (expected,):
                raise ValueError("history_mismatch")
    return data


def import_snapshot(package: Path, workspace: Path) -> Path:
    """Keep immutable snapshots; latest sequence per origin is used by inventory.

    Different contents at the SAME origin/sequence are a fork, never last-write
    wins. A newer import from one origin does not erase another PC's material.
    """
    workspace = external_path(workspace)
    data = verify_snapshot(package)
    target = external_path(workspace / "imports" / str(data["origin"]) / str(data["sequence"]))
    if not target.is_relative_to(workspace):
        raise ValueError("import_path_escapes_workspace")
    if target.exists():
        existing = verify_snapshot(target)
        if existing != data:
            raise ValueError("origin_sequence_conflict")
        return target
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if shutil.disk_usage(target.parent).free < data["bytes"] + 1024**2:
        raise ValueError("insufficient_disk_space")
    with tempfile.TemporaryDirectory(prefix=".ml-import-", dir=target.parent) as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir(mode=0o700)
        shutil.copyfile(package / "archive.sqlite3", stage / "archive.sqlite3")
        atomic_json(stage / "transfer.json", data)
        # Recheck the COPIED data: source can change during removable-media I/O.
        verify_snapshot(stage)
        (stage / "archive.sqlite3").chmod(0o600)
        stage.rename(target)
    return target


def latest_snapshots(workspace: Path) -> list[Path]:
    directory = external_path(workspace) / "imports"
    if not directory.exists():
        return []
    result = []
    if directory.is_symlink():
        raise ValueError("invalid_import_history")
    for origin in sorted(directory.iterdir()):
        if origin.is_symlink() or re.fullmatch(r"[0-9a-f]{32}", origin.name) is None or not origin.is_dir():
            raise ValueError("invalid_import_history")
        versions = [p for p in origin.iterdir() if p.name.isdecimal() and p.is_dir()]
        if any(p.is_symlink() for p in versions):
            raise ValueError("invalid_import_history")
        if versions:
            result.append(max(versions, key=lambda p: int(p.name)))
    return result
