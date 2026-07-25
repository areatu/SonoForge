"""Tests for dicom_validator pre-parse validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from echo_personal_tool.infrastructure.dicom_validator import (
    InvalidDicomError,
    validate_dicom_header,
)


class TestValidateDicomHeader:
    def test_valid_dicom(self, tmp_path: Path) -> None:
        """A file with proper preamble + DICM magic should pass."""
        dcm = tmp_path / "valid.dcm"
        preamble = b"\x00" * 128
        dcm.write_bytes(preamble + b"DICM" + b"\x00" * 100)
        validate_dicom_header(dcm)

    def test_not_a_file(self, tmp_path: Path) -> None:
        dcm = tmp_path / "nonexistent.dcm"
        with pytest.raises(InvalidDicomError, match="Not a file"):
            validate_dicom_header(dcm)

    def test_file_too_small(self, tmp_path: Path) -> None:
        dcm = tmp_path / "tiny.dcm"
        dcm.write_bytes(b"\x00" * 10)
        with pytest.raises(InvalidDicomError, match="too small"):
            validate_dicom_header(dcm)

    def test_file_exactly_preamble_size_plus_4(self, tmp_path: Path) -> None:
        """132 bytes = 128 preamble + 4 magic = minimum valid size."""
        dcm = tmp_path / "min.dcm"
        dcm.write_bytes(b"\x00" * 128 + b"DICM")
        validate_dicom_header(dcm)

    def test_file_131_bytes_too_small(self, tmp_path: Path) -> None:
        dcm = tmp_path / "short.dcm"
        dcm.write_bytes(b"\x00" * 131)
        with pytest.raises(InvalidDicomError, match="too small"):
            validate_dicom_header(dcm)

    def test_file_exceeds_max_size(self, tmp_path: Path) -> None:
        dcm = tmp_path / "big.dcm"
        dcm.write_bytes(b"\x00" * 200)
        with pytest.raises(InvalidDicomError, match="exceeds"):
            validate_dicom_header(dcm, max_size_bytes=100)

    def test_missing_magic_bytes(self, tmp_path: Path) -> None:
        dcm = tmp_path / "bad_magic.dcm"
        dcm.write_bytes(b"\x00" * 128 + b"NOPE" + b"\x00" * 100)
        with pytest.raises(InvalidDicomError, match="Missing DICOM magic"):
            validate_dicom_header(dcm)

    def test_custom_max_size_bytes(self, tmp_path: Path) -> None:
        dcm = tmp_path / "mid.dcm"
        dcm.write_bytes(b"\x00" * 128 + b"DICM" + b"\x00" * 100)
        # 232 bytes, limit 300 → should pass
        validate_dicom_header(dcm, max_size_bytes=300)
        # 232 bytes, limit 200 → should fail
        with pytest.raises(InvalidDicomError, match="exceeds"):
            validate_dicom_header(dcm, max_size_bytes=200)

    def test_is_a_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "dir.dcm"
        d.mkdir()
        with pytest.raises(InvalidDicomError, match="Not a file"):
            validate_dicom_header(d)


class TestInvalidDicomError:
    def test_is_exception(self) -> None:
        assert issubclass(InvalidDicomError, Exception)

    def test_message_preserved(self) -> None:
        e = InvalidDicomError("test msg")
        assert str(e) == "test msg"
