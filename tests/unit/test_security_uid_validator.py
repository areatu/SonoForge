"""Tests for DICOM UID validation security."""

from __future__ import annotations

import pytest

from echo_personal_tool.infrastructure.dicom_uid_validator import (
    safe_uid_path_component,
    validate_dicom_uid,
)


class TestValidateDicomUid:
    def test_valid_uid(self) -> None:
        assert validate_dicom_uid("1.2.840.113619.2.55.3.12345") is True

    def test_valid_uid_simple(self) -> None:
        assert validate_dicom_uid("12345") is True

    def test_empty_uid(self) -> None:
        assert validate_dicom_uid("") is False

    def test_uid_with_slash(self) -> None:
        assert validate_dicom_uid("1.2/../../../etc/passwd") is False

    def test_uid_with_dotdot(self) -> None:
        assert validate_dicom_uid("1.2../etc/passwd") is False

    def test_uid_with_letters(self) -> None:
        assert validate_dicom_uid("1.2.abc.123") is False

    def test_uid_with_special_chars(self) -> None:
        assert validate_dicom_uid("1.2!@#.123") is False

    def test_uid_with_spaces(self) -> None:
        assert validate_dicom_uid("1.2 3.4") is False


class TestSafeUidPathComponent:
    def test_valid_uid(self) -> None:
        result = safe_uid_path_component("1.2.840.113619.2.55.3.12345")
        assert result == "1.2.840.113619.2.55.3.12345"

    def test_invalid_uid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid DICOM UID"):
            safe_uid_path_component("1.2/../../../etc/passwd")

    def test_empty_uid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid DICOM UID"):
            safe_uid_path_component("")

    def test_uid_with_dots_only(self) -> None:
        result = safe_uid_path_component("1.2.3")
        assert result == "1.2.3"
