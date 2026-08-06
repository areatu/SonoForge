"""Pre-parse DICOM file validation (fast header check)."""

from __future__ import annotations

from pathlib import Path

_MAGIC = b"DICM"
_PREAMBLE_SIZE = 128
_MAX_SIZE_BYTES = 500_000_000  # 500 MB


class InvalidDicomError(Exception):
    """Raised when a file fails basic DICOM validation."""


def validate_dicom_header(
    path: Path,
    *,
    max_size_bytes: int = _MAX_SIZE_BYTES,
) -> None:
    """Fast pre-parse validation before pydicom.dcmread.

    Checks: file exists, minimum size, DICOM magic bytes, max size limit.
    Raises InvalidDicomError on failure.
    """
    if not path.is_file():
        raise InvalidDicomError(f"Not a file: {path}")

    size = path.stat().st_size
    if size < _PREAMBLE_SIZE + 4:
        raise InvalidDicomError(f"File too small for DICOM ({size} bytes): {path.name}")

    if size > max_size_bytes:
        raise InvalidDicomError(f"File exceeds {max_size_bytes // 1_000_000} MB limit ({size} bytes): {path.name}")

    with path.open("rb") as fh:
        fh.seek(_PREAMBLE_SIZE)
        magic = fh.read(4)

    if magic != _MAGIC:
        raise InvalidDicomError(f"Missing DICOM magic bytes at offset 128: {path.name}")
