"""Tab session layer (Э9, PR-A): one open study set per tab, no UI.

A tab owns one set of studies (what the folder scanner or the server load
dialog returns today). The manager keeps the open tabs, the active one, and
the rules for parking an inactive tab (flush, save viewer state, release
decoded frames and thumbnails) and for closing it (purge its PACS cache
session unless another open tab still uses it).

Deliberately free of Qt widgets: the tab bar and the window only call into
this module. See docs/superpowers/specs/2026-10-07-tabs-start-page-spec-ru.md §3–§5.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from echo_personal_tool.domain.models.metadata import StudyMetadata

# Proposal from spec §4 (open question §10.1): 8 open tabs. Kept as a constant
# until the user confirms the limit; exceeding it is a UI question, not LRU.
MAX_OPEN_TABS = 8

TAB_ORIGIN_FOLDER = "folder"
TAB_ORIGIN_SERVER = "server"
TAB_ORIGIN_EMPTY = "empty"
TAB_ORIGINS = frozenset({TAB_ORIGIN_FOLDER, TAB_ORIGIN_SERVER, TAB_ORIGIN_EMPTY})


class TabSessionError(ValueError):
    """Base error for invalid tab operations."""


class TabLimitError(TabSessionError):
    """Raised when opening a tab would exceed ``max_tabs``."""


class TabCacheConflictError(TabSessionError):
    """Raised when two tabs would share one PACS cache session."""


class UnknownTabError(TabSessionError, KeyError):
    """Raised when a tab id is not open."""


@dataclass
class TabSession:
    """State of one open tab. Mutable: the viewer updates it while active."""

    tab_id: str
    origin: str
    root: str
    cache_session_id: str
    studies: list[StudyMetadata]
    active_instance_uid: str = ""
    frame_index: int = 0
    viewer_state_json: str = "{}"
    created_at: float = 0.0

    @property
    def clip_count(self) -> int:
        return sum(len(study.series) for study in self.studies)


def tab_title(tab: TabSession, position: int, *, empty_label: str, untitled_label: str) -> str:
    """Tab-bar caption: «N · дата · модальность · описание серии» (spec §2.3).

    No patient name: PHI in titles waits for the PHI policy (N-01).
    ``position`` is zero-based; the caption shows it one-based.
    """
    prefix = f"{position + 1}"
    if not tab.studies:
        return f"{prefix} · {empty_label}"
    study = min(tab.studies, key=lambda item: item.study_datetime)
    date = study.study_datetime.strftime("%d.%m.%Y")
    series = next((item for item in study.series if item.modality or item.description), None)
    if series is None:
        return f"{prefix} · {date} · {untitled_label}"
    description = series.description.strip()[:24] or untitled_label
    parts = [prefix, date, series.modality or "", description]
    return " · ".join(part for part in parts if part)


def encode_viewer_state(state: Mapping[str, Any]) -> str:
    """Serialize viewer state (W/L, calibrations, overlays) to a stable JSON string.

    Raises ``TabSessionError`` for values that are not JSON-serializable, so a
    bad value never reaches the stored tab.
    """
    try:
        return json.dumps(dict(state), sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TabSessionError(f"viewer state is not JSON-serializable: {exc}") from exc


def decode_viewer_state(text: str) -> dict[str, Any]:
    """Inverse of :func:`encode_viewer_state`.

    A corrupt or non-object payload yields an empty dict instead of raising:
    losing the saved view position must not block opening the tab.
    """
    if not text:
        return {}
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class CloseResult:
    closed: TabSession
    next_active_tab_id: str | None
    purge_cache_session_id: str  # "" when nothing must be deleted from Z3


class TabSessionManager:
    """Open tabs, their order, and the active tab. Not thread-safe: GUI thread only."""

    def __init__(
        self,
        *,
        max_tabs: int = MAX_OPEN_TABS,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        if max_tabs < 1:
            raise ValueError("max_tabs must be >= 1")
        self._max_tabs = max_tabs
        self._clock = clock
        self._id_factory = id_factory
        self._tabs: list[TabSession] = []
        self._active_id: str | None = None

    # ----- queries -------------------------------------------------------

    @property
    def max_tabs(self) -> int:
        return self._max_tabs

    @property
    def tabs(self) -> tuple[TabSession, ...]:
        return tuple(self._tabs)

    @property
    def active_tab_id(self) -> str | None:
        return self._active_id

    @property
    def active(self) -> TabSession | None:
        return self.get(self._active_id) if self._active_id is not None else None

    @property
    def is_full(self) -> bool:
        return len(self._tabs) >= self._max_tabs

    def __len__(self) -> int:
        return len(self._tabs)

    def __contains__(self, tab_id: object) -> bool:
        return any(tab.tab_id == tab_id for tab in self._tabs)

    def get(self, tab_id: str) -> TabSession:
        for tab in self._tabs:
            if tab.tab_id == tab_id:
                return tab
        raise UnknownTabError(tab_id)

    def index_of(self, tab_id: str) -> int:
        """Zero-based position in the tab bar (used for the «вкладка N» label)."""
        for position, tab in enumerate(self._tabs):
            if tab.tab_id == tab_id:
                return position
        raise UnknownTabError(tab_id)

    def owner_of_cache_session(self, cache_session_id: str) -> str | None:
        if not cache_session_id:
            return None
        for tab in self._tabs:
            if tab.cache_session_id == cache_session_id:
                return tab.tab_id
        return None

    # ----- mutations -----------------------------------------------------

    def open_tab(
        self,
        *,
        origin: str,
        root: str = "",
        cache_session_id: str = "",
        studies: list[StudyMetadata] | tuple[StudyMetadata, ...] = (),
        activate: bool = True,
    ) -> TabSession:
        self._validate_source(origin, root, cache_session_id)
        if self.is_full:
            raise TabLimitError(f"tab limit reached ({self._max_tabs})")
        if cache_session_id and self.owner_of_cache_session(cache_session_id):
            raise TabCacheConflictError(cache_session_id)

        tab = TabSession(
            tab_id=self._new_id(),
            origin=origin,
            root=root,
            cache_session_id=cache_session_id,
            studies=list(studies),
            created_at=float(self._clock()),
        )
        self._tabs.append(tab)
        if activate or self._active_id is None:
            self._active_id = tab.tab_id
        return tab

    def activate(self, tab_id: str) -> str | None:
        """Make ``tab_id`` active. Returns the previously active id (or None)."""
        self.get(tab_id)
        previous = self._active_id
        self._active_id = tab_id
        return previous

    def update_viewer(
        self,
        tab_id: str,
        *,
        active_instance_uid: str | None = None,
        frame_index: int | None = None,
        viewer_state: Mapping[str, Any] | None = None,
    ) -> TabSession:
        tab = self.get(tab_id)
        if active_instance_uid is not None:
            tab.active_instance_uid = active_instance_uid
        if frame_index is not None:
            if frame_index < 0:
                raise TabSessionError("frame_index must be >= 0")
            tab.frame_index = frame_index
        if viewer_state is not None:
            tab.viewer_state_json = encode_viewer_state(viewer_state)
        return tab

    def set_studies(self, tab_id: str, studies: list[StudyMetadata] | tuple[StudyMetadata, ...]) -> None:
        self.get(tab_id).studies = list(studies)

    def retarget_empty(
        self,
        tab_id: str,
        *,
        origin: str,
        root: str = "",
        cache_session_id: str = "",
    ) -> TabSession:
        """Give an empty tab (the « + » tab) the source of a new load.

        A tab that already holds studies is never retargeted: opening another
        study always gets its own tab (D-29).
        """
        tab = self.get(tab_id)
        if tab.studies:
            raise TabSessionError("only an empty tab can be retargeted")
        self._validate_source(origin, root, cache_session_id)
        if cache_session_id and self.owner_of_cache_session(cache_session_id) not in (None, tab_id):
            raise TabCacheConflictError(cache_session_id)
        tab.origin = origin
        tab.root = root
        tab.cache_session_id = cache_session_id
        return tab

    @staticmethod
    def _validate_source(origin: str, root: str, cache_session_id: str) -> None:
        if origin not in TAB_ORIGINS:
            raise TabSessionError(f"unknown tab origin: {origin!r}")
        if origin == TAB_ORIGIN_SERVER and root:
            raise TabSessionError("server tabs have no local root")
        if origin == TAB_ORIGIN_FOLDER and cache_session_id:
            raise TabSessionError("folder tabs have no PACS cache session")

    def close_tab(self, tab_id: str) -> CloseResult:
        position = self.index_of(tab_id)
        closed = self._tabs.pop(position)
        next_active: str | None = None
        if self._active_id == tab_id:
            if self._tabs:
                # Same as browsers: the tab that took the closed tab's place,
                # or the last one when the rightmost tab was closed.
                neighbour = self._tabs[min(position, len(self._tabs) - 1)]
                next_active = neighbour.tab_id
            self._active_id = next_active
        purge = ""
        if closed.cache_session_id and self.owner_of_cache_session(closed.cache_session_id) is None:
            purge = closed.cache_session_id
        return CloseResult(closed=closed, next_active_tab_id=next_active, purge_cache_session_id=purge)

    def _new_id(self) -> str:
        new_id = self._id_factory()
        if not new_id or any(tab.tab_id == new_id for tab in self._tabs):
            raise TabSessionError("id_factory returned an empty or duplicate id")
        return new_id


class _Flushable(Protocol):
    def __call__(self) -> None: ...


class _Clearable(Protocol):
    def clear(self) -> None: ...


class _Resettable(Protocol):
    def reset(self) -> None: ...


def release_decoded_resources(frame_cache: _Clearable | None, thumbnail_scheduler: _Resettable | None) -> None:
    """Free the RAM of an inactive tab (spec §5): decoded frames and thumbnail queue.

    Measurements, viewer state and PACS images (Z3) are not touched here.
    """
    if frame_cache is not None:
        frame_cache.clear()
    if thumbnail_scheduler is not None:
        thumbnail_scheduler.reset()


def park_tab(
    manager: TabSessionManager,
    tab_id: str,
    *,
    viewer_state: Mapping[str, Any],
    frame_index: int,
    active_instance_uid: str | None = None,
    flush_measurements: _Flushable | None = None,
    release: Callable[[], None] | None = None,
) -> TabSession:
    """Prepare an active tab for deactivation, in this order (spec §5):

    1. flush pending measurement writes (Z2-M is already on disk);
    2. save the viewer state into the tab;
    3. release decoded frames and thumbnails (``release``).

    The tab stays open; the PACS cache session stays in Z3 for the return trip.
    """
    if flush_measurements is not None:
        flush_measurements()
    tab = manager.update_viewer(
        tab_id,
        active_instance_uid=active_instance_uid,
        frame_index=frame_index,
        viewer_state=viewer_state,
    )
    if release is not None:
        release()
    return tab
