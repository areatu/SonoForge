"""Filesystem cache for DICOM instances downloaded from Orthanc.

The cache contains raw DICOM (and therefore may contain PHI). It is a managed
transient store, not an encrypted archive: callers own its retention policy and
the host OS / volume is responsible for at-rest protection.

Write contract (issue #554): an instance is written into a temporary file in the
destination directory, flushed, fsynced and only then renamed onto its final
``*.dcm`` name, so an interrupted write can never publish a partial file under
a name the scanner reads as ready DICOM. The temporary file is created with
``0600`` and the directories are created with ``0700`` — permissions exist
before the first payload byte reaches the disk, never as a post-hoc chmod. Every
path component below the cache root is refused if it is a symbolic link, and a
session identifier must look like a UUID before it is interpolated into a path.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Iterable
from pathlib import Path

from echo_personal_tool.infrastructure.dicom_uid_validator import safe_uid_path_component

_DEFAULT_MAX_AGE_DAYS = 7
_DEFAULT_MAX_SIZE_BYTES = 20 * 1024 * 1024 * 1024

#: Only canonical UUID text is accepted as a session identifier. The value is
#: compared as a whole, so ``../x``, absolute paths, separators and URL-encoded
#: variants never become part of a filesystem path.
_SESSION_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TEMP_PREFIX = ".pending-"
_TEMP_SUFFIX = ".tmp"
_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600


class OrthancCacheQuotaExceeded(OSError):
    """Raised before a DICOM write would exceed the managed-cache quota."""


class OrthancCachePathError(OSError):
    """Unsafe cache path: invalid session identifier or a symbolic link.

    Messages are static on purpose: they never echo a path or an identifier
    into logs, because cache locations can themselves be identifying.
    """


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
        self._make_private_directory(self._root / f"session-{session_id}")
        return session_id

    def save_instance(
        self,
        session_id: str,
        study_uid: str,
        series_uid: str,
        sop_uid: str,
        data: bytes,
    ) -> Path:
        # Validate UIDs to prevent path traversal, but do not put full UIDs in
        # physical paths.  Their authoritative values remain in the unchanged
        # DICOM payload and are read back into InstanceMetadata.
        safe_study = safe_uid_path_component(study_uid)
        safe_uid_path_component(series_uid)
        safe_sop = safe_uid_path_component(sop_uid)
        # Layout: session-<id>/s-<96-bit digest>/i-<128-bit digest>.dcm.
        # Collision-resistant digests keep the whole path short even under a
        # long Windows profile/cache root; series identity stays in the header.
        session_dir = self._session_dir(session_id)
        path = session_dir / self._study_dir_name(safe_study) / self._instance_file_name(safe_sop)
        with self._lock:
            self._refuse_symlinked_ancestors(path)
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
            try:
                self._make_private_directory(session_dir)
                self._make_private_directory(path.parent)
                self._write_instance_atomically(path, data)
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

    # ── path safety ─────────────────────────────────────────────────

    @staticmethod
    def _is_valid_session_id(session_id: object) -> bool:
        return isinstance(session_id, str) and _SESSION_ID_RE.fullmatch(session_id) is not None

    @classmethod
    def _validated_session_id(cls, session_id: str) -> str:
        """Return *session_id* only if it is canonical UUID text."""
        if not cls._is_valid_session_id(session_id):
            raise OrthancCachePathError("Refusing an invalid Orthanc cache session identifier")
        return session_id

    def _session_dir(self, session_id: str) -> Path:
        return self._root / f"session-{self._validated_session_id(session_id)}"

    def _refuse_symlinked_ancestors(self, path: Path) -> None:
        """Refuse a write if any existing component below the root is a link.

        Checking only the final file is not enough: a linked study directory (or
        a linked cache root) redirects the whole write outside the managed
        store, where the ``0700``/``0600`` modes and the retention rules no
        longer apply.
        """
        for component in (path, *path.parents):
            # The root itself is the user's configured location and may be a
            # link legitimately; everything below it must be a real directory.
            if component == self._root or component.parent == component:
                return
            if component.is_symlink():
                raise OrthancCachePathError("Refusing to write through a symbolic link in the DICOM cache")

    @staticmethod
    def _make_private_directory(directory: Path) -> None:
        """Create *directory* (and parents) with ``0700`` before use.

        ``mkdir`` applies the mode at creation; the trailing ``chmod`` only
        repairs a directory an older build created, and is best effort because
        Windows inherits ACLs instead of POSIX mode bits.
        """
        directory.mkdir(mode=_DIRECTORY_MODE, parents=True, exist_ok=True)
        try:
            os.chmod(directory, _DIRECTORY_MODE)
        except OSError:
            pass

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        """Best-effort directory fsync so a rename survives a power loss."""
        if os.name == "nt":
            # Windows cannot open a directory for fsync; MoveFileEx is already
            # ordered by the filesystem journal.
            return
        try:
            fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    @classmethod
    def _write_instance_atomically(cls, path: Path, data: bytes) -> None:
        """Publish *data* at *path* only after a complete, flushed write.

        The temporary file lives in the destination directory so the final
        ``os.replace`` stays on one filesystem and is atomic: a crash, a disk
        error or a killed process leaves either the previous file or nothing,
        never a truncated ``*.dcm`` that the scanner would read as ready.
        """
        temp: Path | None = None
        fd = -1
        # A bounded number of attempts, never tempfile.mkstemp(): on Windows a
        # deny-ACL directory makes mkstemp retry TMP_MAX times after a slow
        # PermissionError path. ``O_EXCL`` with ``0600`` means the file exists
        # with its final permissions before any payload byte is written.
        for _ in range(3):
            candidate = path.parent / f"{_TEMP_PREFIX}{uuid.uuid4().hex}{_TEMP_SUFFIX}"
            try:
                fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
            except FileExistsError:
                continue
            temp = candidate
            break
        if temp is None:
            raise FileExistsError(errno.EEXIST, "No usable temporary file name in the DICOM cache")
        # An unusual umask can strip bits from the creation mode; restate it on
        # the handle before any payload byte is written so the file is never
        # readable by others even transiently.
        try:
            os.fchmod(fd, _FILE_MODE)
        except (AttributeError, OSError):
            pass
        try:
            with os.fdopen(fd, "wb") as file:
                fd = -1
                # ``FileIO.write`` may accept only part of a large payload (a
                # non-blocking descriptor, an interrupted syscall, a full disk
                # that reports the short count before failing). Read the count
                # so a short write is an error here, never a short DICOM file.
                written = file.write(data)
                if written != len(data):
                    raise OSError(errno.ENOSPC, "Short write in the DICOM cache")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp, path)
            cls._fsync_directory(path.parent)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                temp.unlink()
            except OSError:
                # Already renamed away, or the cleanup itself failed; a stray
                # ``.pending-*.tmp`` is not media and is removed by the next
                # session clear.
                pass

    @staticmethod
    def _uid_digest(uid: str, hex_chars: int) -> str:
        return hashlib.sha256(uid.encode("ascii")).hexdigest()[:hex_chars]

    @classmethod
    def _study_dir_name(cls, study_uid: str) -> str:
        return f"s-{cls._uid_digest(study_uid, 24)}"

    @classmethod
    def _instance_file_name(cls, sop_uid: str) -> str:
        return f"i-{cls._uid_digest(sop_uid, 32)}.dcm"

    def study_path(self, session_id: str, study_uid: str) -> Path:
        safe_study = safe_uid_path_component(study_uid)
        return self._session_dir(session_id) / self._study_dir_name(safe_study)

    def legacy_study_path(self, session_id: str, study_uid: str) -> Path:
        """Return the pre-hashing study directory for migration/read compatibility."""
        safe_study = safe_uid_path_component(study_uid)
        return self.session_path(session_id) / safe_study

    def session_path(self, session_id: str) -> Path:
        return self._session_dir(session_id)

    def session_id_for_path(self, path: Path) -> str | None:
        """Return the cache session owning *path*, or ``None`` for other files."""
        try:
            relative = Path(path).resolve(strict=False).relative_to(self._root.resolve(strict=False))
        except (OSError, ValueError):
            return None
        if len(relative.parts) < 3 or not relative.parts[0].startswith("session-"):
            return None
        session_id = relative.parts[0][len("session-") :]
        if _SESSION_ID_RE.fullmatch(session_id) is None:
            # A directory this cache cannot have created is not a session.
            return None
        return session_id

    def clear_session(self, session_id: str) -> None:
        try:
            session_dir = self._session_dir(session_id)
        except OrthancCachePathError:
            # Nothing this cache created can be named that way, so there is
            # nothing to remove; never delete an arbitrary path.
            return
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
            preserved_names = {
                f"session-{session_id}" for session_id in preserve_session_ids if self._is_valid_session_id(session_id)
            }
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
