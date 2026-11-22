"""Unit tests for the view-recognition domain + dataset (no model required)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from echo_personal_tool.domain.models.view_recognition import (
    KNOWN_VIEWS,
    RecognizedView,
    ViewRecognitionManifest,
    ViewRecognitionSample,
    as_clip_array,
    clip_label_index,
    view_category,
)
from echo_personal_tool.domain.ports import IViewRecognizer
from echo_personal_tool.domain.services.view_recognition import ViewRecognitionService
from echo_personal_tool.infrastructure.view_recognition_dataset import (
    ViewRecognitionDataset,
    build_dicom_clip_provider,
    load_manifest,
    normalize_clip,
)


def test_recognized_view_properties() -> None:
    confident = RecognizedView("A4C", 0.91)
    assert confident.is_confident is True
    assert confident.category == "apical"

    weak = RecognizedView("PLAX", 0.4)
    assert weak.is_confident is False
    assert weak.category == "parasternal_long"

    assert RecognizedView("NOPE", 0.0).category == "unknown"


def test_view_category_covers_known_views() -> None:
    for view in KNOWN_VIEWS:
        assert view_category(view) != "unknown"


def test_clip_label_index_round_trip() -> None:
    assert clip_label_index("A4C", KNOWN_VIEWS) == 0
    assert clip_label_index("TEE", KNOWN_VIEWS) == len(KNOWN_VIEWS) - 1
    assert clip_label_index("UNSEEN", KNOWN_VIEWS) == -1


def test_as_clip_array_stacks_frames() -> None:
    frames = [np.full((3, 3), float(i)) for i in range(4)]
    clip = as_clip_array(frames)
    assert clip.shape == (4, 3, 3)
    assert clip[2, 0, 0] == 2.0


class StubRecognizer:
    """Minimal :class:`IViewRecognizer` for tests."""

    def __init__(self, view: str, confidence: float) -> None:
        self._view = view
        self._confidence = confidence

    def recognize(self, frames: Sequence[np.ndarray]) -> RecognizedView:
        return RecognizedView(self._view, self._confidence)


def test_view_recognition_service_returns_recognizer_result() -> None:
    recognizer: IViewRecognizer = StubRecognizer("A2C", 0.88)
    service = ViewRecognitionService(recognizer)
    result = service.recognize([np.zeros((8, 8))])
    assert result.view == "A2C"
    assert result.confidence == 0.88

    summary = service.describe([np.zeros((8, 8))])
    assert summary["view"] == "A2C"
    assert summary["confident"] is True
    assert summary["category"] == "apical"


def _sample_manifest() -> ViewRecognitionManifest:
    return ViewRecognitionManifest(
        samples=(
            ViewRecognitionSample("s1", "/a.dcm", "A4C", "train"),
            ViewRecognitionSample("s2", "/b.dcm", "PLAX", "train"),
            ViewRecognitionSample("s3", "/c.dcm", "A4C", "val"),
        )
    )


def test_manifest_round_trip() -> None:
    manifest = _sample_manifest()
    restored = ViewRecognitionManifest.from_dict(manifest.to_dict())
    assert restored == manifest
    assert restored.sample_ids_with_split("val") == ["s3"]
    assert restored.sample_ids_with_split("train") == ["s1", "s2"]


def test_dataset_uses_clip_provider_and_label() -> None:
    def provider(_: str) -> np.ndarray:
        return np.random.default_rng(0).random((8, 16, 16)).astype(np.float32)

    dataset = ViewRecognitionDataset(_sample_manifest(), provider, split="train")
    assert len(dataset) == 2
    clip, label = dataset[0]
    assert clip.shape == (8, 16, 16)
    assert label == clip_label_index("A4C", KNOWN_VIEWS)


def test_normalize_clip_scales_to_unit() -> None:
    clip = np.stack([np.full((2, 2), float(v)) for v in (0.0, 4.0, 8.0)])
    norm = normalize_clip(clip)
    assert norm.min() == 0.0
    assert norm.max() == 1.0


class FakeDicomReader:
    """Minimal :class:`IDicomReader` for tests."""

    def read_pixels(self, path: Path, frame_index: int = 0) -> np.ndarray:
        return np.full((4, 4), float(frame_index), dtype=np.float32)


def test_dicom_clip_provider_stacks_frames() -> None:
    provider = build_dicom_clip_provider(FakeDicomReader(), n_frames=3)
    clip = provider("/x.dcm")
    assert clip.shape == (3, 4, 4)
    assert clip[2, 0, 0] == 2.0


def test_dicom_clip_provider_samples_across_whole_clip() -> None:
    class MetadataReader(FakeDicomReader):
        def read_metadata(self, path: Path) -> SimpleNamespace:
            return SimpleNamespace(number_of_frames=9)

    provider = build_dicom_clip_provider(MetadataReader(), n_frames=3)
    clip = provider("/x.dcm")
    assert clip.shape == (3, 4, 4)
    assert [float(frame[0, 0]) for frame in clip] == [0.0, 4.0, 8.0]


def test_load_manifest_from_file(tmp_path: Path) -> None:
    manifest = _sample_manifest()
    path = tmp_path / "manifest.json"
    path.write_text(__import__("json").dumps(manifest.to_dict()), encoding="utf-8")
    loaded = load_manifest(path)
    assert loaded == manifest
