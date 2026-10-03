"""Filesystem cache for DICOM instances downloaded from Orthanc.

The cache contains raw DICOM (and therefore may contain PHI). It is a managed
transient store, not an encrypted archive: callers own its retention policy and
the host OS / volume is responsible for at-rest protection.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from collections.abc import Iterable
from pathlib import Path

from echo_personal_tool.infrastructure.dicom_uid_validator import safe_uid_path_component

_DEFAULT_MAX_AGE_DAYS = 7
_DEFAULT_MAX_SIZE_BYTES = 20 * 1024 * 1024 * 1024


class OrthancCacheQuotaExceeded(OSError):
    """Raised before a DICOM write would exceed the managed-cache quota."""


class OrthancSessionCache:
    def __init__(self, root: Path, *, max_size_bytes: int = _DEFAULT_MAX_SIZE_BYTES) -> None:
        self._root = Path(root)
        self._max_size_bytes = max(0, int(max_size_bytes))
        self._lock = threading.RLock()
        self._known_size_bytes: int | None = None

    @property
    def root(self) -> Path:
        """Directory containing the per-download session folders."""
        return self._root

    @property
    def max_size_bytes(self) -> int:
        """Maximum combined size of managed DICOM session files."""
        return self._max_size_bytes

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        (self._root / f"session-{session_id}").mkdir(parents=True, exist_ok=True)
        return session_id

    def save_instance(
        self,
        session_id: str,
        study_uid: str,
        series_uid: str,
        sop_uid: str,
        data: bytes,
    ) -> Path:
        # Validate UIDs to prevent path traversal
        safe_study = safe_uid_path_component(study_uid)
        safe_uid_path_component(series_uid)
        safe_sop = safe_uid_path_component(sop_uid)
        # Layout: session-<id>/<study UID>/<sop UID>.dcm
        # The series directory level is intentionally omitted: four levels of
        # full DICOM UIDs exceed the Windows MAX_PATH limit (260), which made
        # every write fail with [Errno 2] during real server downloads.
        session_dir = self._root / f"session-{session_id}"
        path = session_dir / safe_study / f"{safe_sop}.dcm"
        with self._lock:
            if path.is_symlink():
                raise OSError("Refusing to write through a symlink in the DICOM cache")
            current_size = self._current_size_bytes_locked()
            try:
                existing_size = path.stat().st_size if path.is_file() else 0
            except FileNotFoundError:
                existing_size = 0
            projected_size = current_size - existing_size + len(data)
            if projected_size > self._max_size_bytes:
                raise OrthancCacheQuotaExceeded(
                    f"Orthanc cache quota ({self._max_size_bytes} bytes) reached; clear cached sessions before retrying"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                path.write_bytes(data)
                # Set restrictive permissions where the platform supports POSIX
                # mode bits. Windows ACLs are inherited from the profile/volume.
                os.chmod(path, 0o600)
            except OSError:
                # A failed/partial write makes our accounting uncertain.
                self._known_size_bytes = None
                raise
            self._known_size_bytes = projected_size
            # The session directory mtime is the retention timestamp. Refresh it
            # for every successful write so a long download is not aged from its
            # initial folder creation time.
            try:
                os.utime(session_dir, None)
            except OSError:
                pass
        return path

    def study_path(self, session_id: str, study_uid: str) -> Path:
        return self._root / f"session-{session_id}" / study_uid

    def session_path(self, session_id: str) -> Path:
        return self._root / f"session-{session_id}"

    def session_id_for_path(self, path: Path) -> str | None:
        """Return the cache session owning *path*, or ``None`` for other files."""
        try:
            relative = Path(path).resolve(strict=False).relative_to(self._root.resolve(strict=False))
        except (OSError, ValueError):
            return None
        if len(relative.parts) < 3 or not relative.parts[0].startswith("session-"):
            return None
        session_id = relative.parts[0][len("session-") :]
        return session_id or None

    def clear_session(self, session_id: str) -> None:
        session_dir = self._root / f"session-{session_id}"
        with self._lock:
            if session_dir.exists() and not session_dir.is_symlink():
                shutil.rmtree(session_dir, ignore_errors=True)
                self._known_size_bytes = None

    def clear_all(self, preserve_session_ids: Iterable[str] = ()) -> int:
        """Remove cached sessions, optionally retaining sessions still in use.

        Returns the number of session directories removed. Removal uses normal
        filesystem deletion; it is not a secure-erasure operation.
        """
        with self._lock:
            if not self._root.exists():
                return 0
            preserved_names = {f"session-{session_id}" for session_id in preserve_session_ids if session_id}
            removed = 0
            entries = list(self._root.iterdir())
            for entry in entries:
                if (
                    not entry.name.startswith("session-")
                    or entry.name in preserved_names
                    or entry.is_symlink()
                    or not entry.is_dir()
                ):
                    continue
                shutil.rmtree(entry, ignore_errors=True)
                if not entry.exists():
                    removed += 1
            if removed:
                self._known_size_bytes = None
            return removed

    def size_bytes(self) -> int:
        """Return the size of regular files in managed session folders.

        Symlinks are not followed, so an unexpected link cannot make the size
        scan traverse unrelated files elsewhere on the machine.
        """
        with self._lock:
            self._known_size_bytes = self._measure_size_bytes()
            return self._known_size_bytes

    def _current_size_bytes_locked(self) -> int:
        if self._known_size_bytes is None:
            self._known_size_bytes = self._measure_size_bytes()
        return self._known_size_bytes

    def _measure_size_bytes(self) -> int:
        if not self._root.exists():
            return 0
        total = 0
        pending: list[Path] = []
        try:
            with os.scandir(self._root) as entries:
                for entry in entries:
                    try:
                        if entry.name.startswith("session-") and entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            return 0

        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                continue
        return total

    def clear_stale(self, max_age_days: int = _DEFAULT_MAX_AGE_DAYS) -> int:
        """Remove session directories older than ``max_age_days``.

        This is run at application startup as crash recovery. Returns the
        number of session directories removed.
        """
        with self._lock:
            if not self._root.exists():
                return 0
            cutoff = time.time() - (max_age_days * 86400)
            removed = 0
            try:
                entries = list(self._root.iterdir())
            except OSError:
                return 0
            for entry in entries:
                if not entry.name.startswith("session-") or entry.is_symlink() or not entry.is_dir():
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    if not entry.exists():
                        removed += 1
            if removed:
                self._known_size_bytes = None
            return removed
