"""Unit tests for log_sanitizer (sanitize_uid, sanitize_path)."""

from __future__ import annotations

from pathlib import Path

from echo_personal_tool.infrastructure.log_sanitizer import sanitize_path, sanitize_uid


class TestSanitizeUid:
    def test_short_uid_unchanged(self) -> None:
        assert sanitize_uid("1.2.3") == "1.2.3"

    def test_exact_length(self) -> None:
        uid = "1.2.3.4.5.6.7.8"  # 16 chars
        assert sanitize_uid(uid) == uid

    def test_long_uid_truncated(self) -> None:
        uid = "1.2.3.4.5.6.7.8.9.10.11.12"
        result = sanitize_uid(uid)
        assert result.endswith("...")
        assert len(result) == 19  # 16 + "..."

    def test_custom_keep(self) -> None:
        uid = "1.2.3.4.5.6.7.8.9"
        result = sanitize_uid(uid, keep=5)
        assert result == "1.2.3..."

    def test_empty_string(self) -> None:
        assert sanitize_uid("") == ""


class TestSanitizePath:
    def test_returns_filename(self) -> None:
        assert sanitize_path(Path("/data/patient/scan.dcm")) == "scan.dcm"

    def test_no_path(self) -> None:
        assert sanitize_path(Path("file.dcm")) == "file.dcm"

    def test_deep_path(self) -> None:
        assert sanitize_path(Path("/a/b/c/d/e/f.txt")) == "f.txt"
