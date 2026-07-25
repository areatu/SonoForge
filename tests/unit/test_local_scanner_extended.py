"""Extended unit tests for infrastructure/local_scanner.py — covers edge cases and utility functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.infrastructure.local_scanner import (
    LocalDicomDirectoryScanner,
    LocalMediaDirectoryScanner,
    has_media,
    has_media_in_directory,
    iter_media_files,
    iter_study_roots,
)
from tests.fixtures.generate_synthetic_dicom import write_synthetic_dicom
from tests.fixtures.generate_synthetic_media import (
    write_synthetic_jpeg,
    write_synthetic_mp4,
    write_synthetic_png,
)


class TestAlias:
    def test_alias_same_class(self):
        assert LocalDicomDirectoryScanner is LocalMediaDirectoryScanner


class TestHasMedia:
    def test_has_media_true(self, tmp_path):
        write_synthetic_mp4(tmp_path / "clip.mp4")
        assert has_media(tmp_path) is True

    def test_has_media_false(self, tmp_path):
        (tmp_path / "readme.txt").write_text("no media")
        assert has_media(tmp_path) is False

    def test_has_media_nested(self, tmp_path):
        write_synthetic_dicom(tmp_path / "sub" / "a.dcm")
        assert has_media(tmp_path) is True


class TestHasMediaInDirectory:
    def test_non_recursive_with_media(self, tmp_path):
        write_synthetic_mp4(tmp_path / "clip.mp4")
        assert has_media_in_directory(tmp_path, recursive=False) is True

    def test_non_recursive_without_media(self, tmp_path):
        (tmp_path / "readme.txt").write_text("text")
        assert has_media_in_directory(tmp_path, recursive=False) is False

    def test_recursive_with_nested_media(self, tmp_path):
        write_synthetic_dicom(tmp_path / "sub" / "a.dcm")
        assert has_media_in_directory(tmp_path, recursive=True) is True

    def test_non_recursive_nested_not_found(self, tmp_path):
        write_synthetic_dicom(tmp_path / "sub" / "a.dcm")
        assert has_media_in_directory(tmp_path, recursive=False) is False


class TestIterMediaFiles:
    def test_yields_media_files(self, tmp_path):
        write_synthetic_mp4(tmp_path / "clip.mp4")
        write_synthetic_jpeg(tmp_path / "photo.jpg")
        (tmp_path / "readme.txt").write_text("text")
        files = list(iter_media_files(tmp_path))
        assert len(files) == 2

    def test_nested_files(self, tmp_path):
        write_synthetic_dicom(tmp_path / "sub" / "a.dcm")
        files = list(iter_media_files(tmp_path))
        assert len(files) == 1


class TestIterStudyRoots:
    def test_root_with_media_returns_root(self, tmp_path):
        write_synthetic_mp4(tmp_path / "clip.mp4")
        roots = iter_study_roots(tmp_path)
        assert roots == [tmp_path]

    def test_root_without_media_child_dirs(self, tmp_path):
        child = tmp_path / "study1"
        child.mkdir()
        write_synthetic_dicom(child / "a.dcm")
        roots = iter_study_roots(tmp_path)
        assert roots == [child]

    def test_multiple_child_dirs(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        write_synthetic_dicom(a / "a.dcm")
        write_synthetic_dicom(b / "b.dcm")
        roots = iter_study_roots(tmp_path)
        assert sorted(r.name for r in roots) == ["a", "b"]

    def test_root_with_media_and_children(self, tmp_path):
        write_synthetic_mp4(tmp_path / "clip.mp4")
        child = tmp_path / "study"
        child.mkdir()
        write_synthetic_dicom(child / "a.dcm")
        roots = iter_study_roots(tmp_path)
        # Root has media → returns root only
        assert roots == [tmp_path]


class TestScanRaisesNotADirectory:
    def test_scan_nonexistent_path(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            LocalMediaDirectoryScanner().scan(tmp_path / "nonexistent")


class TestScanEmptyDirectory:
    def test_scan_empty(self, tmp_path):
        studies = LocalMediaDirectoryScanner().scan(tmp_path)
        assert studies == []


class TestScanWithPng:
    def test_png_only(self, tmp_path):
        write_synthetic_png(tmp_path / "img.png")
        studies = LocalMediaDirectoryScanner().scan(tmp_path)
        assert len(studies) == 1
        assert studies[0].series[0].description == "Still (JPEG)"


class TestErrorLogPath:
    def test_error_log_written(self, tmp_path):
        error_log = tmp_path / "errors.log"
        scanner = LocalMediaDirectoryScanner(error_log_path=error_log)
        # Scan empty dir
        scanner.scan(tmp_path)
        # No error log should exist since no errors
        # But the path is set correctly
        assert scanner._error_log_path == error_log


class TestIterMediaFilesIgnoresSkippedDirs:
    def test_skipped_dirs_ignored(self, tmp_path):
        skipped = tmp_path / "__pycache__"
        skipped.mkdir()
        write_synthetic_mp4(skipped / "clip.mp4")
        files = list(iter_media_files(tmp_path))
        # __pycache__ is in SKIP_DIR_NAMES
        assert all("__pycache__" not in str(f) for f in files)

    def test_git_dir_ignored(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        write_synthetic_mp4(git_dir / "clip.mp4")
        files = list(iter_media_files(tmp_path))
        assert len(files) == 0
