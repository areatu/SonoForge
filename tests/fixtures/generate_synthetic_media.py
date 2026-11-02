"""Generate synthetic JPEG/PNG/MP4 fixtures for unit tests."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


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
    path.parent.mkdir(parents=True, exist_ok=True)
    split_y = int(height * split_ratio)
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height), isColor=True)
    if not writer.isOpened():
        raise RuntimeError("Failed to open VideoWriter for composite cine MP4")
    try:
        for index in range(frame_count):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:split_y, :] = (90 + index, 100 + index, 110 + index)
            frame[split_y:, :] = (25, 25, 30)
            # faint ellipse in upper panel simulating LV cavity
            center = (width // 2, int(split_y * 0.55))
            axes = (int(width * 0.18), int(split_y * 0.35))
            cv2.ellipse(frame, center, axes, 0, 0, 360, (180, 180, 190), -1)
            writer.write(frame)
    finally:
        writer.release()


def write_synthetic_mp4(
    path: Path,
    *,
    frame_count: int = 10,
    width: int = 32,
    height: int = 24,
    fps: float = 25.0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height), isColor=True)
    if not writer.isOpened():
        raise RuntimeError("Failed to open VideoWriter for synthetic MP4")
    try:
        for index in range(frame_count):
            value = index % 256
            frame = np.full((height, width, 3), value, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


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
