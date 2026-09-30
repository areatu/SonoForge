"""Unit tests for OrthancSessionCache."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache

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


def test_instance_stored_directly_under_study_dir(tmp_path: Path) -> None:
    """No series directory level: session/<study>/<sop>.dcm."""
    cache = OrthancSessionCache(tmp_path)
    session = cache.create_session()
    path = cache.save_instance(session, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")
    assert path.parent == cache.study_path(session, STUDY_UID)
    assert path.name == f"{SOP_UID}.dcm"


def test_instance_path_fits_windows_max_path(tmp_path: Path) -> None:
    """Regression: the 4-level UID layout exceeded MAX_PATH (260) -> [Errno 2]."""
    cache = OrthancSessionCache(tmp_path)
    session = cache.create_session()
    path = cache.save_instance(session, STUDY_UID, SERIES_UID, SOP_UID, b"DICM")
    reported = Path(_REPORTED_CACHE_ROOT) / path.relative_to(tmp_path)
    assert len(str(reported)) < 260, f"path too long for Windows: {reported}"
    assert path.exists()
