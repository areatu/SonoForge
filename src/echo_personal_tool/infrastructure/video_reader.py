"""OpenCV-based MP4 video reader with a fixed-size frame ring buffer."""

from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np

from echo_personal_tool.infrastructure.pixel_utils import to_bgr_uint8

RING_BUFFER_SIZE = 50
_thread_local = threading.local()


def get_thread_video_reader() -> VideoReader:
    """Return a VideoReader cached on the current worker thread."""
    reader = getattr(_thread_local, "video_reader", None)
    if reader is None:
        reader = VideoReader()
        _thread_local.video_reader = reader
    return reader


class VideoReader:
    """Reads MP4 frames via OpenCV and caches the most recent frames in a ring buffer."""

    def __init__(self, buffer_size: int = RING_BUFFER_SIZE) -> None:
        self._buffer_size = buffer_size
        self._slots: list[tuple[int, np.ndarray] | None] = [None] * buffer_size
        self._write_pos = 0
        self._capture: cv2.VideoCapture | None = None
        self._open_path: Path | None = None
        self._frame_count = 0
        self._fps = 0.0
        self._last_read_index: int | None = None

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def fps(self) -> float:
        return self._fps

    def open(self, path: Path | str) -> None:
        resolved = Path(path).resolve()
        if self._capture is not None and self._open_path == resolved:
            return
        self.release()
        capture = cv2.VideoCapture(str(resolved))
        if not capture.isOpened():
            raise OSError(f"Cannot open video: {path}")
        self._capture = capture
        self._open_path = resolved
        self._frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self._fps = float(capture.get(cv2.CAP_PROP_FPS))

    def read_frame(self, index: int) -> np.ndarray:
        if self._capture is None:
            raise RuntimeError("Video is not open; call open() first")
        if index < 0 or index >= self._frame_count:
            raise IndexError(f"Frame index {index} out of range [0, {self._frame_count})")

        try:
            return self.get_buffered_frame(index)
        except KeyError:
            pass

        if self._last_read_index is not None and index == self._last_read_index + 1:
            return self._read_next_sequential(index)

        if self._try_read_at_index(index):
            return self.get_buffered_frame(index)

        if self._last_read_index is None or index <= self._last_read_index:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self._last_read_index = -1

        while self._last_read_index < index:
            self._read_next_sequential(self._last_read_index + 1)

        return self.get_buffered_frame(index)

    def get_buffered_frame(self, index: int) -> np.ndarray:
        for slot in self._slots:
            if slot is not None and slot[0] == index:
                return slot[1]
        raise KeyError(f"Frame {index} is not in the ring buffer")

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self._open_path = None
        self._frame_count = 0
        self._fps = 0.0
        self._last_read_index = None
        self._slots = [None] * self._buffer_size
        self._write_pos = 0

    def __enter__(self) -> VideoReader:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def _read_next_sequential(self, index: int) -> np.ndarray:
        ok, bgr = self._capture.read()
        if not ok or bgr is None:
            raise OSError(f"Failed to read frame {index}")
        frame = to_bgr_uint8(bgr)
        self._store_in_buffer(index, frame)
        self._last_read_index = index
        return frame

    def _try_read_at_index(self, index: int) -> bool:
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, bgr = self._capture.read()
        if not ok or bgr is None:
            return False
        frame = to_bgr_uint8(bgr)
        self._store_in_buffer(index, frame)
        self._last_read_index = index
        return True

    def _store_in_buffer(self, index: int, frame: np.ndarray) -> None:
        self._slots[self._write_pos] = (index, frame)
        self._write_pos = (self._write_pos + 1) % self._buffer_size
