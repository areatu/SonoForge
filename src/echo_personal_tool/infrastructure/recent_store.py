"""Recently opened folders and pinned places (Э3).

The same store feeds the "Open folder" dialog sidebar and (later) the welcome
page, so the list must survive restarts and live next to the other user
preferences (portable builds keep them in the INI next to the executable).

Entries are stored as a single JSON value instead of a ``QStringList`` because
the pin flag travels with the path; the list itself is small (a handful of
folders), so reading it whole is cheaper than a second QSettings key.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

#: More entries would not fit the dialog without scrolling and stop being useful.
MAX_RECENT_FOLDERS = 15
_SETTINGS_KEY = "recent_folders"


@dataclass(frozen=True)
class RecentFolder:
    """One remembered folder.

    ``path`` is stored as the user typed/picked it (normalized), ``pinned``
    entries stay on top of the list and are never evicted by the limit.
    """

    path: str
    pinned: bool = False

    @property
    def exists(self) -> bool:
        try:
            return Path(self.path).is_dir()
        except OSError:
            return False


def normalize_folder(path: str | Path) -> str:
    """Canonical key for deduplication.

    Case is collapsed on Windows/macOS (the filesystems there are
    case-insensitive), separators are normalized everywhere.  The path is not
    resolved: a folder on a disconnected drive or a network share must keep its
    identity instead of turning into an unrelated local path.
    """
    text = str(path).strip()
    if not text:
        return ""
    text = os.path.normpath(os.path.expanduser(text))
    if sys.platform in ("win32", "darwin"):
        text = text.casefold()
    return text


def _settings_store() -> QSettings:
    from echo_personal_tool.infrastructure.user_preferences import _settings_store as store

    return store()


class RecentStore:
    """Recent folders with pin/remove/clear and a hard size limit."""

    def __init__(
        self,
        store: QSettings | None = None,
        *,
        limit: int = MAX_RECENT_FOLDERS,
        entries: list[RecentFolder] | None = None,
    ) -> None:
        self._store = store
        self._limit = max(1, int(limit))
        self._entries: list[RecentFolder] = list(entries) if entries is not None else self._load()

    # ── persistence ──────────────────────────────────────────────────

    def _store_object(self) -> QSettings:
        if self._store is None:
            self._store = _settings_store()
        return self._store

    def _load(self) -> list[RecentFolder]:
        raw = self._store_object().value(_SETTINGS_KEY, "")
        if not raw:
            return []
        try:
            payload = json.loads(str(raw))
        except (TypeError, ValueError):
            return []
        entries: list[RecentFolder] = []
        if not isinstance(payload, list):
            return []
        for item in payload:
            if isinstance(item, str) and item:
                entries.append(RecentFolder(path=item))
            elif isinstance(item, dict) and item.get("path"):
                entries.append(RecentFolder(path=str(item["path"]), pinned=bool(item.get("pinned"))))
        return entries

    def _save(self) -> None:
        payload = json.dumps(
            [{"path": entry.path, "pinned": entry.pinned} for entry in self._entries],
            ensure_ascii=False,
        )
        store = self._store_object()
        store.setValue(_SETTINGS_KEY, payload)
        store.sync()

    # ── reading ──────────────────────────────────────────────────────

    def entries(self) -> list[RecentFolder]:
        """Pinned entries first, then the rest in recency order."""
        return [entry for entry in self._entries if entry.pinned] + [
            entry for entry in self._entries if not entry.pinned
        ]

    def paths(self) -> list[str]:
        return [entry.path for entry in self.entries()]

    def is_pinned(self, path: str | Path) -> bool:
        key = normalize_folder(path)
        return any(entry.pinned and normalize_folder(entry.path) == key for entry in self._entries)

    def last_folder(self) -> str:
        """Most recent folder that still exists; empty when there is none."""
        for entry in self.entries():
            if entry.exists:
                return entry.path
        return ""

    # ── writing ──────────────────────────────────────────────────────

    def record(self, path: str | Path) -> None:
        """Remember ``path``; duplicates move to the front, pins are preserved."""
        text = str(path).strip()
        if not text:
            return
        key = normalize_folder(text)
        pinned = False
        rest: list[RecentFolder] = []
        for entry in self._entries:
            if normalize_folder(entry.path) == key:
                pinned = pinned or entry.pinned
                continue
            rest.append(entry)
        updated = [RecentFolder(path=text, pinned=pinned), *rest]
        trimmed = self._trimmed(updated)
        if trimmed == self._entries:
            return  # already the newest entry with unchanged pins: nothing to write
        self._entries = trimmed
        self._save()

    def set_pinned(self, path: str | Path, pinned: bool = True) -> None:
        key = normalize_folder(path)
        updated = [
            RecentFolder(path=entry.path, pinned=pinned) if normalize_folder(entry.path) == key else entry
            for entry in self._entries
        ]
        self._entries = updated
        self._save()

    def toggle_pinned(self, path: str | Path) -> bool:
        """Flip the pin flag and return the new state."""
        new_state = not self.is_pinned(path)
        self.set_pinned(path, new_state)
        return new_state

    def remove(self, path: str | Path) -> None:
        key = normalize_folder(path)
        self._entries = [entry for entry in self._entries if normalize_folder(entry.path) != key]
        self._save()

    def clear(self, *, keep_pinned: bool = False) -> None:
        """Forget the list; pinned entries stay unless asked otherwise."""
        self._entries = [entry for entry in self._entries if keep_pinned and entry.pinned]
        self._save()

    def _trimmed(self, entries: list[RecentFolder]) -> list[RecentFolder]:
        """Limit the unpinned tail; pinned entries are never dropped."""
        pinned = [entry for entry in entries if entry.pinned]
        unpinned = [entry for entry in entries if not entry.pinned]
        keep = max(0, self._limit - len(pinned))
        return [*pinned, *unpinned[:keep]]
