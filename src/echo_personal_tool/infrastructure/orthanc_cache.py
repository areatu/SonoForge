"""Filesystem cache for DICOM instances downloaded from Orthanc."""

from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path

from echo_personal_tool.infrastructure.dicom_uid_validator import safe_uid_path_component

_DEFAULT_MAX_AGE_DAYS = 7


class OrthancSessionCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        (self._root / f"session-{session_id}").mkdir(parents=True, exist_ok=True)
        return session_id

    def save_instance(
        self,
        session_id: str,
        study_uid: str,
        series_uid: str,
        sop_uid: str,
        data: bytes,
    ) -> Path:
        # Validate UIDs to prevent path traversal
        safe_study = safe_uid_path_component(study_uid)
        safe_series = safe_uid_path_component(series_uid)
        safe_sop = safe_uid_path_component(sop_uid)
        path = self._root / f"session-{session_id}" / safe_study / safe_series / f"{safe_sop}.dcm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        # Set restrictive permissions (owner read/write only)
        os.chmod(path, 0o600)
        return path

    def study_path(self, session_id: str, study_uid: str) -> Path:
        return self._root / f"session-{session_id}" / study_uid

    def session_path(self, session_id: str) -> Path:
        return self._root / f"session-{session_id}"

    def clear_session(self, session_id: str) -> None:
        session_dir = self._root / f"session-{session_id}"
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)

    def clear_all(self) -> None:
        if not self._root.exists():
            return
        for entry in self._root.iterdir():
            if entry.is_dir() and entry.name.startswith("session-"):
                shutil.rmtree(entry, ignore_errors=True)

    def clear_stale(self, max_age_days: int = _DEFAULT_MAX_AGE_DAYS) -> int:
        """Remove session directories older than max_age_days.

        Returns the number of sessions removed.
        """
        if not self._root.exists():
            return 0
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        for entry in self._root.iterdir():
            if not entry.is_dir() or not entry.name.startswith("session-"):
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        return removed
