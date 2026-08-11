import numpy as np
import pytest
from echo_personal_tool.infrastructure.samsung_tick_detector import (
    detect_ticks,
    TickDetectionResult,
)


def test_detect_ticks_returns_result():
    """Basic interface test."""
    img = np.zeros((200, 800, 3), dtype=np.uint8)
    for x in [100, 200, 300, 400, 500]:
        img[:, x, :] = 255
    
    result = detect_ticks(img)
    assert isinstance(result, TickDetectionResult)
    assert len(result.tick_positions) >= 2
    assert result.spacing_px > 0


def test_detect_ticks_measures_correct_spacing():
    """Verify spacing measurement on synthetic image."""
    img = np.zeros((200, 800, 3), dtype=np.uint8)
    for x in range(100, 700, 50):
        img[:, x, :] = 255
    
    result = detect_ticks(img)
    assert abs(result.spacing_px - 50.0) < 5.0


def test_detect_ticks_empty_image():
    """No ticks = low confidence."""
    img = np.zeros((200, 800, 3), dtype=np.uint8)
    result = detect_ticks(img)
    assert result.confidence < 0.5
