"""Local measurement archive contracts. Pixels may contain burned-in PHI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


class ArchiveWriteError(Exception):
    """Safe archive boundary failure; never includes patient data."""


@dataclass(frozen=True)
class ArchiveContext:
    patient_key: str
    study_key: str
    series_key: str
    instance_key: str
    app_version: str
    pixel_spacing_mm: tuple[float, float] | None = None
    measurement_key: str = ""
    patient_identity_known: bool = True


@dataclass(frozen=True)
class ArchiveSample:
    """One partial annotation. Unlisted structures are UNKNOWN, not negatives."""

    sample_id: str
    metadata: dict[str, object]
    pixels: np.ndarray


@dataclass(frozen=True)
class ArchiveDecision:
    """Pixel-free receipt identifying the exact saved material, not a live frame."""

    sample_id: str
    fingerprint: str
    chamber: str
    phase: str
    frame_index: int


class MeasurementArchive(Protocol):
    def token(self, kind: str, value: str) -> str: ...
    def save(self, sample: ArchiveSample) -> bool: ...
    def exclude_missing(self, instance_key: str, retained_ids: set[str]) -> None: ...
    def exclude_study(self, study_key: str) -> None: ...
    def reject_sample(self, decision: ArchiveDecision) -> bool: ...
