"""Atomic local-only frame+annotation store, separate from clinical documents."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

import numpy as np

from echo_personal_tool.domain.models.training_archive import ArchiveDecision, ArchiveSample, ArchiveWriteError
from echo_personal_tool.domain.services.training_archive import material_fingerprint


class SqliteMeasurementArchive:
    """Current revisions only; edits replace, deletions tombstone, pixels deduplicate.

    No DICOM tags/paths are stored. HMAC linkage is local pseudonymisation, NOT
    anonymisation: source pixels may include patient text. No network methods.
    """

    def __init__(self, path: Path, *, read_only: bool = False, quota_bytes: int | None = None) -> None:
        self.path = path
        self.read_only = read_only
        self.quota_bytes = quota_bytes

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            if self.read_only:
                with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                    yield connection
                return
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with closing(sqlite3.connect(self.path, timeout=2.0)) as connection, connection:
                self.path.chmod(0o600)
                connection.execute("PRAGMA foreign_keys=ON")
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value BLOB NOT NULL);
                    CREATE TABLE IF NOT EXISTS rejections(id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                        PRIMARY KEY(id, fingerprint));
                    CREATE TABLE IF NOT EXISTS frames(hash TEXT PRIMARY KEY, pixels BLOB NOT NULL);
                    CREATE TABLE IF NOT EXISTS samples(
                        id TEXT PRIMARY KEY, instance TEXT NOT NULL, revision INTEGER NOT NULL,
                        excluded INTEGER NOT NULL, metadata TEXT NOT NULL,
                        frame TEXT NOT NULL REFERENCES frames(hash));
                """)
                connection.execute("INSERT OR IGNORE INTO settings VALUES('salt', ?)", (os.urandom(32),))
                yield connection
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise ArchiveWriteError("local archive unavailable") from exc

    def token(self, kind: str, value: str) -> str:
        with self._connection() as db:
            salt = db.execute("SELECT value FROM settings WHERE key='salt'").fetchone()[0]
        return hmac.new(salt, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()

    def save(self, sample: ArchiveSample) -> bool:
        stream = io.BytesIO()
        np.save(stream, sample.pixels, allow_pickle=False)
        pixels = stream.getvalue()
        digest = hashlib.sha256(pixels).hexdigest()
        metadata = json.dumps(sample.metadata, sort_keys=True, allow_nan=False)
        with self._connection() as db:
            fingerprint = material_fingerprint(metadata, digest)
            if db.execute(
                "SELECT 1 FROM rejections WHERE id=? AND fingerprint=?", (sample.sample_id, fingerprint)
            ).fetchone():
                return False
            old = db.execute(
                "SELECT revision,excluded,metadata,frame FROM samples WHERE id=?", (sample.sample_id,)
            ).fetchone()
            if old is not None and not old[1] and old[2:] == (metadata, digest):
                return False
            new_frame = db.execute("SELECT 1 FROM frames WHERE hash=?", (digest,)).fetchone() is None
            required = len(metadata.encode("utf-8")) + (len(pixels) if new_frame else 0) + 65536
            if self.quota_bytes is not None and self.path.stat().st_size + required > self.quota_bytes:
                raise ArchiveWriteError("local archive quota reached")
            revision = old[0] + 1 if old else 1
            db.execute("INSERT OR IGNORE INTO frames VALUES(?,?)", (digest, pixels))
            db.execute(
                "INSERT OR REPLACE INTO samples VALUES(?,?,?,?,?,?)",
                (sample.sample_id, sample.metadata["instance_key"], revision, 0, metadata, digest),
            )
        return True

    def exclude_missing(self, instance_key: str, retained_ids: set[str]) -> None:
        with self._connection() as db:
            ids = db.execute("SELECT id FROM samples WHERE instance=? AND excluded=0", (instance_key,)).fetchall()
            for (sample_id,) in ids:
                if sample_id not in retained_ids:
                    db.execute("UPDATE samples SET excluded=1,revision=revision+1 WHERE id=?", (sample_id,))

    def exclude_study(self, study_key: str) -> None:
        with self._connection() as db:
            for sid, metadata in db.execute("SELECT id,metadata FROM samples WHERE excluded=0").fetchall():
                if json.loads(metadata)["study_key"] == study_key:
                    db.execute("UPDATE samples SET excluded=1,revision=revision+1 WHERE id=?", (sid,))

    def reject_sample(self, decision: ArchiveDecision) -> bool:
        """Reject only the material shown in the prompt; never a newer edit."""
        with self._connection() as db:
            row = db.execute("SELECT metadata,frame,excluded FROM samples WHERE id=?", (decision.sample_id,)).fetchone()
            if row is None or material_fingerprint(row[0], row[1]) != decision.fingerprint or row[2]:
                return False
            db.execute("INSERT OR IGNORE INTO rejections VALUES(?,?)", (decision.sample_id, decision.fingerprint))
            db.execute("UPDATE samples SET excluded=1,revision=revision+1 WHERE id=?", (decision.sample_id,))
        return True

    def records(self, *, include_excluded: bool = False) -> list[dict[str, object]]:
        """Metadata snapshot; export keeps only the current non-excluded revision."""
        with self._connection() as db:
            rows = db.execute("SELECT id,revision,excluded,metadata,frame FROM samples ORDER BY id").fetchall()
        return [
            {**json.loads(data), "sample_id": sid, "revision": rev, "excluded": bool(excluded), "frame_hash": frame}
            for sid, rev, excluded, data, frame in rows
            if include_excluded or not excluded
        ]

    def frame(self, digest: str) -> np.ndarray:
        with self._connection() as db:
            row = db.execute("SELECT pixels FROM frames WHERE hash=?", (digest,)).fetchone()
        if row is None:
            raise ArchiveWriteError("archive frame missing")
        return np.asarray(np.load(io.BytesIO(row[0]), allow_pickle=False))
