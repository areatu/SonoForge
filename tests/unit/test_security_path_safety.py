"""Tests for path traversal protection in storage."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from echo_personal_tool.constructor.storage.image_storage import ImageStorage
from echo_personal_tool.infrastructure.orthanc_cache import OrthancSessionCache


class TestOrthancCachePathSafety:
    def test_valid_uids_work(self, tmp_path: Path) -> None:
        cache = OrthancSessionCache(tmp_path)
        session = cache.create_session()
        path = cache.save_instance(session, "1.2.3", "4.5.6", "7.8.9", b"DICM")
        assert path.exists()
        assert path.read_bytes() == b"DICM"

    def test_invalid_uid_rejected(self, tmp_path: Path) -> None:
        cache = OrthancSessionCache(tmp_path)
        session = cache.create_session()
        with pytest.raises(ValueError, match="Invalid DICOM UID"):
            cache.save_instance(session, "../etc", "4.5.6", "7.8.9", b"DICM")

    def test_path_traversal_in_study_uid(self, tmp_path: Path) -> None:
        cache = OrthancSessionCache(tmp_path)
        session = cache.create_session()
        with pytest.raises(ValueError):
            cache.save_instance(session, "../../etc/passwd", "1.2", "3.4", b"DICM")

    def test_path_traversal_in_series_uid(self, tmp_path: Path) -> None:
        cache = OrthancSessionCache(tmp_path)
        session = cache.create_session()
        with pytest.raises(ValueError):
            cache.save_instance(session, "1.2", "../secret", "3.4", b"DICM")

    def test_path_traversal_in_sop_uid(self, tmp_path: Path) -> None:
        cache = OrthancSessionCache(tmp_path)
        session = cache.create_session()
        with pytest.raises(ValueError):
            cache.save_instance(session, "1.2", "3.4", "../../etc/shadow", b"DICM")

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows uses different file permissions")
    def test_file_permissions_restrictive(self, tmp_path: Path) -> None:
        import os

        cache = OrthancSessionCache(tmp_path)
        session = cache.create_session()
        path = cache.save_instance(session, "1.2.3", "4.5.6", "7.8.9", b"DICM")
        mode = os.stat(path).st_mode & 0o777
        assert mode == 0o600, f"Expected 0600, got {oct(mode)}"


class TestImageStoragePathSafety:
    def test_resolve_valid_filename(self, tmp_path: Path) -> None:
        storage = ImageStorage(tmp_path)
        (tmp_path / "test.png").write_bytes(b"PNG")
        assert storage.resolve("test.png") == tmp_path / "test.png"

    def test_resolve_path_traversal_rejected(self, tmp_path: Path) -> None:
        storage = ImageStorage(tmp_path)
        assert storage.resolve("../../etc/passwd") is None

    def test_resolve_slash_rejected(self, tmp_path: Path) -> None:
        storage = ImageStorage(tmp_path)
        assert storage.resolve("sub/file.png") is None

    def test_delete_path_traversal_rejected(self, tmp_path: Path) -> None:
        storage = ImageStorage(tmp_path)
        assert storage.delete("../../etc/passwd") is False

    def test_rename_path_traversal_rejected(self, tmp_path: Path) -> None:
        storage = ImageStorage(tmp_path)
        (tmp_path / "old.png").write_bytes(b"PNG")
        result = storage.rename("old.png", "../../new.png")
        assert result == "old.png"
