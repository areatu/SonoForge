"""In-memory alternatives for one report parameter (or one ED/ES pair)."""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.models.value_origin import ClipSource


@dataclass(frozen=True)
class ReportCandidate:
    id: str
    parts: tuple[tuple[str, ClipSource], ...]


@dataclass(frozen=True)
class ReportRepeat:
    key: str
    parameter_ids: tuple[str, ...]
    candidates: tuple[ReportCandidate, ...]
    #: Empty = follow the latest acquisition rather than pinning a measurement.
    override: str
    default_id: str
