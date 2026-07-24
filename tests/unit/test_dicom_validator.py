"""Unit tests for dicom_validator (validate_dicom_header)."""

from __future__ import annotations

import pytest

from echo_personal_tool.infrastructure.dicom_validator import (
    InvalidDicomError,
    validate_dicom_header,
)


class TestValidateDicomHeader:
    def test_valid_dicom(self, tmp_path) -> None:
        # 128 bytes preamble + 4 bytes DICM magic
        path = tmp_path / "test.dcm"
        path.write_bytes(b"\x00" * 128 + b"DICM")
        validate_dicom_header(path)  # no exception

    def test_file_not_found(self, tmp_path) -> None:
        path = tmp_path / "missing.dcm"
        with pytest.raises(InvalidDicomError, match="Not a file"):
            validate_dicom_header(path)

    def test_too_small(self, tmp_path) -> None:
        path = tmp_path / "tiny.dcm"
        path.write_bytes(b"\x00" * 10)
        with pytest.raises(InvalidDicomError, match="too small"):
            validate_dicom_header(path)

    def test_exact_minimum_size(self, tmp_path) -> None:
        # 128 + 4 = 132 bytes, but wrong magic
        path = tmp_path / "min.dcm"
        path.write_bytes(b"\x00" * 132)
        with pytest.raises(InvalidDicomError, match="Missing DICOM magic"):
            validate_dicom_header(path)

    def test_wrong_magic(self, tmp_path) -> None:
        path = tmp_path / "bad.dcm"
        path.write_bytes(b"\x00" * 128 + b"NONE")
        with pytest.raises(InvalidDicomError, match="Missing DICOM magic"):
            validate_dicom_header(path)

    def test_exceeds_max_size(self, tmp_path) -> None:
        path = tmp_path / "big.dcm"
        path.write_bytes(b"\x00" * 128 + b"DICM")
        with pytest.raises(InvalidDicomError, match="exceeds"):
            validate_dicom_header(path, max_size_bytes=100)

    def test_custom_max_size(self, tmp_path) -> None:
        path = tmp_path / "ok.dcm"
        path.write_bytes(b"\x00" * 128 + b"DICM")
        validate_dicom_header(path, max_size_bytes=200)  # no exception

    def test_invalid_dicom_error_is_exception(self) -> None:
        assert issubclass(InvalidDicomError, Exception)
