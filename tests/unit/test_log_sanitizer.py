"""Tests for log_sanitizer PHI/PII protection utilities."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from echo_personal_tool.infrastructure.log_sanitizer import sanitize_path, sanitize_uid


class TestSanitizeUid:
    def test_short_uid_unchanged(self) -> None:
        uid = "1.2.3.4"
        assert sanitize_uid(uid) == uid

    def test_exact_keep_length_unchanged(self) -> None:
        uid = "1234567890123456"
        assert sanitize_uid(uid) == uid

    def test_long_uid_truncated(self) -> None:
        uid = "1.2.840.113619.2.55.3.1234567890"
        result = sanitize_uid(uid)
        assert result.endswith("...")
        assert len(result) == 19  # 16 + "..."

    def test_custom_keep_length(self) -> None:
        uid = "1234567890"
        result = sanitize_uid(uid, keep=5)
        assert result == "12345..."

    def test_empty_uid(self) -> None:
        assert sanitize_uid("") == ""

    def test_keep_zero_truncates_all(self) -> None:
        result = sanitize_uid("abcde", keep=0)
        assert result == "..."


class TestSanitizePath:
    def test_posix_path_returns_name(self) -> None:
        p = Path("/dicom/patient/study/image.dcm")
        assert sanitize_path(p) == "image.dcm"

    def test_pure_posix(self) -> None:
        p = PurePosixPath("/data/scans/scan001.dcm")
        assert sanitize_path(p) == "scan001.dcm"

    def test_pure_windows(self) -> None:
        p = PureWindowsPath("C:\\data\\scans\\scan001.dcm")
        assert sanitize_path(p) == "scan001.dcm"

    def test_no_parent(self) -> None:
        p = Path("file.dcm")
        assert sanitize_path(p) == "file.dcm"
