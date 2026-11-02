"""In-memory history of PACS downloads for the current Full-profile run.

The Full start page may list «Недавние исследования» from this history. It
holds metadata only and writes nothing to disk, so the list is empty after a
restart. Records remain identifier-free apart from study UID; a separate,
bounded RAM-only surname lookup serves the opt-in start-page privacy setting. Presenter disables the
history entirely through the profile capability matrix.
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

    def __init__(
        self,
        *,
        limit: int = 50,
        clock: Callable[[], float] = time.time,
        enabled: bool | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if enabled is None:
            from echo_personal_tool.infrastructure.profile import has_recent_studies

            enabled = has_recent_studies()
        self._enabled = bool(enabled)
        self._limit = limit
        self._clock = clock
        self._records: list[DownloadRecord] = []
        self._patient_surnames: dict[str, str] = {}

    def record(self, study: StudyMetadata) -> DownloadRecord | None:
        if not self._enabled:
            return None
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
        surnames = {
            instance.patient_surname
            for series in study.series
            for instance in series.instances
            if instance.patient_surname
        }
        self._patient_surnames[study.study_uid] = surnames.pop() if len(surnames) == 1 else ""
        retained = {record.study_uid for record in self._records}
        self._patient_surnames = {uid: name for uid, name in self._patient_surnames.items() if uid in retained}
        return entry

    def patient_surname(self, study_uid: str) -> str:
        """Opt-in UI projection only; never persisted or included in record reprs."""
        return self._patient_surnames.get(study_uid, "")

    def records(self) -> tuple[DownloadRecord, ...]:
        return tuple(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def clear(self) -> None:
        self._records.clear()
        self._patient_surnames.clear()
