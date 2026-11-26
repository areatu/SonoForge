"""Persistent store for view-recognition decisions (#639 step 4).

One JSON document per study (``<study_uid>.json``) holding the persisted
:class:`~echo_personal_tool.domain.models.view_recognition.ViewDecision` of
every series the user has explicitly chosen a view for. Written atomically
(tmp + fsync + ``os.replace``) and refusing symlinks, mirroring the local
user store conventions.

The store is keyed by ``(study_uid, series_uid)``: re-loading the same series
of the same study restores the user's manual choice instead of re-running
the classifier.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from echo_personal_tool.domain.models.view_recognition import ViewDecision, ViewDecisionSource

_SAFE_UID = re.compile(r"[^A-Za-z0-9._-]+")


def _is_unsafe_link(path: Path) -> bool:
    try:
        return path.is_symlink() or (path.exists() and not path.is_file())
    except OSError:
        return True


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _safe_study_filename(study_uid: str) -> str:
    """Map a study UID to a filesystem-safe filename (keeps the UID readable)."""
    cleaned = _SAFE_UID.sub("_", str(study_uid).strip())
    return cleaned or "__default__"


class JsonViewDecisionStore:
    """JSON-file-backed :class:`IViewDecisionStore`.

    Each study owns one file with a ``decisions`` mapping
    ``series_uid -> decision dict``; a missing or unreadable file means
    "no decisions for this study" (never an error).
    """

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)

    @property
    def directory(self) -> Path:
        return self._dir

    def _study_path(self, study_uid: str) -> Path:
        return self._dir / f"{_safe_study_filename(study_uid)}.json"

    def _read_decisions(self, study_uid: str) -> dict[str, Any]:
        path = self._study_path(study_uid)
        if _is_unsafe_link(path):
            return {}
        try:
            raw = path.read_bytes()
        except OSError:
            return {}
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        decisions = data.get("decisions", {})
        return decisions if isinstance(decisions, dict) else {}

    def load(self, study_uid: str, series_uid: str) -> ViewDecision | None:
        raw = self._read_decisions(study_uid).get(series_uid)
        if not isinstance(raw, dict):
            return None
        try:
            return ViewDecision.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            return None

    def save(self, decision: ViewDecision) -> None:
        decisions = self._read_decisions(decision.study_uid)
        existing = decisions.get(decision.series_uid)
        if (
            decision.source is not ViewDecisionSource.MANUAL
            and isinstance(existing, dict)
            and existing.get("source", "manual") == ViewDecisionSource.MANUAL.value
        ):
            return
        decisions[decision.series_uid] = decision.to_dict()
        payload = json.dumps(
            {"schema_version": 1, "decisions": decisions},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        _atomic_write(self._study_path(decision.study_uid), payload)
