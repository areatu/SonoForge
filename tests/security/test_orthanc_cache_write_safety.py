"""Fault injection and path-safety tests for the managed Orthanc DICOM cache (#554).

The cache is a PHI-bearing store written by a worker thread while a download is
in flight. These tests pin the three guarantees the issue asks for:

* a failure at any point of a write never leaves a partial file under the final
  ``*.dcm`` name, so a later scan cannot treat half an instance as ready DICOM;
* restrictive permissions exist at creation time, not after the payload lands;
* a session identifier and every existing path component below the cache root
  are validated before a single byte is written.

The failures are injected in-process (``os.open``/``os.write``/``os.fsync``/
``os.replace``/``os.getpid`` style monkeypatching of the module's ``os``
namespace). That proves the error path leaves no publishable file; it is not
power-loss evidence and is not claimed as such.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

from echo_personal_tool.infrastructure import orthanc_cache as cache_module
from echo_personal_tool.infrastructure.local_scanner import iter_media_files
from echo_personal_tool.infrastructure.orthanc_cache import (
    OrthancCachePathError,
    OrthancCacheQuotaExceeded,
    OrthancSessionCache,
)

STUDY_UID = "1.2.410.200001.1.1185.2062614048.1.20260929.1094518981.328.1"
SERIES_UID = "1.2.410.200001.1.1185.2062614048.2.20260929.1094519409.100.1"
SOP_UID = "1.2.410.200001.1.1185.2062614048.3.20260929.1094703762.595.3"
OTHER_SOP_UID = "1.2.410.200001.1.1185.2062614048.3.20260929.1094703762.596.3"

pytestmark = pytest.mark.security

_POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not applied on Windows")


@pytest.fixture()
def cache(tmp_path: Path) -> OrthancSessionCache:
    return OrthancSessionCache(tmp_path / "cache")


def _final_files(cache: OrthancSessionCache, session_id: str) -> list[Path]:
    session_dir = cache.session_path(session_id)
    return sorted(session_dir.rglob("*.dcm")) if session_dir.exists() else []


def _temp_files(cache: OrthancSessionCache, session_id: str) -> list[Path]:
    session_dir = cache.session_path(session_id)
    return sorted(session_dir.rglob("*.tmp")) if session_dir.exists() else []


def _save(cache: OrthancSessionCache, session_id: str, sop_uid: str = SOP_UID, payload: bytes = b"DICM") -> Path:
    return cache.save_instance(session_id, STUDY_UID, SERIES_UID, sop_uid, payload)


# ── atomic write: no partial file is ever published ─────────────────


def test_successful_write_leaves_no_temporary_file(cache: OrthancSessionCache) -> None:
    session = cache.create_session()
    path = _save(cache, session, payload=b"DICM payload")

    assert path.read_bytes() == b"DICM payload"
    assert _temp_files(cache, session) == []
    # The scanner only ever sees the complete file, and its name is the final one.
    assert [p.name for p in iter_media_files(cache.session_path(session))] == [path.name]


def test_failed_payload_write_never_publishes_a_dicom(cache: OrthancSessionCache, monkeypatch) -> None:
    """A disk that reports a short write must not leave a truncated ``*.dcm``."""
    session = cache.create_session()
    real_fdopen = os.fdopen

    class _ShortWritingFile:
        """Accepts a prefix of the payload, then fails like a full disk."""

        def __init__(self, wrapped) -> None:
            self._wrapped = wrapped

        def write(self, data) -> int:
            self._wrapped.write(bytes(data)[:4])
            raise OSError(28, "No space left on device")

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> None:
            self._wrapped.close()

    def short_fdopen(fd, *args, **kwargs):
        return _ShortWritingFile(real_fdopen(fd, *args, **kwargs))

    monkeypatch.setattr(cache_module.os, "fdopen", short_fdopen)

    with pytest.raises(OSError, match="No space left"):
        _save(cache, session, payload=b"DICM" + b"\x00" * 512)

    assert _final_files(cache, session) == [], "a partially written instance must not appear as *.dcm"
    assert _temp_files(cache, session) == [], "the temporary file is cleaned up on failure"
    # Nothing the scanner accepts is left in the session at all.
    assert list(iter_media_files(cache.session_path(session))) == []


def test_a_short_write_count_is_treated_as_a_failure(cache: OrthancSessionCache, monkeypatch) -> None:
    """``write`` returning fewer bytes than asked is an error, not a success."""
    session = cache.create_session()
    real_fdopen = os.fdopen

    class _CountingFile:
        def __init__(self, wrapped) -> None:
            self._wrapped = wrapped

        def write(self, data) -> int:
            self._wrapped.write(bytes(data)[:2])
            return 2  # a short count, without raising

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> None:
            self._wrapped.close()

    monkeypatch.setattr(cache_module.os, "fdopen", lambda fd, *a, **k: _CountingFile(real_fdopen(fd, *a, **k)))

    with pytest.raises(OSError, match="Short write"):
        _save(cache, session, payload=b"DICM payload")

    assert _final_files(cache, session) == []
    assert _temp_files(cache, session) == []


def test_failed_fsync_never_publishes_a_dicom(cache: OrthancSessionCache, monkeypatch) -> None:
    session = cache.create_session()

    def failing_fsync(fd: int) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(cache_module.os, "fsync", failing_fsync)

    with pytest.raises(OSError, match="Input/output error"):
        _save(cache, session, payload=b"DICM" + b"\x00" * 64)

    assert _final_files(cache, session) == []
    assert _temp_files(cache, session) == []


def test_failed_replace_keeps_the_previous_instance_and_drops_the_temp(cache: OrthancSessionCache, monkeypatch) -> None:
    session = cache.create_session()
    first = _save(cache, session, payload=b"first complete instance")

    def failing_replace(src, dst) -> None:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(cache_module.os, "replace", failing_replace)

    with pytest.raises(OSError, match="Permission denied"):
        _save(cache, session, payload=b"second instance")

    assert _final_files(cache, session) == [first]
    assert first.read_bytes() == b"first complete instance"
    assert _temp_files(cache, session) == []


def test_interrupted_process_leaves_no_publishable_dicom(cache: OrthancSessionCache, monkeypatch) -> None:
    """A write interrupted between fsync and rename is invisible to the scanner."""
    session = cache.create_session()

    class _Interrupted(BaseException):
        """Stands in for a killed worker: not an ``OSError``, like a BaseException."""

    def interrupting_replace(src, dst) -> None:
        raise _Interrupted

    monkeypatch.setattr(cache_module.os, "replace", interrupting_replace)

    with pytest.raises(_Interrupted):
        _save(cache, session, payload=b"DICM" + b"\x00" * 32)

    assert _final_files(cache, session) == []
    assert list(iter_media_files(cache.session_path(session))) == []


def test_rewrite_replaces_an_existing_instance_in_place(cache: OrthancSessionCache) -> None:
    session = cache.create_session()
    path = _save(cache, session, payload=b"old")
    assert _save(cache, session, payload=b"new payload") == path
    assert path.read_bytes() == b"new payload"
    assert cache.size_bytes() == len(b"new payload")


def test_accounting_recovers_after_a_failed_write(cache: OrthancSessionCache, monkeypatch) -> None:
    """A failed write drops the cached size, so the next admitted write is exact."""
    cache = OrthancSessionCache(cache.root, max_size_bytes=8)
    session = cache.create_session()
    _save(cache, session, payload=b"DICM")

    real_replace = os.replace
    monkeypatch.setattr(cache_module.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError(13, "denied")))
    with pytest.raises(OSError):
        _save(cache, session, sop_uid=OTHER_SOP_UID, payload=b"DICM")
    monkeypatch.setattr(cache_module.os, "replace", real_replace)

    # Without a recomputed size the failed attempt could admit a 12-byte file
    # over the 8-byte limit; measured size keeps the limit honest.
    assert cache.size_bytes() == 4
    with pytest.raises(OrthancCacheQuotaExceeded):
        _save(cache, session, sop_uid=OTHER_SOP_UID, payload=b"x" * 8)


# ── permissions are set at creation ─────────────────────────────────


@_POSIX_ONLY
def test_file_and_directories_are_private_from_creation(cache: OrthancSessionCache) -> None:
    session = cache.create_session()
    path = _save(cache, session, payload=b"DICM")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(cache.session_path(session).stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@_POSIX_ONLY
def test_temporary_file_is_created_private(cache: OrthancSessionCache, monkeypatch) -> None:
    """The mode is applied by ``os.open`` itself, before the payload exists."""
    session = cache.create_session()
    observed: list[int] = []
    real_open = os.open

    def recording_open(path, flags, mode=0o777, *args, **kwargs):
        if isinstance(path, (str, os.PathLike)) and str(path).endswith(".tmp"):
            observed.append(mode)
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(cache_module.os, "open", recording_open)

    _save(cache, session, payload=b"DICM")

    assert observed, "the instance is written through a temporary file"
    assert set(observed) == {0o600}


@_POSIX_ONLY
def test_permissions_are_applied_before_the_payload_is_flushed(cache: OrthancSessionCache, monkeypatch) -> None:
    """At fsync time the payload already sits in a ``0600`` file."""
    session = cache.create_session()
    seen: list[int] = []
    real_fsync = os.fsync

    def checking_fsync(fd: int) -> None:
        seen.append(stat.S_IMODE(os.fstat(fd).st_mode))
        real_fsync(fd)

    monkeypatch.setattr(cache_module.os, "fsync", checking_fsync)

    path = _save(cache, session, payload=b"DICM")

    # One fsync for the instance file, one for its directory.
    assert seen[0] == 0o600, "the instance bytes never live in a group/world-readable file"
    assert set(seen) <= {0o600, 0o700}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


# ── session identifier validation ───────────────────────────────────


@pytest.mark.parametrize(
    "session_id",
    [
        "",
        "..",
        "../outside",
        "..\\outside",
        "/etc",
        "C:\\Windows",
        "a/b",
        "a\\b",
        "0" * 36,
        "00000000-0000-0000-0000-00000000000",
        "00000000-0000-0000-0000-0000000000000",
        "00000000-0000-0000-0000-00000000000G",
        "00000000-0000-0000-0000-000000000000\n",
        " 00000000-0000-0000-0000-000000000000",
        "%2e%2e%2foutside",
        "session-00000000-0000-0000-0000-000000000000",
    ],
)
def test_invalid_session_ids_are_refused_before_any_path_is_built(
    cache: OrthancSessionCache, tmp_path: Path, session_id: str
) -> None:
    with pytest.raises(OrthancCachePathError):
        cache.save_instance(session_id, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")

    with pytest.raises(OrthancCachePathError):
        cache.session_path(session_id)

    with pytest.raises(OrthancCachePathError):
        cache.study_path(session_id, STUDY_UID)

    # Nothing escaped the cache root, and the cache root was not even created:
    # the identifier is rejected before any directory is touched.
    assert not (tmp_path / "outside").exists()
    assert list(tmp_path.iterdir()) == []


def test_clearing_an_invalid_session_id_is_a_no_op(cache: OrthancSessionCache, tmp_path: Path) -> None:
    """A bad identifier must never delete an arbitrary directory."""
    victim = tmp_path / "session-.."
    victim.mkdir()
    (victim / "keep.dcm").write_bytes(b"DICM")
    cache.create_session()

    cache.clear_session("../victim")
    cache.clear_session("..")

    assert victim.is_dir()
    assert (victim / "keep.dcm").exists()


def test_preserved_session_ids_cannot_name_an_outside_directory(cache: OrthancSessionCache, tmp_path: Path) -> None:
    outside = tmp_path / "session-.."
    outside.mkdir()
    session = cache.create_session()
    _save(cache, session, payload=b"DICM")

    removed = cache.clear_all(preserve_session_ids={"..", "../x", session})

    assert removed == 0, "the only real session is the preserved one"
    assert cache.session_path(session).is_dir()
    assert outside.is_dir()


def test_session_id_for_path_rejects_non_uuid_session_directories(cache: OrthancSessionCache) -> None:
    forged = cache.root / "session-.." / "s-x" / "i-y.dcm"
    forged.parent.mkdir(parents=True)
    forged.write_bytes(b"DICM")

    assert cache.session_id_for_path(forged) is None


# ── symlink hardening below the cache root ──────────────────────────


def test_write_through_a_symlinked_study_directory_is_refused(
    cache: OrthancSessionCache, tmp_path: Path, monkeypatch
) -> None:
    session = cache.create_session()
    _save(cache, session, sop_uid=OTHER_SOP_UID, payload=b"first")
    real_study_dir = cache.study_path(session, STUDY_UID)
    assert real_study_dir.is_dir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    shutil.rmtree(real_study_dir)
    try:
        real_study_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(OrthancCachePathError, match="symbolic link"):
        _save(cache, session, payload=b"DICM")

    assert list(outside.iterdir()) == [], "nothing is written through the link"


def test_write_through_a_symlinked_session_directory_is_refused(cache: OrthancSessionCache, tmp_path: Path) -> None:
    session = cache.create_session()
    session_dir = cache.session_path(session)
    outside = tmp_path / "outside-session"
    outside.mkdir()
    session_dir.rmdir()
    try:
        session_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(OrthancCachePathError, match="symbolic link"):
        _save(cache, session, payload=b"DICM")

    assert list(outside.iterdir()) == []


def test_symlinked_final_instance_file_is_replaced_not_followed(cache: OrthancSessionCache, tmp_path: Path) -> None:
    """A planted link under the final name is overwritten by the rename."""
    session = cache.create_session()
    target = tmp_path / "target.dcm"
    target.write_bytes(b"untouched")
    path = _save(cache, session, sop_uid=OTHER_SOP_UID, payload=b"first")
    outside = tmp_path / "outside.dcm"
    outside.write_bytes(b"secret")

    link = path
    link.unlink()
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(OrthancCachePathError, match="symbolic link"):
        _save(cache, session, sop_uid=OTHER_SOP_UID, payload=b"second")

    assert outside.read_bytes() == b"secret"
    assert target.read_bytes() == b"untouched"


def test_a_symlinked_cache_root_is_allowed(cache: OrthancSessionCache, tmp_path: Path) -> None:
    """The user may point the configured root at a link (e.g. another volume)."""
    real_root = tmp_path / "real-cache"
    real_root.mkdir()
    linked_root = tmp_path / "linked-cache"
    try:
        linked_root.symlink_to(real_root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    linked_cache = OrthancSessionCache(linked_root)
    session = linked_cache.create_session()
    path = linked_cache.save_instance(session, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")

    assert path.read_bytes() == b"DICM"
    assert (real_root / f"session-{session}").is_dir()
