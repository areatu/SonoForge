"""Generate synthetic JPEG/PNG/MP4 fixtures for unit tests."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

FrameFactory = Callable[[int], np.ndarray]


def _open_writer(target: Path, fourcc_text: str, fps: float, width: int, height: int) -> cv2.VideoWriter | None:
    fourcc = cv2.VideoWriter_fourcc(*fourcc_text)
    writer = cv2.VideoWriter(str(target), fourcc, fps, (width, height), isColor=True)
    if not writer.isOpened():
        writer.release()
        return None
    return writer


def _roundtrips_exactly(path: Path, make_frame: FrameFactory, last_index: int) -> bool:
    """Re-read first and last frame; a writer that shifts values must not ship.

    The two frames cover the two regressions seen in the wild: a value/colour
    shift (MJPG quantisation) moves both, an encoder delay duplicates the
    leading frame and drops the trailing one.
    """
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return False
    try:
        for index in dict.fromkeys((0, last_index)):
            if index and not capture.set(cv2.CAP_PROP_POS_FRAMES, float(index)):
                return False
            ok, frame = capture.read()
            if not ok or frame is None or not (frame == make_frame(index)).all():
                return False
        return True
    finally:
        capture.release()


def _write_synthetic_video(
    path: Path,
    *,
    frame_count: int,
    width: int,
    height: int,
    fps: float,
    make_frame: FrameFactory,
) -> None:
    """Write ``make_frame(0..frame_count - 1)`` losslessly, MJPG as last resort.

    The reader tests assert exact pixel values (a frame's value *is* its
    identity in the cache), so the fixture has to round-trip bit-exactly.
    OpenCV >= 4.14 quantises MJPG enough to shift dark solid frames by 1–2
    levels, and OpenCV 5's ``.mp4`` fallback to mp4v adds an encoder delay
    that duplicates the leading frames (CI run 41549459474: all seven
    video/session failures were ``int(frame[0, 0, 0])`` off by exactly that
    shift). FFV1 in an AVI container is lossless in every wheel under test;
    ``cv2.VideoCapture`` probes content rather than the extension, so the AVI
    is renamed to the requested ``clip.mp4``-style path afterwards and every
    downstream consumer (scanner, metadata mapper, workers) still sees the
    file name it expects. Backends without FFV1 keep the historical MJPG
    write unchanged.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lossless = path.with_name(path.name + ".ffv1.avi")
    try:
        writer = _open_writer(lossless, "FFV1", fps, width, height)
        if writer is not None:
            try:
                for index in range(frame_count):
                    writer.write(make_frame(index))
            finally:
                writer.release()
            if _roundtrips_exactly(lossless, make_frame, frame_count - 1):
                os.replace(lossless, path)
                return
    finally:
        lossless.unlink(missing_ok=True)

    writer = _open_writer(path, "MJPG", fps, width, height)
    if writer is None:
        raise RuntimeError(f"Failed to open VideoWriter for synthetic clip: {path}")
    try:
        for index in range(frame_count):
            writer.write(make_frame(index))
    finally:
        writer.release()


def write_synthetic_composite_cine_mp4(
    path: Path,
    *,
    frame_count: int = 4,
    width: int = 800,
    height: int = 600,
    fps: float = 25.0,
    split_ratio: float = 0.62,
) -> None:
    """MP4 with bright upper B-mode strip and darker lower Doppler-like band."""
    split_y = int(height * split_ratio)

    def make_frame(index: int) -> np.ndarray:
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:split_y, :] = (90 + index, 100 + index, 110 + index)
        frame[split_y:, :] = (25, 25, 30)
        # faint ellipse in upper panel simulating LV cavity
        center = (width // 2, int(split_y * 0.55))
        axes = (int(width * 0.18), int(split_y * 0.35))
        cv2.ellipse(frame, center, axes, 0, 0, 360, (180, 180, 190), -1)
        return frame

    _write_synthetic_video(
        path,
        frame_count=frame_count,
        width=width,
        height=height,
        fps=fps,
        make_frame=make_frame,
    )


def write_synthetic_mp4(
    path: Path,
    *,
    frame_count: int = 10,
    width: int = 32,
    height: int = 24,
    fps: float = 25.0,
) -> None:
    def make_frame(index: int) -> np.ndarray:
        return np.full((height, width, 3), index % 256, dtype=np.uint8)

    _write_synthetic_video(
        path,
        frame_count=frame_count,
        width=width,
        height=height,
        fps=fps,
        make_frame=make_frame,
    )


def write_synthetic_jpeg(
    path: Path,
    *,
    width: int = 48,
    height: int = 36,
    value: int = 128,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = np.full((height, width, 3), value, dtype=np.uint8)
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"Failed to write synthetic JPEG: {path}")


def write_synthetic_png(path: Path, *, width: int = 48, height: int = 36, value: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = np.full((height, width, 3), value, dtype=np.uint8)
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"Failed to write synthetic PNG: {path}")
