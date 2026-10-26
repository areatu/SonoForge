"""Application facade for the recent-folder preference store.

Presentation can display and update recent places without depending on the
Qt-backed QSettings adapter. The adapter is created lazily so importing this
application API never imports Qt.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast


class RecentFolderEntry(Protocol):
    """Read-only folder data shown by the welcome page and folder dialog."""

    @property
    def path(self) -> str: ...

    @property
    def pinned(self) -> bool: ...

    @property
    def exists(self) -> bool: ...


class RecentFolderStore(Protocol):
    """Application-facing operations for a user's recent-folder history."""

    @property
    def enabled(self) -> bool: ...

    def entries(self) -> Sequence[RecentFolderEntry]: ...

    def last_folder(self) -> str: ...

    def reload(self) -> None: ...

    def record(self, path: str | Path) -> None: ...

    def is_pinned(self, path: str | Path) -> bool: ...

    def toggle_pinned(self, path: str | Path) -> bool: ...

    def remove(self, path: str | Path) -> None: ...

    def clear(self, *, keep_pinned: bool = False) -> None: ...


def make_recent_folder_store(*, enabled: bool | None = None) -> RecentFolderStore:
    """Create the profile-aware QSettings adapter behind the application API."""
    from echo_personal_tool.infrastructure.recent_store import RecentStore as RecentStoreAdapter

    return cast(RecentFolderStore, RecentStoreAdapter(enabled=enabled))


__all__ = ["RecentFolderEntry", "RecentFolderStore", "make_recent_folder_store"]
