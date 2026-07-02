"""OpenCV-based MP4 video reader with keyframe index and ring buffer."""

from __future__ import annotations

import bisect
import threading
from pathlib import Path

import cv2
import numpy as np

from echo_personal_tool.infrastructure.pixel_utils import to_bgr_uint8

RING_BUFFER_SIZE = 50
_KEYFRAME_SCAN_MAX_STEP = 120
_thread_local = threading.local()


def get_thread_video_reader() -> VideoReader:
    """Return a VideoReader cached on the current worker thread."""
    reader = getattr(_thread_local, "video_reader", None)
    if reader is None:
        reader = VideoReader()
        _thread_local.video_reader = reader
    return reader


class VideoReader:
    """Reads MP4 frames via OpenCV with keyframe-aware seek and ring buffer."""

    def __init__(self, buffer_size: int = RING_BUFFER_SIZE) -> None:
        self._buffer_size = buffer_size
        self._buffer: dict[int, np.ndarray] = {}
        self._buffer_order: list[int] = []
        self._capture: cv2.VideoCapture | None = None
        self._open_path: Path | None = None
        self._frame_count = 0
        self._fps = 0.0
        self._last_read_index: int | None = None
        self._keyframe_index: list[int] | None = None

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def keyframe_index(self) -> list[int]:
        self._ensure_keyframe_index()
        return list(self._keyframe_index or [0])

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
        self._keyframe_index = None

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

        self._seek_via_keyframe(index)
        return self.get_buffered_frame(index)

    def get_buffered_frame(self, index: int) -> np.ndarray:
        frame = self._buffer.get(index)
        if frame is None:
            raise KeyError(f"Frame {index} is not in the ring buffer")
        return frame

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self._open_path = None
        self._frame_count = 0
        self._fps = 0.0
        self._last_read_index = None
        self._keyframe_index = None
        self._buffer.clear()
        self._buffer_order.clear()

    def __enter__(self) -> VideoReader:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def _ensure_keyframe_index(self) -> None:
        if self._keyframe_index is not None:
            return
        self._keyframe_index = self._build_keyframe_index()

    def _build_keyframe_index(self) -> list[int]:
        if self._capture is None or self._frame_count <= 0:
            return [0]

        total = self._frame_count
        keyframes = [0]
        step = 1 if total <= _KEYFRAME_SCAN_MAX_STEP else max(1, total // 60)

        for candidate in range(step, total, step):
            if self._is_seekable_keyframe(candidate):
                keyframes.append(candidate)

        if total > 1 and keyframes[-1] != total - 1 and self._is_seekable_keyframe(total - 1):
            keyframes.append(total - 1)

        return sorted(set(keyframes))

    def _is_seekable_keyframe(self, index: int) -> bool:
        if self._capture is None:
            return False
        if not self._capture.set(cv2.CAP_PROP_POS_FRAMES, index):
            return False
        reported = int(self._capture.get(cv2.CAP_PROP_POS_FRAMES))
        if abs(reported - index) > 1:
            return False
        ok, _bgr = self._capture.read()
        if not ok:
            return False
        after = int(self._capture.get(cv2.CAP_PROP_POS_FRAMES))
        return after in (index + 1, index)

    def _nearest_keyframe(self, index: int) -> int:
        self._ensure_keyframe_index()
        keyframes = self._keyframe_index or [0]
        pos = bisect.bisect_right(keyframes, index) - 1
        return keyframes[max(0, pos)]

    def _seek_via_keyframe(self, index: int) -> None:
        if self._capture is None:
            raise RuntimeError("Video is not open; call open() first")
        keyframe = self._nearest_keyframe(index)
        if not self._capture.set(cv2.CAP_PROP_POS_FRAMES, keyframe):
            raise OSError(f"Failed to seek to keyframe {keyframe}")
        self._last_read_index = keyframe - 1
        while self._last_read_index < index:
            self._read_next_sequential(self._last_read_index + 1)

    def _read_next_sequential(self, index: int) -> np.ndarray:
        if self._capture is None:
            raise RuntimeError("Video is not open; call open() first")
        ok, bgr = self._capture.read()
        if not ok or bgr is None:
            raise OSError(f"Failed to read frame {index}")
        frame = to_bgr_uint8(bgr)
        self._store_in_buffer(index, frame)
        self._last_read_index = index
        return frame

    def _try_read_at_index(self, index: int) -> bool:
        if self._capture is None:
            return False
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, bgr = self._capture.read()
        if not ok or bgr is None:
            return False
        frame = to_bgr_uint8(bgr)
        self._store_in_buffer(index, frame)
        self._last_read_index = index
        return True

    def _store_in_buffer(self, index: int, frame: np.ndarray) -> None:
        if index in self._buffer:
            return
        self._buffer[index] = frame
        self._buffer_order.append(index)
        if len(self._buffer_order) > self._buffer_size:
            evict_idx = self._buffer_order.pop(0)
            self._buffer.pop(evict_idx, None)
