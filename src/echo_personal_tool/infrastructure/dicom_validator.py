"""Pre-parse DICOM file validation (fast header check)."""

from __future__ import annotations

import struct
from enum import Enum
from io import BytesIO
from pathlib import Path

import pydicom

from echo_personal_tool.infrastructure.dicom_uid_validator import validate_dicom_uid

_MAGIC = b"DICM"
_PREAMBLE_SIZE = 128
_MAGIC_OFFSET = _PREAMBLE_SIZE + 4

#: Raw datasets have no File Meta Information, so pydicom cannot know their
#: transfer syntax in advance. 64 KiB covers the normal element values before
#: the required identity tags while deferring anything unusually large.
_RAW_DEFER_BYTES = 64 * 1024
#: Recognition inspects only this prefix; a dataset whose identity tags sit
#: behind a larger private element is outside the deliberately bounded fallback.
_RAW_PROBE_BYTES = 1024 * 1024
_RAW_SPECIFIC_TAGS = (
    "SOPClassUID",
    "SOPInstanceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "Rows",
    "Columns",
)

DICOMDIR_SOP_CLASS_UID = "1.2.840.10008.1.3.10"
_STRUCTURED_REPORT_PREFIX = "1.2.840.10008.5.1.4.1.1.88."
_PRESENTATION_STATE_PREFIX = "1.2.840.10008.5.1.4.1.1.11."
_ENCAPSULATED_DOCUMENT_PREFIX = "1.2.840.10008.5.1.4.1.1.104."


class InvalidDicomError(Exception):
    """Raised when a file fails basic DICOM validation."""


class CorruptDicomError(InvalidDicomError):
    """The file claims to be DICOM but its structure or identity is unusable."""


class UnsupportedDicomError(InvalidDicomError):
    """The file is valid DICOM, but not a DICOM image instance the viewer can show."""


class DicomKind(str, Enum):
    """What a DICOM dataset represents, as far as the image viewer is concerned."""

    IMAGE = "image"
    DICOMDIR = "dicomdir"
    STRUCTURED_REPORT = "structured_report"
    PRESENTATION_STATE = "presentation_state"
    NON_IMAGE = "non_image"
    UNKNOWN = "unknown"

    @property
    def is_image(self) -> bool:
        return self is DicomKind.IMAGE

    @property
    def is_index(self) -> bool:
        return self is DicomKind.DICOMDIR


def _sop_class_uid(dataset: pydicom.Dataset) -> str:
    value = str(dataset.get("SOPClassUID", "") or "").strip()
    if value:
        return value
    file_meta = getattr(dataset, "file_meta", None)
    return str(getattr(file_meta, "MediaStorageSOPClassUID", "") or "").strip()


def classify_dicom_dataset(dataset: pydicom.Dataset) -> DicomKind:
    """Classify a parsed dataset without decoding pixels.

    DICOMDIR is an index, SR/PR are documents/state objects and encapsulated
    documents are not images at all. Treating those as corrupt pictures makes a
    valid folder look damaged; the scanner skips them and the pixel reader
    reports an unsupported kind.
    """
    sop_class = _sop_class_uid(dataset)
    if sop_class == DICOMDIR_SOP_CLASS_UID:
        return DicomKind.DICOMDIR
    if sop_class.startswith(_STRUCTURED_REPORT_PREFIX):
        return DicomKind.STRUCTURED_REPORT
    if sop_class.startswith(_PRESENTATION_STATE_PREFIX):
        return DicomKind.PRESENTATION_STATE
    if sop_class.startswith(_ENCAPSULATED_DOCUMENT_PREFIX):
        return DicomKind.NON_IMAGE
    if dataset.get("Rows") is not None and dataset.get("Columns") is not None:
        return DicomKind.IMAGE
    return DicomKind.UNKNOWN


def _validate_raw_dataset(path: Path) -> None:
    """Accept a dataset without the 128-byte Part 10 preamble on narrow terms.

    A raw dataset is recognised only when pydicom can read its header and it
    carries valid SOP Class/Instance UIDs plus the Study/Series identity (or the
    DICOMDIR SOP class). That is deliberately much stricter than the Part 10
    magic check: arbitrary binaries are not silently promoted to images.
    """
    try:
        with path.open("rb") as fh:
            probe = fh.read(_RAW_PROBE_BYTES)
        dataset = pydicom.dcmread(
            BytesIO(probe),
            stop_before_pixels=True,
            force=True,
            defer_size=_RAW_DEFER_BYTES,
            specific_tags=list(_RAW_SPECIFIC_TAGS),
        )
    except (pydicom.errors.InvalidDicomError, EOFError, OSError, ValueError, TypeError, struct.error) as exc:
        raise CorruptDicomError(f"Missing DICOM magic and unreadable raw dataset: {path.name}") from exc

    encoding = getattr(dataset, "original_encoding", None)
    if isinstance(encoding, tuple) and len(encoding) == 2 and encoding[1] is False:
        raise UnsupportedDicomError(f"Big-endian raw DICOM dataset is not supported: {path.name}")

    sop_class = _sop_class_uid(dataset)
    sop_instance = str(dataset.get("SOPInstanceUID", "") or "").strip()
    if not validate_dicom_uid(sop_class) or not validate_dicom_uid(sop_instance):
        raise CorruptDicomError(f"Missing DICOM magic and no valid SOP Class/Instance in raw dataset: {path.name}")

    kind = classify_dicom_dataset(dataset)
    if kind.is_index:
        return
    if kind is DicomKind.UNKNOWN:
        raise CorruptDicomError(f"Missing DICOM magic and no image dataset identity: {path.name}")
    study_uid = str(dataset.get("StudyInstanceUID", "") or "").strip()
    series_uid = str(dataset.get("SeriesInstanceUID", "") or "").strip()
    if not validate_dicom_uid(study_uid) or not validate_dicom_uid(series_uid):
        raise CorruptDicomError(f"Missing DICOM magic and no valid Study/Series UID in raw dataset: {path.name}")


def validate_dicom_header(
    path: Path,
    *,
    max_size_bytes: int | None = None,
) -> None:
    """Fast pre-parse validation before pydicom.dcmread.

    Checks: file exists, minimum size, and either DICOM Part 10 magic bytes or a
    narrowly recognised raw dataset (no 128-byte preamble). A study is never
    rejected for its size: long clinical loops (a minute of 512×512 at 30 fps is
    ~410 Mpx) are legitimate and must open. ``max_size_bytes`` stays as an
    optional guard for callers that explicitly want one; the application does
    not set it.
    Raises InvalidDicomError on failure.
    """
    if not path.is_file():
        raise InvalidDicomError(f"Not a file: {path}")

    size = path.stat().st_size
    if size < _MAGIC_OFFSET:
        raise InvalidDicomError(f"File too small for DICOM ({size} bytes): {path.name}")

    if max_size_bytes is not None and size > max_size_bytes:
        raise InvalidDicomError(f"File exceeds {max_size_bytes // 1_000_000} MB limit ({size} bytes): {path.name}")

    with path.open("rb") as fh:
        fh.seek(_PREAMBLE_SIZE)
        magic = fh.read(4)

    if magic == _MAGIC:
        return
    _validate_raw_dataset(path)
