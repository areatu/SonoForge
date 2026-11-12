"""State of one Orthanc download batch.

The dialog used to keep the queue, the counters, the partial warnings and the
hand-off result as separate attributes.  That made "is a batch running and how
did it end?" a question that only the dialog could answer, and the download
coordinator had to read its private fields.  This object is the single owner of
that state; Qt objects (the worker, timers and widgets) stay in the dialog.

The state is deliberately not reset by :meth:`finish`: after a batch ends the
dialog still shows its counters and warnings in the result message until the
next batch starts with :meth:`start`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from echo_personal_tool.domain.models import StudyMetadata


@dataclass(frozen=True)
class DownloadBatchSnapshot:
    """Read-only view of a batch for callers outside the dialog."""

    active: bool
    background_requested: bool
    pending: int
    completed: int
    failed: int
    total: int
    saved: int
    downloaded_studies: tuple[StudyMetadata, ...]
    warnings: tuple[str, ...]
    result: tuple[str, str] | None


@dataclass
class DownloadBatch:
    """Queue, progress, outcome and partial warnings of one download."""

    active: bool = False
    background_requested: bool = False
    queue: list[tuple[str, list[str]]] = field(default_factory=list)
    completed: int = 0
    failed: int = 0
    total: int = 0
    warnings: list[str] = field(default_factory=list)
    downloaded_studies: list[StudyMetadata] = field(default_factory=list)
    result: tuple[str, str] | None = None

    def start(self, series: Sequence[tuple[str, list[str]]]) -> None:
        """Begin a fresh batch; a previous batch's counters never leak in."""

        self.active = True
        self.queue = list(series)
        self.completed = 0
        self.failed = 0
        self.total = len(series)
        self.warnings = []
        self.downloaded_studies = []
        self.result = None

    def finish(self) -> None:
        """Mark the batch as no longer running, keeping its outcome visible."""

        self.active = False

    def request_background(self) -> None:
        self.background_requested = True

    def next_item(self) -> tuple[str, list[str]]:
        """Take the next study; the caller has already checked ``queue``."""

        return self.queue.pop(0)

    def record_completed(self) -> None:
        self.completed += 1

    def record_failed(self) -> None:
        # A failed study still consumed its slot, so both counters move: the
        # number of successfully saved studies is ``completed - failed``.
        self.completed += 1
        self.failed += 1

    def add_studies(self, studies: Sequence[StudyMetadata]) -> None:
        self.downloaded_studies.extend(studies)

    def clear_studies(self) -> None:
        self.downloaded_studies = []

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def warning_text(self) -> str:
        """Join the per-instance warnings exactly as the final message shows them."""

        return "\n".join(self.warnings)

    def set_result(self, session_id: str, study_uid: str) -> None:
        self.result = (session_id, study_uid)

    @property
    def pending(self) -> int:
        return len(self.queue)

    @property
    def saved(self) -> int:
        return self.completed - self.failed

    @property
    def first_study_uid(self) -> str:
        return self.downloaded_studies[0].study_uid if self.downloaded_studies else ""

    def snapshot(self) -> DownloadBatchSnapshot:
        return DownloadBatchSnapshot(
            active=self.active,
            background_requested=self.background_requested,
            pending=self.pending,
            completed=self.completed,
            failed=self.failed,
            total=self.total,
            saved=self.saved,
            downloaded_studies=tuple(self.downloaded_studies),
            warnings=tuple(self.warnings),
            result=self.result,
        )


class DownloadBatchAttribute:
    """Compatibility alias from a former dialog field to the batch owner.

    Existing tests and small UI call sites historically wrote
    ``dialog._downloading`` and friends.  The alias keeps that spelling while
    the batch object remains the only place the value is stored.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:
            return self
        return getattr(instance.download_batch, self._name)

    def __set__(self, instance: Any, value: Any) -> None:
        setattr(instance.download_batch, self._name, value)
