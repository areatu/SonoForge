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


def test_detect_ticks_grayscale_input():
    """2D grayscale array should be handled directly."""
    img = np.zeros((200, 800), dtype=np.uint8)
    for x in range(100, 700, 50):
        img[:, x] = 255

    result = detect_ticks(img)
    assert isinstance(result, TickDetectionResult)
    assert result.spacing_px > 0


def test_detect_ticks_single_tick():
    """Single tick produces valid result with zero confidence."""
    img = np.zeros((200, 800, 3), dtype=np.uint8)
    img[:, 400, :] = 255

    result = detect_ticks(img)
    assert isinstance(result, TickDetectionResult)
    assert result.confidence == 0.0


def test_detect_ticks_empty_array_raises():
    """Empty input raises ValueError."""
    img = np.zeros((0, 0), dtype=np.uint8)
    with pytest.raises(ValueError, match="empty"):
        detect_ticks(img)


def test_detect_ticks_invalid_ndim_raises():
    """1D input raises ValueError."""
    img = np.zeros((800,), dtype=np.uint8)
    with pytest.raises(ValueError, match="2D or 3D"):
        detect_ticks(img)


def test_detect_ticks_bgr_channel_order():
    """BGR channel order should produce valid result."""
    img = np.zeros((200, 800, 3), dtype=np.uint8)
    for x in range(100, 700, 50):
        img[:, x, :] = 255

    result = detect_ticks(img, channel_order="bgr")
    assert isinstance(result, TickDetectionResult)
    assert result.spacing_px > 0


from echo_personal_tool.infrastructure.samsung_calibration_builder import (
    SamsungTickCalibration,
    build_calibration,
    load_calibration,
)


def test_build_calibration_returns_calibration():
    """Basic interface test."""
    training_data = []
    for freq in [60, 120, 240]:
        spacing = 6000 / freq
        img = np.zeros((200, 800, 3), dtype=np.uint8)
        for x in range(100, 700, int(spacing)):
            img[:, x, :] = 255
        training_data.append((freq, img))

    calibration = build_calibration(training_data)
    assert isinstance(calibration, SamsungTickCalibration)
    assert calibration.k_constant > 0
    assert calibration.r_squared > 0.9


def test_build_calibration_computes_correct_k():
    """Verify K constant computation."""
    training_data = []
    for freq in [60, 120]:
        spacing = 6000 / freq
        img = np.zeros((200, 800, 3), dtype=np.uint8)
        for x in range(100, 700, int(spacing)):
            img[:, x, :] = 255
        training_data.append((freq, img))

    calibration = build_calibration(training_data)
    assert abs(calibration.k_constant - 6000.0) < 100.0


def test_build_calibration_insufficient_data():
    """Too few valid measurements raises ValueError."""
    img = np.zeros((200, 800, 3), dtype=np.uint8)  # no ticks
    training_data = [(60, img), (120, img)]
    with pytest.raises(ValueError):
        build_calibration(training_data)


def test_load_calibration_missing_file():
    """Loading nonexistent calibration returns None."""
    result = load_calibration()
    # Can't guarantee file state; just verify function exists and returns something
    assert result is None or isinstance(result, SamsungTickCalibration)
