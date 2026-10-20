"""Local library of user report phrases (UI-4 PR-3, spec §4.6, UQ-08).

User phrases live next to the other per-user data in a small JSON file; the
same document is the import/export format, so sending one's phrase library to
another workstation is a file copy.  Built-in phrases are not stored — they
ship with the application and are merged in by the column.

The store is deliberately forgiving on read: a missing, unreadable or corrupt
file yields an empty library instead of blocking the report, because a lost
phrase list must never cost a study.  Writes are atomic (temporary file plus
``os.replace``) and are the only place errors escape, so the UI can tell the
physician that the file was not saved.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from echo_personal_tool.domain.services.report_phrases import (
    MAX_USER_PHRASES,
    PhraseDocument,
    PhraseDocumentError,
    ReportPhrase,
    dumped_document,
    make_user_phrase,
    parse_phrase_document,
)
from echo_personal_tool.infrastructure.paths import report_phrases_file

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportResult:
    """What an import changed: added rows, duplicates and unusable entries."""

    added: int = 0
    duplicates: int = 0
    skipped: int = 0


def write_phrase_document(path: Path, phrases: tuple[ReportPhrase, ...]) -> int:
    """Atomically write an export document; return the number of phrases.

    ``OSError`` propagates: the caller decides how to tell the user that the
    file was not written.  A partly written file is never left behind.
    """
    text = dumped_document(phrases)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
    return len(phrases)


class PhraseStore:
    """User phrases of one workstation, persisted as the export document.

    ``path`` defaults to :func:`report_phrases_file` (the canonical per-user
    data directory, portable profile included).  Tests and tools pass an
    explicit path, which keeps the real library untouched.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else report_phrases_file()
        self._phrases: tuple[ReportPhrase, ...] | None = None

    @property
    def path(self) -> Path:
        return self._path

    # ── reading ──────────────────────────────────────────────────────

    def phrases(self) -> tuple[ReportPhrase, ...]:
        """The stored phrases, read once per store instance."""
        if self._phrases is None:
            self._phrases = self._read()
        return self._phrases

    def reload(self) -> tuple[ReportPhrase, ...]:
        """Drop the cache and read the file again (used after an import)."""
        self._phrases = None
        return self.phrases()

    def _read(self) -> tuple[ReportPhrase, ...]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ()
        except OSError as exc:
            logger.warning("report phrases: cannot read %s (%s)", self._path, type(exc).__name__)
            return ()
        try:
            return parse_phrase_document(text).phrases
        except PhraseDocumentError:
            logger.warning("report phrases: %s is not a phrase document; keeping the built-in set", self._path)
            return ()

    # ── editing ──────────────────────────────────────────────────────

    def add(self, section: object, ru: object, en: object) -> ReportPhrase | None:
        """Add a phrase and persist it; ``None`` when unusable, a duplicate or full.

        A write failure propagates as ``OSError`` — the caller shows it, but
        the in-memory list only changes after the file was replaced.
        """
        phrase = make_user_phrase(section, ru, en)
        if phrase is None:
            return None
        current = self.phrases()
        if any(existing.id == phrase.id for existing in current):
            return None
        if len(current) >= MAX_USER_PHRASES:
            return None
        self._write(current + (phrase,))
        return phrase

    def remove(self, phrase_id: str) -> bool:
        """Delete one phrase by id; ``False`` when the id is unknown."""
        current = self.phrases()
        remaining = tuple(phrase for phrase in current if phrase.id != phrase_id)
        if len(remaining) == len(current):
            return False
        self._write(remaining)
        return True

    def import_file(self, path: Path) -> ImportResult:
        """Merge another library into this one.

        ``PhraseDocumentError`` marks a file that is not a phrase document;
        ``OSError`` an unreadable one.  Entries already present are counted as
        duplicates, broken ones and entries beyond the limit as skipped.
        """
        text = Path(path).read_text(encoding="utf-8")
        document: PhraseDocument = parse_phrase_document(text)
        current = self.phrases()
        known = {phrase.id for phrase in current}
        added: list[ReportPhrase] = []
        duplicates = 0
        skipped = document.skipped
        for phrase in document.phrases:
            if phrase.id in known:
                duplicates += 1
                continue
            if len(current) + len(added) >= MAX_USER_PHRASES:
                skipped += 1
                continue
            added.append(phrase)
        if added:
            self._write(current + tuple(added))
        return ImportResult(added=len(added), duplicates=duplicates, skipped=skipped)

    def export_file(self, path: Path) -> int:
        """Write the current library as an import document; return its size."""
        return write_phrase_document(path, self.phrases())

    # ── persistence ──────────────────────────────────────────────────

    def _write(self, phrases: tuple[ReportPhrase, ...]) -> None:
        write_phrase_document(self._path, phrases)
        self._phrases = tuple(phrases)
