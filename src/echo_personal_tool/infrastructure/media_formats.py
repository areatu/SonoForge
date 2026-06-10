"""Media file extension detection for the local study scanner."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydicom.misc import is_dicom

MediaFormat = Literal["dicom", "mp4", "jpeg", "png"]

DICOM_EXTENSIONS = frozenset({".dcm", ".dicom"})
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
VIDEO_EXTENSIONS = frozenset({".mp4"})
SKIP_DIR_NAMES = frozenset({".git", ".idea", "__pycache__", "node_modules", ".venv", ".svn"})


def detect_media_format(path: Path) -> MediaFormat | None:
    """Return the media format for a file path, or None if unsupported."""
    ext = path.suffix.lower()
    if ext in DICOM_EXTENSIONS:
        return "dicom"
    if ext in VIDEO_EXTENSIONS:
        return "mp4"
    if ext in {".jpg", ".jpeg"}:
        return "jpeg"
    if ext == ".png":
        return "png"
    if ext == "" and path.is_file() and is_dicom(str(path)):
        return "dicom"
    return None


def is_media_file(path: Path) -> bool:
    return detect_media_format(path) is not None


def is_ignored_scan_path(path: Path) -> bool:
    """Skip version-control and IDE metadata directories during recursive scans."""
    return any(part in SKIP_DIR_NAMES for part in path.parts)
