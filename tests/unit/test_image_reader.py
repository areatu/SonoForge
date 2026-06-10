"""Unit tests for ImageReader."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.infrastructure.image_reader import ImageReader
from tests.fixtures.generate_synthetic_media import write_synthetic_jpeg, write_synthetic_png


def test_read_jpeg_returns_color_bgr_uint8(tmp_path: Path) -> None:
    path = tmp_path / "still.jpg"
    write_synthetic_jpeg(path, value=200)

    pixels = ImageReader().read_pixels(path)

    assert pixels.shape == (36, 48, 3)
    assert pixels.dtype == np.uint8
    assert int(pixels[0, 0, 0]) == 200


def test_read_png_returns_color_bgr_uint8(tmp_path: Path) -> None:
    path = tmp_path / "still.png"
    write_synthetic_png(path, value=90)

    pixels = ImageReader().read_pixels(path)

    assert pixels.shape == (36, 48, 3)
    assert int(pixels[0, 0, 0]) == 90


def test_read_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="Cannot read image"):
        ImageReader().read_pixels(tmp_path / "missing.jpg")
