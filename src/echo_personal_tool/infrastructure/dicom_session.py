"""Thread-local DICOM session: open once, decode all frames."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pydicom

_thread_local = threading.local()


def get_thread_dicom_session() -> DicomSession:
    session = getattr(_thread_local, "dicom_session", None)
    if session is None:
        session = DicomSession()
        _thread_local.dicom_session = session
    return session


class DicomSession:
    def __init__(self) -> None:
        self._open_path: Path | None = None
        self._frames: np.ndarray | None = None

    @property
    def frame_count(self) -> int:
        if self._frames is None:
            return 0
        return int(self._frames.shape[0])

    def open(self, path: Path | str) -> None:
        resolved = Path(path).resolve()
        if self._open_path == resolved and self._frames is not None:
            return
        self.release()
        self._open_path = resolved

    def decode_all_frames(self) -> np.ndarray:
        if self._open_path is None:
            raise RuntimeError("DICOM is not open; call open() first")
        dataset = pydicom.dcmread(self._open_path, force=True)
        pixel_array = dataset.pixel_array
        self._frames = stack_pixel_array(pixel_array)
        return self._frames.copy()

    def read_frame(self, frame_index: int) -> np.ndarray:
        if self._frames is None:
            raise RuntimeError("Frames not decoded; call decode_all_frames() first")
        if frame_index < 0 or frame_index >= self._frames.shape[0]:
            raise IndexError(
                f"Frame index {frame_index} out of range [0, {self._frames.shape[0]})"
            )
        return np.ascontiguousarray(self._frames[frame_index]).copy()

    def release(self) -> None:
        self._open_path = None
        self._frames = None


def stack_pixel_array(pixel_array: np.ndarray) -> np.ndarray:
    """Normalize pydicom pixel_array to shape (N,H,W) or (N,H,W,C)."""
    arr = np.asarray(pixel_array)
    if arr.ndim == 2:
        return np.ascontiguousarray(arr[np.newaxis, ...])
    if arr.ndim == 3:
        if arr.shape[-1] in (3, 4):
            frames = arr[np.newaxis, ...]
        else:
            frames = arr
    elif arr.ndim == 4:
        frames = arr
    else:
        raise ValueError(f"Unsupported pixel_array ndim: {arr.ndim}")

    if frames.ndim == 4 and frames.shape[-1] == 4:
        frames = frames[..., :3]
    if frames.ndim == 4 and frames.shape[-1] not in (3,):
        raise ValueError(f"Expected color channels last in {frames.shape}")
    if frames.ndim not in (3, 4):
        raise ValueError(f"Expected (N,H,W) or (N,H,W,C) after normalization, got {frames.shape}")
    return np.ascontiguousarray(frames)
