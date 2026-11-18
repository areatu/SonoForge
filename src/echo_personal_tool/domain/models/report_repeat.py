"""In-memory alternatives for one report parameter (or one ED/ES pair)."""

from __future__ import annotations

from dataclasses import dataclass

from echo_personal_tool.domain.models.value_origin import ClipSource


@dataclass(frozen=True)
class ReportCandidate:
    id: str
    parts: tuple[tuple[str, ClipSource], ...]
    #: Norm label and value of every reading of each part, in ``parts`` order.
    #: Selection never judges them — the report builder fills ``pathological``
    #: when it knows the patient's sex (2026-11-18 list, item 1).
    readings: tuple[tuple[tuple[str, float], ...], ...] = ()
    #: ``True`` when any recorded reading is outside its norm, ``False`` when
    #: all known readings are in norm, ``None`` when nothing could be judged.
    pathological: bool | None = None


@dataclass(frozen=True)
class ReportRepeat:
    key: str
    parameter_ids: tuple[str, ...]
    candidates: tuple[ReportCandidate, ...]
    #: Empty = follow the latest acquisition rather than pinning a measurement.
    override: str
    default_id: str
