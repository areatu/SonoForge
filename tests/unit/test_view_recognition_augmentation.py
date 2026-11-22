"""Tests for the A3C augmentation path in the view-recognition trainer."""

from __future__ import annotations

import random

import numpy as np
import pytest


def _augmentation_helpers():
    """Import the trainer lazily so collection works without ML extras.

    Skipping per test (rather than at module level) keeps the selected/executed
    test inventory in sync: a module-level skip emits an extra JUnit report.
    """
    pytest.importorskip("torch")
    pytest.importorskip("torchvision")
    from scripts.train_view_recognition import _augment_clip, _AugmentedClipsDataset

    return _augment_clip, _AugmentedClipsDataset


class _FakeBase:
    def __init__(self, views: list[str]) -> None:
        self._samples = [type("Sample", (), {"view": view})() for view in views]

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> tuple[np.ndarray, int]:
        return np.full((2, 8, 8), 0.5, dtype=np.float32), index


def test_augment_clip_preserves_shape_and_range() -> None:
    _augment_clip, _ = _augmentation_helpers()
    random.seed(7)
    clip = np.stack([np.full((24, 24), value / 10, dtype=np.float32) for value in range(1, 9)])

    augmented = _augment_clip(clip)

    assert augmented.shape == clip.shape
    assert augmented.min() >= 0.0
    assert augmented.max() <= 1.0
    assert not np.allclose(augmented, clip)


def test_augment_clip_frame_jitter_replaces_middle_frame(monkeypatch) -> None:
    _augment_clip, _ = _augmentation_helpers()
    clip = np.stack([np.full((16, 16), i / 8, dtype=np.float32) for i in range(8)])
    monkeypatch.setattr(random, "randint", lambda _low, _high: 1)
    monkeypatch.setattr(random, "uniform", lambda lo, _hi: 0.0 if lo <= 0.0 else 1.0)
    monkeypatch.setattr(random, "random", lambda: 1.0)

    augmented = _augment_clip(clip, frame_jitter=True)

    # Frame 1 (value 0.125) is moved to the middle slot by the swap.
    assert abs(float(augmented[4].mean()) - 0.125) < 0.02


def test_augmented_dataset_only_duplicates_requested_views() -> None:
    _, _AugmentedClipsDataset = _augmentation_helpers()
    base = _FakeBase(["A3C", "A4C", "A3C"])

    dataset = _AugmentedClipsDataset(base, ("A3C",), copies=2, frame_jitter=False)

    assert len(dataset) == 7  # 3 originals + 2 A3C clips * 2 copies
    assert [label for _, label in (dataset[i] for i in range(len(dataset)))] == [
        0,
        0,
        0,
        1,
        2,
        2,
        2,
    ]
