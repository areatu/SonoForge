"""Application facade for the per-user report phrase library.

Presentation consumes the phrase-store contract below; the JSON file adapter
and atomic persistence remain in infrastructure. The adapter is loaded only
when a store is requested, keeping this module Qt-free and cheap to import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from echo_personal_tool.domain.services.report_phrases import ReportPhrase


class PhraseImportSummary(Protocol):
    """Read-only outcome of merging an imported phrase document."""

    @property
    def added(self) -> int: ...

    @property
    def duplicates(self) -> int: ...

    @property
    def skipped(self) -> int: ...


class ReportPhraseStore(Protocol):
    """Application-facing persistence operations for user-authored phrases."""

    @property
    def path(self) -> Path: ...

    def phrases(self) -> tuple[ReportPhrase, ...]: ...

    def reload(self) -> tuple[ReportPhrase, ...]: ...

    def add(self, section: object, ru: object, en: object) -> ReportPhrase | None: ...

    def remove(self, phrase_id: str) -> bool: ...

    def import_file(self, path: Path) -> PhraseImportSummary: ...

    def export_file(self, path: Path) -> int: ...


def make_report_phrase_store(path: Path | None = None) -> ReportPhraseStore:
    """Create the local JSON phrase store behind the application API."""
    from echo_personal_tool.infrastructure.report_phrase_store import PhraseStore as PhraseStoreAdapter

    return cast(ReportPhraseStore, PhraseStoreAdapter(path))


__all__ = ["PhraseImportSummary", "ReportPhraseStore", "make_report_phrase_store"]
