"""Benchmarks for core operations.

Run with: pytest tests/benchmark/ --benchmark-json=results.json
"""

import numpy as np
import pytest


@pytest.fixture
def sample_frame():
    """Create a sample 640x480 grayscale frame."""
    return np.random.randint(0, 255, (480, 640), dtype=np.uint8)


@pytest.fixture
def sample_frame_bgr():
    """Create a sample 640x480 BGR frame."""
    return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)


class TestImageOps:
    """Benchmark basic image operations."""

    def test_grayscale_to_bgr(self, sample_frame, benchmark):
        import cv2

        benchmark(cv2.cvtColor, sample_frame, cv2.COLOR_GRAY2BGR)

    def test_rgb_to_bgr(self, sample_frame_bgr, benchmark):
        import cv2

        benchmark(cv2.cvtColor, sample_frame_bgr, cv2.COLOR_RGB2BGR)

    def test_resize(self, sample_frame_bgr, benchmark):
        import cv2

        benchmark(cv2.resize, sample_frame_bgr, (320, 240))

    def test_median_blur(self, sample_frame, benchmark):
        import cv2

        benchmark(cv2.medianBlur, sample_frame, 5)


class TestDicomParsing:
    """Benchmark DICOM metadata operations."""

    def test_parse_json(self, benchmark):
        import json

        data = {
            "PatientName": "Test^Patient",
            "StudyDate": "20240101",
            "Modality": "US",
            "SeriesDescription": "Test Series",
            "PixelSpacing": [0.5, 0.5],
            "FrameTime": 33.33,
        }
        benchmark(json.dumps, data)
