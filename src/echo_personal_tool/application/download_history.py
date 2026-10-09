"""In-memory history of PACS downloads for the current run (Э9, PR-C).

The start page (PR-D) lists «Недавние исследования» from this history. It holds
metadata only: no file paths, no patient name (PHI, N-01), and nothing is
written to disk, so the list is empty after a restart, as the spec requires.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from echo_personal_tool.domain.models.metadata import StudyMetadata


@dataclass(frozen=True)
class DownloadRecord:
    study_uid: str
    study_datetime: datetime
    modality: str
    description: str
    clip_count: int
    downloaded_at: float


class DownloadHistory:
    """Newest first, unique by study UID, bounded by ``limit``."""

    def __init__(self, *, limit: int = 50, clock: Callable[[], float] = time.time) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self._limit = limit
        self._clock = clock
        self._records: list[DownloadRecord] = []

    def record(self, study: StudyMetadata) -> DownloadRecord:
        series = next((item for item in study.series if item.modality or item.description), None)
        entry = DownloadRecord(
            study_uid=study.study_uid,
            study_datetime=study.study_datetime,
            modality=(series.modality if series else "") or "",
            description=((series.description if series else "") or "").strip()[:64],
            clip_count=sum(len(item.instances) for item in study.series),
            downloaded_at=float(self._clock()),
        )
        self._records = [item for item in self._records if item.study_uid != study.study_uid]
        self._records.insert(0, entry)
        del self._records[self._limit :]
        return entry

    def records(self) -> tuple[DownloadRecord, ...]:
        return tuple(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def clear(self) -> None:
        self._records.clear()
