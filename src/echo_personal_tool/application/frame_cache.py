"""In-memory frame store for the active DICOM instance."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class FrameCache:
    source_path: Path | None = field(default=None, repr=False)
    frames: np.ndarray | None = field(default=None, repr=False)

    def is_ready(self, path: Path) -> bool:
        return (
            self.source_path is not None
            and self.frames is not None
            and self.source_path.resolve() == Path(path).resolve()
        )

    def load(self, path: Path, frames: np.ndarray) -> None:
        arr = np.ascontiguousarray(frames)
        if arr.ndim == 3:
            pass
        elif arr.ndim == 4 and arr.shape[-1] in (3, 4):
            pass
        else:
            raise ValueError(f"Expected frames shape (N,H,W) or (N,H,W,C), got {arr.shape}")
        self.source_path = Path(path).resolve()
        self.frames = arr

    def get(self, index: int) -> np.ndarray:
        if self.frames is None:
            raise RuntimeError("Frame cache is empty")
        if index < 0 or index >= self.frames.shape[0]:
            raise IndexError(
                f"Frame index {index} out of range [0, {self.frames.shape[0]})"
            )
        return np.ascontiguousarray(self.frames[index]).copy()

    def clear(self) -> None:
        self.source_path = None
        self.frames = None

    def frame_count(self) -> int:
        if self.frames is None:
            return 0
        return int(self.frames.shape[0])

    def memory_bytes(self) -> int:
        if self.frames is None:
            return 0
        return int(self.frames.nbytes)
