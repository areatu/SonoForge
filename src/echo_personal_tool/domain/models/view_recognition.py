"""View-recognition domain model (pure, no Qt / no IO).

Defines the stable vocabulary of echocardiographic views, the recognition
result, and the dataset manifest used to train and evaluate a view
classifier. Everything here is importable from the domain layer so the
rest of the application can depend on it without pulling in infrastructure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

#: Canonical view identifiers the classifier may emit. ``UNKNOWN_VIEW`` is the
#: fallback when the clip does not match a recognised view.
KNOWN_VIEWS: tuple[str, ...] = ("A4C", "A2C", "A3C", "PLAX", "SAX", "PSAX", "TEE")
UNKNOWN_VIEW: str = "UNKNOWN"

#: Confidence at or above which a recognition result may be auto-applied
#: (suggest profile / view). Below this the UI should ask the user.
RECOGNITION_CONFIDENCE_THRESHOLD: float = 0.6

#: Coarse anatomical category for a view — used by the panel/profile filter
#: (step 4) and by reporting. Mapped explicitly so the set stays closed.
_VIEW_CATEGORY: dict[str, str] = {
    "A4C": "apical",
    "A2C": "apical",
    "A3C": "apical",
    "PLAX": "parasternal_long",
    "SAX": "parasternal_short",
    "PSAX": "parasternal_short",
    "TEE": "tee",
    UNKNOWN_VIEW: "unknown",
}


def view_category(view: str) -> str:
    """Return the coarse anatomical category for ``view`` (``"unknown"`` default)."""
    return _VIEW_CATEGORY.get(view, "unknown")


@dataclass(frozen=True)
class RecognizedView:
    """Result of running a view classifier on a cine clip."""

    view: str
    confidence: float

    @property
    def is_confident(self) -> bool:
        """True when confidence meets :data:`RECOGNITION_CONFIDENCE_THRESHOLD`."""
        return float(self.confidence) >= RECOGNITION_CONFIDENCE_THRESHOLD

    @property
    def category(self) -> str:
        """Coarse anatomical category of the recognised view."""
        return view_category(self.view)


@dataclass(frozen=True)
class ViewRecognitionSample:
    """One labelled clip in a view-recognition corpus."""

    sample_id: str
    source_path: str
    view: str
    split: str = "train"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "source_path": self.source_path,
            "view": self.view,
            "split": self.split,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ViewRecognitionSample:
        return cls(
            sample_id=str(data["sample_id"]),
            source_path=str(data["source_path"]),
            view=str(data["view"]),
            split=str(data.get("split", "train")),
        )


@dataclass(frozen=True)
class ViewRecognitionManifest:
    """A corpus of labelled clips plus its train/val/test assignment."""

    samples: tuple[ViewRecognitionSample, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"samples": [s.to_dict() for s in self.samples]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ViewRecognitionManifest:
        raw = data.get("samples", [])
        return cls(samples=tuple(ViewRecognitionSample.from_dict(s) for s in raw))

    def sample_ids_with_split(self, split: str) -> list[str]:
        return [s.sample_id for s in self.samples if s.split == split]


def clip_label_index(view: str, views: Sequence[str] = KNOWN_VIEWS) -> int:
    """Map a view label to a class index, or ``-1`` when unknown."""
    index = {v: i for i, v in enumerate(views)}
    return index.get(view, -1)


def as_clip_array(frames: Sequence[np.ndarray]) -> np.ndarray:
    """Stack per-frame arrays into a single ``(N, H, W)`` or ``(N, H, W, C)`` clip."""
    if not frames:
        raise ValueError("cannot build a clip from zero frames")
    return np.stack([np.asarray(f) for f in frames], axis=0)
