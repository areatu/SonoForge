"""Unit tests for OrthancSessionCache."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from echo_personal_tool.infrastructure.orthanc_cache import (
    OrthancCacheQuotaExceeded,
    OrthancSessionCache,
)

# Realistic UIDs (60 chars each) as returned by the production Orthanc server.
STUDY_UID = "1.2.410.200001.1.1185.2062614048.1.20260929.1094518981.328.1"
SERIES_UID = "1.2.410.200001.1.1185.2062614048.2.20260929.1094519409.100.1"
SOP_UID = "1.2.410.200001.1.1185.2062614048.3.20260929.1094703762.595.3"

# Cache root from the bug report (its full instance path was 264 characters,
# over the Windows MAX_PATH limit of 260, so every write failed with [Errno 2]).
_REPORTED_CACHE_ROOT = r"C:\Users\user\.sonoforge\orthanc"


def test_session_cache_writes_instance(tmp_path: Path) -> None:
    cache = OrthancSessionCache(tmp_path)
    session = cache.create_session()
    path = cache.save_instance(session, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")
    assert path.exists()
    assert path.read_bytes() == b"DICM"
    assert cache.study_path(session, STUDY_UID).is_dir()


def test_clear_session_removes_dir(tmp_path: Path) -> None:
    cache = OrthancSessionCache(tmp_path)
    session = cache.create_session()
    cache.save_instance(session, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")
    session_dir = tmp_path / f"session-{session}"
    assert session_dir.is_dir()
    cache.clear_session(session)
    assert not session_dir.exists()


def test_clear_all_removes_all_sessions(tmp_path: Path) -> None:
    cache = OrthancSessionCache(tmp_path)
    s1 = cache.create_session()
    s2 = cache.create_session()
    cache.save_instance(s1, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")
    cache.save_instance(s2, STUDY_UID, SERIES_UID, SOP_UID, b"DICM2")
    assert len(list(tmp_path.iterdir())) == 2
    cache.clear_all()
    assert list(tmp_path.iterdir()) == []


def test_instance_uses_short_hashed_physical_path(tmp_path: Path) -> None:
    """Full UIDs remain logical identifiers and never lengthen cache paths."""
    cache = OrthancSessionCache(tmp_path)
    session = cache.create_session()
    path = cache.save_instance(session, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")
    assert path.parent == cache.study_path(session, STUDY_UID)
    assert path.parent.name.startswith("s-")
    assert path.name.startswith("i-")
    assert path.name.endswith(".dcm")
    assert STUDY_UID not in str(path)
    assert SOP_UID not in str(path)


def test_instance_path_fits_windows_max_path(tmp_path: Path) -> None:
    """Regression: UID directory/file names exceeded MAX_PATH on Windows 10."""
    cache = OrthancSessionCache(tmp_path)
    session = cache.create_session()
    maximal_uid = "1." + "2" * 62
    path = cache.save_instance(session, maximal_uid, SERIES_UID, maximal_uid, b"DICM")
    reported = Path(_REPORTED_CACHE_ROOT) / path.relative_to(tmp_path)
    assert len(str(reported)) < 180, f"path unexpectedly long: {reported}"
    assert path.exists()


def test_size_bytes_counts_cached_regular_files(tmp_path: Path) -> None:
    cache = OrthancSessionCache(tmp_path)
    session = cache.create_session()
    cache.save_instance(session, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")
    assert cache.size_bytes() == 4


def test_clear_all_preserves_sessions_still_in_use(tmp_path: Path) -> None:
    cache = OrthancSessionCache(tmp_path)
    active = cache.create_session()
    inactive = cache.create_session()
    cache.save_instance(active, STUDY_UID, SERIES_UID, SOP_UID, b"active")
    cache.save_instance(inactive, STUDY_UID, SERIES_UID, SOP_UID, b"inactive")

    removed = cache.clear_all(preserve_session_ids={active})

    assert removed == 1
    assert cache.session_path(active).is_dir()
    assert not cache.session_path(inactive).exists()


def test_session_id_for_cache_path(tmp_path: Path) -> None:
    cache = OrthancSessionCache(tmp_path)
    session = cache.create_session()
    instance = cache.save_instance(session, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")
    assert cache.session_id_for_path(instance) == session
    assert cache.session_id_for_path(tmp_path / "outside.dcm") is None


def test_clear_stale_removes_old_sessions_only(tmp_path: Path) -> None:
    cache = OrthancSessionCache(tmp_path)
    stale = cache.create_session()
    fresh = cache.create_session()
    stale_path = cache.session_path(stale)
    old_time = time.time() - (8 * 86400)
    os.utime(stale_path, (old_time, old_time))

    removed = cache.clear_stale()

    assert removed == 1
    assert not stale_path.exists()
    assert cache.session_path(fresh).is_dir()


def test_cache_quota_rejects_write_without_removing_existing_data(tmp_path: Path) -> None:
    cache = OrthancSessionCache(tmp_path, max_size_bytes=4)
    session = cache.create_session()
    cache.save_instance(session, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")

    with pytest.raises(OrthancCacheQuotaExceeded, match="quota"):
        cache.save_instance(
            session,
            STUDY_UID,
            SERIES_UID,
            "1.2.3.4",
            b"extra",
        )

    assert cache.size_bytes() == 4
    assert len(list(cache.session_path(session).rglob("*.dcm"))) == 1
