"""Atomic per-study storage, independent of Qt and the disposable DICOM cache."""

from __future__ import annotations

import errno
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    MAX_DOCUMENT_BYTES,
    SEMANTICS_VERSION,
    VERSION,
    MeasurementStorageError,
    dumps,
    loads,
    study_key,
)

_UTC = timezone.utc  # noqa: UP017 - retain Python 3.10 compatibility


class MeasurementRepository:
    def __init__(self, root: Path, max_bytes: int = 1024**3):
        self.root = Path(root)
        self.max_bytes = max_bytes
        self._lock_file = None

    def _safe(self, path: Path) -> Path:
        # Never follow record/root links, including Windows junctions/reparse points.
        for item in (self.root, path):
            if item.is_symlink() or (item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400):
                raise MeasurementStorageError("unsafe_path")
        return path

    def _path(self, uid: str) -> Path:
        return self._safe(self.root / (study_key(uid) + ".json"))

    def acquire(self) -> None:
        if self._lock_file is not None:
            return
        self._safe(self.root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._safe(self.root / ".writer.lock")
        file = open(path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                file.seek(0, 2)
                if file.tell() == 0:
                    file.write(b"0")
                    file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            file.close()
            raise MeasurementStorageError("busy") from exc
        self._lock_file = file
        # Incomplete atomic writes are never used as recovery records.
        for temp in self.root.glob(".pending-*.tmp"):
            self._safe(temp).unlink(missing_ok=True)

    def close(self) -> None:
        if self._lock_file is not None:
            self._lock_file.close()  # OS releases advisory lock on close/process death.
            self._lock_file = None

    def load(self, uid: str) -> dict | None:
        path = self._path(uid)
        try:
            with path.open("rb") as file:
                record = loads(file.read(MAX_DOCUMENT_BYTES + 1))
        except FileNotFoundError:
            return None
        if record["study_uid"] != uid:
            raise MeasurementStorageError("identity")
        return record

    def save(self, uid: str, data, sources: dict, expected_revision: int) -> dict:
        self.acquire()
        path = self._path(uid)
        previous = self.load(uid)  # corrupt/future records block writes, never auto-replaced
        revision = previous["revision"] if previous else 0
        if revision != expected_revision:
            raise MeasurementStorageError("conflict")
        record = dict(
            format=FORMAT,
            schema_version=VERSION,
            measurement_semantics_version=SEMANTICS_VERSION,
            study_uid=uid,
            revision=revision + 1,
            saved_at=datetime.now(_UTC).isoformat(),
            sources=sources,
            data=data,
        )
        payload = dumps(record)
        old_size = path.stat().st_size if path.exists() else 0
        if self.size_bytes() - old_size + len(payload) > self.max_bytes:
            raise MeasurementStorageError("quota")
        self.atomic_write(path, payload)
        return record

    @staticmethod
    def atomic_write(path: Path, payload: bytes) -> None:
        if path.is_symlink():
            raise MeasurementStorageError("unsafe_path")
        # One attempt with a uuid name, never tempfile.mkstemp(): on Windows a
        # directory denied by ACL makes mkstemp spin through TMP_MAX retries —
        # its PermissionError fallback trusts os.access(W_OK), which cannot see
        # deny ACEs — stalling the writer for minutes instead of failing fast.
        temp: Path | None = None
        fd = -1
        for _ in range(3):
            candidate = path.parent / f".pending-{uuid.uuid4().hex}.tmp"
            try:
                fd = os.open(candidate, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            temp = candidate
            break
        if temp is None:
            raise FileExistsError(errno.EEXIST, "No usable temporary file name found")
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp, path)
            if os.name != "nt":
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temp.unlink(missing_ok=True)

    def entries(self) -> list[Path]:
        self._safe(self.root)
        return [self._safe(p) for p in sorted(self.root.glob("*.json")) if re.fullmatch(r"[a-f0-9]{64}\.json", p.name)]

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.entries())

    def _sync_directory(self) -> None:
        if os.name != "nt":
            fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def delete(self, uid: str) -> None:
        self.acquire()
        self._path(uid).unlink(missing_ok=True)
        self._sync_directory()

    def delete_key(self, key: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise MeasurementStorageError("identity")
        self.acquire()
        self._safe(self.root / (key + ".json")).unlink(missing_ok=True)
        self._sync_directory()

    def delete_all(self) -> None:
        self.acquire()
        for path in self.entries():
            path.unlink()  # report failure; never claim a partially failed delete succeeded
        self._sync_directory()
