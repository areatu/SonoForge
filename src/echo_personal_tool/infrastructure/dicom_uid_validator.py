"""DICOM UID validation for path safety."""

from __future__ import annotations

import re

_UID_PATTERN = re.compile(r"^[0-9](?:[0-9.]*[0-9])?$")


def validate_dicom_uid(uid: str) -> bool:
    """Validate DICOM UID per PS3.5 §6.1.

    Rules:
    - Must start and end with a digit (not a dot)
    - May contain digits and dots in between
    - Maximum 64 characters
    - Must not be empty
    """
    if len(uid) > 64 or len(uid) == 0:
        return False
    return bool(_UID_PATTERN.match(uid))


def safe_uid_path_component(uid: str) -> str:
    """Return safe path component from UID, raising ValueError if invalid."""
    if not validate_dicom_uid(uid):
        raise ValueError(f"Invalid DICOM UID: {uid!r}")
    return uid
