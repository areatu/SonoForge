"""Logging sanitization utilities for PHI/PII protection."""

from __future__ import annotations

from pathlib import Path


def sanitize_uid(uid: str, keep: int = 16) -> str:
    """Truncate DICOM UID for safe logging."""
    if len(uid) <= keep:
        return uid
    return uid[:keep] + "..."


def sanitize_path(path: Path) -> str:
    """Return only filename, not full path with potential PHI."""
    return path.name
