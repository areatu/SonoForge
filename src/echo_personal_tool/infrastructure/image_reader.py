"""OpenCV-based JPEG/PNG still image reader."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from echo_personal_tool.infrastructure.pixel_utils import to_bgr_uint8


class ImageReader:
    """Reads JPEG/PNG files and returns BGR or grayscale uint8 arrays."""

    def read_pixels(self, path: Path | str) -> np.ndarray:
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise OSError(f"Cannot read image: {path}")
        return to_bgr_uint8(bgr)
