"""View-recognition domain model (pure, no Qt / no IO).

Defines the stable vocabulary of echocardiographic views, the recognition
result, and the dataset manifest used to train and evaluate a view
classifier. Everything here is importable from the domain layer so the
rest of the application can depend on it without pulling in infrastructure.

The manifest schema (step 4 design, #639) is versioned: v1 is the minimal
``PR-A`` shape (sample_id/source_path/view/split); v2 adds the per-sample
acquisition metadata (``ProtocolName`` / view-tag / vendor) and an explicit
``class_names`` order so a trained model's output index is pinned to a label
set. Old manifests keep loading through :meth:`ViewRecognitionManifest.from_dict`
with the v1 defaults filled in — training tooling built on v1 needs no rework.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

#: Canonic view identifiers the legacy v1/v2 7-class classifier emits.
#: ``UNKNOWN_VIEW`` is the fallback when the clip does not match a recognised view.
KNOWN_VIEWS: tuple[str, ...] = ("A4C", "A2C", "A3C", "PLAX", "SAX", "PSAX", "TEE")

#: Transthoracic standard view set including RV-focused apical 4-chamber and
#: subcostal windows (issue #688 / ML.0b).
TTE_STANDARD_VIEWS: tuple[str, ...] = (
    "PLAX",
    "PSAX",
    "A4C",
    "RV_A4C",
    "A2C",
    "A3C",
    "SUBCOSTAL",
)

#: Full superset of canonical echocardiographic views supported across v1/v2+
#: manifests and workflow routing.
EXTENDED_KNOWN_VIEWS: tuple[str, ...] = (
    "PLAX",
    "PSAX",
    "A4C",
    "RV_A4C",
    "A2C",
    "A3C",
    "SUBCOSTAL",
    "SAX",
    "TEE",
)
ALL_RECOGNIZABLE_VIEWS: frozenset[str] = frozenset(EXTENDED_KNOWN_VIEWS)
UNKNOWN_VIEW: str = "UNKNOWN"

#: Confidence at or above which a recognition result may be auto-applied
#: (suggest profile / view). Below this the UI should ask the user.
RECOGNITION_CONFIDENCE_THRESHOLD: float = 0.6

#: Current manifest schema. v1 = PR-A minimal shape; v2 adds acquisition
#: metadata and an explicit class-name order.
MANIFEST_SCHEMA_VERSION: int = 2

#: Splits a corpus may use. The split assignment is a label, not a constraint:
#: a manifest may omit ``test`` entirely, but the vocabulary stays closed so
#: the training tooling can validate assignments.
SPLIT_NAMES: tuple[str, ...] = ("train", "val", "test")

#: Coarse anatomical category for a view — used by the panel/profile filter
#: (step 4) and by reporting. Mapped explicitly so the set stays closed.
_VIEW_CATEGORY: dict[str, str] = {
    "A4C": "apical",
    "RV_A4C": "apical",
    "A2C": "apical",
    "A3C": "apical",
    "PLAX": "parasternal_long",
    "SAX": "parasternal_short",
    "PSAX": "parasternal_short",
    "SUBCOSTAL": "subcostal",
    "TEE": "tee",
    UNKNOWN_VIEW: "unknown",
}

#: Alias table mapping scanner-side view labels (DICOM ``ProtocolName``,
#: burned-in view tags, vendor spellings) onto the canonical vocabulary.
#: The keys are lower-cased at comparison time by :func:`canonicalize_view`.
#: Keeping the table closed means an unknown spelling degrades to
#: ``UNKNOWN_VIEW`` instead of silently inventing a class.
_VIEW_ALIASES: dict[str, frozenset[str]] = {
    "A4C": frozenset({"a4c", "ap4", "4ch", "4cv", "4c", "4-chamber", "four-chamber"}),
    "RV_A4C": frozenset(
        {
            "rv_a4c",
            "rva4c",
            "rv-a4c",
            "rv4c",
            "rv 4c",
            "rv_focused",
            "rv focused",
            "rv-focused",
            "rv focused a4c",
            "apical rv",
        }
    ),
    "A2C": frozenset({"a2c", "ap2", "2ch", "2cv", "2c", "2-chamber", "two-chamber"}),
    "A3C": frozenset({"a3c", "ap3", "3ch", "3cv", "3c", "3-chamber", "three-chamber"}),
    "PLAX": frozenset({"plax", "psla", "psax_l", "lvot", "parasternal_long", "parasternal long axis"}),
    "SAX": frozenset({"sax", "pssax", "short_axis", "short axis", "short-axis", "sa", "mid_sax"}),
    "PSAX": frozenset({"psax", "parasternal_short", "parasternal short axis", "parasternal-short"}),
    "SUBCOSTAL": frozenset({"subcostal", "sub-costal", "subxiphoid", "sc", "sc4c", "subcostal 4c"}),
    "TEE": frozenset({"tee", "tga", "transesophageal", "trans-esophageal"}),
}


def view_category(view: str) -> str:
    """Return the coarse anatomical category for ``view`` (``"unknown"`` default)."""
    return _VIEW_CATEGORY.get(view, "unknown")


def canonicalize_view(label: str) -> str:
    """Map a raw view label (``ProtocolName`` / view-tag / vendor spelling)
    to its canonical view id, or :data:`UNKNOWN_VIEW` when unrecognised.

    Comparison is case-insensitive and whitespace-tolerant; aliases are
    looked up in :data:`_VIEW_ALIASES` (including the canonical names
    themselves). This is the single normalisation point used by the dataset
    loader (so a corpus labelled with scanner spellings still trains against
    the canonical class order) and by the UI override path.
    """
    cleaned = " ".join(str(label).split()).lower()
    if not cleaned:
        return UNKNOWN_VIEW
    upper = cleaned.upper()
    if upper in ALL_RECOGNIZABLE_VIEWS:
        return upper
    for canonical, aliases in _VIEW_ALIASES.items():
        if cleaned in aliases:
            return canonical
    return UNKNOWN_VIEW


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
class ViewSampleMetadata:
    """Acquisition metadata of one labelled clip (manifest schema v2).

    Captured at labelling time so the corpus can be filtered and stratified
    by scanner protocol without re-reading the source files:

    * ``protocol_name`` — the scanner's DICOM ``ProtocolName`` (0018,1140)
      exactly as stored, before :func:`canonicalize_view` normalisation.
    * ``vendor`` — ultrasound system vendor (optional; free string).
    * ``view_tag`` — the burned-in / tag spelling the label was derived from
      (optional; may differ from ``protocol_name``).
    * ``acquisition_note`` — free-form labeller note (optional).
    """

    protocol_name: str = ""
    vendor: str = ""
    view_tag: str = ""
    acquisition_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_name": self.protocol_name,
            "vendor": self.vendor,
            "view_tag": self.view_tag,
            "acquisition_note": self.acquisition_note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ViewSampleMetadata:
        return cls(
            protocol_name=str(data.get("protocol_name", "")),
            vendor=str(data.get("vendor", "")),
            view_tag=str(data.get("view_tag", "")),
            acquisition_note=str(data.get("acquisition_note", "")),
        )


@dataclass(frozen=True)
class ViewRecognitionSample:
    """One labelled clip in a view-recognition corpus."""

    sample_id: str
    source_path: str
    view: str
    split: str = "train"
    metadata: ViewSampleMetadata | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "sample_id": self.sample_id,
            "source_path": self.source_path,
            "view": self.view,
            "split": self.split,
        }
        if self.metadata is not None:
            data["metadata"] = self.metadata.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ViewRecognitionSample:
        raw_meta = data.get("metadata")
        metadata = ViewSampleMetadata.from_dict(raw_meta) if isinstance(raw_meta, Mapping) else None
        return cls(
            sample_id=str(data["sample_id"]),
            source_path=str(data["source_path"]),
            view=str(data["view"]),
            split=str(data.get("split", "train")),
            metadata=metadata,
        )


@dataclass(frozen=True)
class ViewRecognitionManifest:
    """A corpus of labelled clips plus its train/val/test assignment.

    ``class_names`` pins the label order used by :func:`clip_label_index` and
    by the trained model's output index; it defaults to :data:`KNOWN_VIEWS`
    so v1 manifests (which carry no explicit order) stay compatible.
    """

    samples: tuple[ViewRecognitionSample, ...]
    schema_version: int = MANIFEST_SCHEMA_VERSION
    class_names: tuple[str, ...] = KNOWN_VIEWS

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "class_names": list(self.class_names),
            "samples": [s.to_dict() for s in self.samples],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ViewRecognitionManifest:
        raw = data.get("samples", [])
        version = int(data.get("schema_version", 1))
        raw_classes = data.get("class_names")
        class_names = tuple(str(v) for v in raw_classes) if raw_classes else KNOWN_VIEWS
        return cls(
            samples=tuple(ViewRecognitionSample.from_dict(s) for s in raw),
            schema_version=version,
            class_names=class_names,
        )

    def sample_ids_with_split(self, split: str) -> list[str]:
        return [s.sample_id for s in self.samples if s.split == split]


class ViewDecisionSource(Enum):
    """Where a persisted :class:`ViewDecision` came from."""

    AUTO = "auto"
    MANUAL = "manual"


@dataclass(frozen=True)
class ViewDecision:
    """A persisted view choice for one series of one study.

    ``source`` records whether the classifier or the user produced it; a
    restored manual decision keeps ``MANUAL`` so the UI never re-asks and
    the classifier result is not silently overridden on reload.
    """

    study_uid: str
    series_uid: str
    view: str
    source: ViewDecisionSource
    confidence: float
    profile_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_uid": self.study_uid,
            "series_uid": self.series_uid,
            "view": self.view,
            "source": self.source.value,
            "confidence": self.confidence,
            "profile_id": self.profile_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ViewDecision:
        return cls(
            study_uid=str(data["study_uid"]),
            series_uid=str(data["series_uid"]),
            view=str(data["view"]),
            source=ViewDecisionSource(str(data.get("source", "manual"))),
            confidence=float(data.get("confidence", 1.0)),
            profile_id=(str(data["profile_id"]) if data.get("profile_id") else None),
        )


def clip_label_index(view: str, views: Sequence[str] = KNOWN_VIEWS) -> int:
    """Map a view label to a class index, or ``-1`` when unknown."""
    index = {v: i for i, v in enumerate(views)}
    return index.get(view, -1)


def as_clip_array(frames: Sequence[np.ndarray]) -> np.ndarray:
    """Stack per-frame arrays into a single ``(N, H, W)`` or ``(N, H, W, C)`` clip."""
    if not frames:
        raise ValueError("cannot build a clip from zero frames")
    return np.stack([np.asarray(f) for f in frames], axis=0)
