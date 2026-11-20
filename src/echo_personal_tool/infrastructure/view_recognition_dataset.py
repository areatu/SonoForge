"""View-recognition dataset loading (infrastructure).

Loads a :class:`ViewRecognitionManifest` and turns it into an indexable dataset
of ``(clip, label)`` pairs. Frame decoding is injected as a ``ClipProvider`` so
the dataset is testable with synthetic clips and can be wired to DICOM / video
readers (see :func:`build_dicom_clip_provider`) without changing the core.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from echo_personal_tool.domain.models.view_recognition import (
    KNOWN_VIEWS,
    ViewRecognitionManifest,
    as_clip_array,
    clip_label_index,
)
from echo_personal_tool.domain.ports import IDicomReader

#: A callable that turns a source path into a stacked clip array.
ClipProvider = Callable[[str], np.ndarray]


def normalize_clip(clip: np.ndarray) -> np.ndarray:
    """Convert a clip to ``float32`` in ``[0, 1]`` for model input."""
    arr = np.asarray(clip, dtype=np.float32)
    if arr.size == 0:
        return arr
    lo = float(arr.min())
    hi = float(arr.max())
    if hi > lo:
        arr = (arr - lo) / (hi - lo)
    else:
        arr = np.zeros_like(arr)
    return arr


class ViewRecognitionDataset:
    """Indexable ``(clip, label)`` dataset built from a manifest."""

    def __init__(
        self,
        manifest: ViewRecognitionManifest,
        clip_provider: ClipProvider,
        *,
        views: Sequence[str] = KNOWN_VIEWS,
        split: str | None = None,
        normalize: bool = True,
    ) -> None:
        self._manifest = manifest
        self._provider = clip_provider
        self._views = tuple(views)
        self._normalize = normalize
        if split is None:
            self._samples = manifest.samples
        else:
            self._samples = tuple(s for s in manifest.samples if s.split == split)

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, idx: int) -> tuple[np.ndarray, int]:
        sample = self._samples[idx]
        clip = self._provider(sample.source_path)
        if self._normalize:
            clip = normalize_clip(clip)
        return clip, clip_label_index(sample.view, self._views)

    def clips(self) -> Iterator[tuple[np.ndarray, int]]:
        for i in range(len(self)):
            yield self[i]


def load_manifest(path: str | Path) -> ViewRecognitionManifest:
    """Read a manifest JSON file into a :class:`ViewRecognitionManifest`."""
    with Path(path).open(encoding="utf-8") as handle:
        data: dict[str, Any] = __import__("json").load(handle)
    return ViewRecognitionManifest.from_dict(data)


def build_dicom_clip_provider(reader: IDicomReader, *, n_frames: int = 8) -> ClipProvider:
    """Build a :data:`ClipProvider` that reads ``n_frames`` DICOM frames per clip."""

    def provider(source_path: str) -> np.ndarray:
        frames = [reader.read_pixels(Path(source_path), frame_index=i) for i in range(n_frames)]
        return as_clip_array(frames)

    return provider
