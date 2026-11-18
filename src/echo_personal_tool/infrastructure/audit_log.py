"""Append-only, SHA-256 hash-chained local audit trail (``audit.jsonl``).

Every event is validated by :mod:`echo_personal_tool.domain.models.audit` before
touching disk, written as a single canonical UTF-8 JSON line and flushed with
``os.fsync``. Refuses symlinked directories/files and never logs raw PHI.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import sys
import threading
import uuid
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echo_personal_tool.domain.models.audit import (
    GENESIS_HASH,
    AuditAction,
    AuditEntry,
    AuditVerificationResult,
    DetailScalar,
    build_audit_entry,
    sanitize_audit_details,
    validate_actor_id,
    validate_audit_study_key,
    validate_target_id,
    verify_audit_chain,
)

_UTC = timezone.utc  # noqa: UP017 - aligned with ruff target py310
AUDIT_FILENAME = "audit.jsonl"
MAX_AUDIT_LINE_BYTES = 16 * 1024


class AuditLogError(RuntimeError):
    """Safe error raised when the audit log cannot be read, verified or written."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _is_unsafe_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return False
    return bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _entry_to_json_line(entry: AuditEntry) -> bytes:
    payload = {
        "seq": entry.seq,
        "timestamp": entry.timestamp,
        "action": entry.action,
        "actor_id": entry.actor_id,
        "target_id": entry.target_id,
        "study_key": entry.study_key,
        "details": dict(entry.details),
        "prev_hash": entry.prev_hash,
        "entry_hash": entry.entry_hash,
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def _parse_entry_line(raw_line: bytes) -> AuditEntry:
    if len(raw_line) > MAX_AUDIT_LINE_BYTES:
        raise ValueError("line_too_long")
    data = json.loads(raw_line.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not_object")
    seq = data.get("seq")
    if type(seq) is not int or seq < 1:
        raise ValueError("bad_seq")
    timestamp = data.get("timestamp")
    action = data.get("action")
    actor_id = data.get("actor_id")
    target_id = data.get("target_id", "")
    study_key = data.get("study_key", "")
    prev_hash = data.get("prev_hash")
    entry_hash = data.get("entry_hash")
    raw_details: Any = data.get("details", {})
    if (
        not isinstance(timestamp, str)
        or not isinstance(action, str)
        or not isinstance(actor_id, str)
        or not isinstance(target_id, str)
        or not isinstance(study_key, str)
        or not isinstance(prev_hash, str)
        or not isinstance(entry_hash, str)
        or not isinstance(raw_details, dict)
    ):
        raise ValueError("bad_types")
    details = sanitize_audit_details(raw_details)
    return AuditEntry(
        seq=seq,
        timestamp=timestamp,
        action=action,
        actor_id=validate_actor_id(actor_id),
        target_id=validate_target_id(target_id),
        study_key=validate_audit_study_key(study_key),
        details=details,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )


class LocalAuditLog:
    """Thread- and process-safe hash-chained JSONL audit log."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._path = self._root / AUDIT_FILENAME
        self._lock_path = self._root / ".audit.lock"
        self._thread_lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _ensure_safe_paths(self, *, create_root: bool) -> None:
        if _is_unsafe_link(self._root):
            raise AuditLogError("unsafe_path")
        if create_root:
            self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if _is_unsafe_link(self._path) or _is_unsafe_link(self._lock_path):
            raise AuditLogError("unsafe_path")

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            self._ensure_safe_paths(create_root=True)
            lock_fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            lock_file = os.fdopen(lock_fd, "a+b")
            try:
                if sys.platform == "win32":
                    import msvcrt

                    lock_file.seek(0, 2)
                    if lock_file.tell() == 0:
                        lock_file.write(b"0")
                        lock_file.flush()
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                yield
            except OSError as exc:
                raise AuditLogError("io_error") from exc
            finally:
                lock_file.close()

    def _read_lines_unlocked(self) -> list[bytes]:
        self._ensure_safe_paths(create_root=False)
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise AuditLogError("io_error") from exc
        if not raw:
            return []
        return [line for line in raw.splitlines() if line.strip()]

    def append(
        self,
        action: AuditAction | str,
        *,
        actor_id: str,
        target_id: str = "",
        study_key: str = "",
        details: Mapping[str, DetailScalar] | None = None,
        now: datetime | None = None,
    ) -> AuditEntry:
        """Append one validated event and fsync it to disk."""
        timestamp = (now if now is not None else datetime.now(_UTC)).isoformat()
        with self._locked():
            lines = self._read_lines_unlocked()
            if not lines:
                next_seq = 1
                prev_hash = GENESIS_HASH
            else:
                try:
                    last = _parse_entry_line(lines[-1])
                except (UnicodeDecodeError, ValueError) as exc:
                    raise AuditLogError("corrupt_tail") from exc
                if last.entry_hash != last.expected_hash():
                    raise AuditLogError("corrupt_tail")
                next_seq = last.seq + 1
                prev_hash = last.entry_hash
            entry = build_audit_entry(
                seq=next_seq,
                timestamp=timestamp,
                action=action,
                actor_id=actor_id,
                target_id=target_id,
                study_key=study_key,
                details=details,
                prev_hash=prev_hash,
            )
            encoded = _entry_to_json_line(entry)
            try:
                fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    written = os.write(fd, encoded)
                    if written != len(encoded):
                        raise AuditLogError("short_write")
                    os.fsync(fd)
                finally:
                    os.close(fd)
                if os.name != "nt":
                    with contextlib.suppress(OSError):
                        os.chmod(self._path, 0o600)
            except AuditLogError:
                raise
            except OSError as exc:
                raise AuditLogError("io_error") from exc
            return entry

    def read_recent(self, *, limit: int = 200) -> tuple[AuditEntry, ...]:
        """Return up to *limit* newest readable audit entries, newest first."""
        if limit <= 0:
            return ()
        with self._thread_lock:
            lines = self._read_lines_unlocked()
        selected = lines[-limit:]
        parsed: list[AuditEntry] = []
        for line in reversed(selected):
            try:
                parsed.append(_parse_entry_line(line))
            except (UnicodeDecodeError, ValueError):
                continue
        return tuple(parsed)

    def verify(self) -> AuditVerificationResult:
        """Verify the entire audit trail from line 1 against its SHA-256 hash chain."""
        with self._thread_lock:
            lines = self._read_lines_unlocked()
        entries: list[AuditEntry] = []
        for idx, line in enumerate(lines, start=1):
            try:
                entries.append(_parse_entry_line(line))
            except (UnicodeDecodeError, ValueError):
                prev = entries[-1].entry_hash if entries else GENESIS_HASH
                return AuditVerificationResult(
                    valid=False,
                    checked_count=idx - 1,
                    last_hash=prev,
                    first_broken_seq=idx,
                    reason="malformed_line",
                )
        return verify_audit_chain(entries)

    def export_copy(self, destination: Path) -> int:
        """Atomically write the current audit JSONL to *destination*; return entry count."""
        target = Path(destination)
        if _is_unsafe_link(target):
            raise AuditLogError("unsafe_path")
        with self._thread_lock:
            lines = self._read_lines_unlocked()
        payload = b"".join(line + b"\n" for line in lines)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp: Path | None = None
            fd = -1
            for _ in range(3):
                candidate = target.parent / f".audit-export-{uuid.uuid4().hex}.tmp"
                try:
                    fd = os.open(candidate, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
                    temp = candidate
                    break
                except FileExistsError:
                    continue
            if temp is None:
                raise OSError(errno.EEXIST, "no temporary export file")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
        except OSError as exc:
            raise AuditLogError("io_error") from exc
        return len(lines)
