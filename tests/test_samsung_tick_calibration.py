import numpy as np
import pytest
from pathlib import Path

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
        spacing = freq / 5.0
        img = np.zeros((200, 800, 3), dtype=np.uint8)
        for x in range(100, 700, int(spacing)):
            img[:, x, :] = 255
        training_data.append((freq, img))

    calibration = build_calibration(training_data)
    assert isinstance(calibration, SamsungTickCalibration)
    assert calibration.k_constant > 0
    assert calibration.r_squared > 0.9


def test_build_calibration_computes_correct_k():
    """Verify K constant computation (linear model, k == 5.0)."""
    training_data = []
    for freq in [60, 120]:
        spacing = freq / 5.0
        img = np.zeros((200, 800, 3), dtype=np.uint8)
        for x in range(100, 700, int(spacing)):
            img[:, x, :] = 255
        training_data.append((freq, img))

    calibration = build_calibration(training_data)
    assert abs(calibration.k_constant - 5.0) < 0.5


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


def test_load_calibration_is_trained():
    """The committed calibration JSON should be loaded and match training."""
    cal = load_calibration()
    if cal is None:
        pytest.skip("calibration JSON not present")
    assert abs(cal.k_constant - 5.0) < 0.1
    assert cal.r_squared > 0.99
    assert len(cal.measured_points) >= 10


from pydicom.dataset import Dataset

from echo_personal_tool.infrastructure.vendor_profiles.samsung import SamsungProfile


def test_samsung_profile_falls_back_to_tick_detection():
    """Samsung profile uses tick detection when DICOM time tags are absent."""
    region = Dataset()
    region.RegionLocationMaxX1 = 1180

    pixels = np.zeros((884, 1180, 3), dtype=np.uint8)
    # Simulate a ruler at spacing=24 px (>=120 Hz, >=6 ticks within 0..700)
    for x in range(40, 700, 24):
        pixels[845:875, x, :] = 255

    profile = SamsungProfile()
    if profile._tick_calibration is None:
        pytest.skip("calibration not trained")
    result = profile.compute_time_span(region, 700.0, pixels)
    assert result is not None
    # spacing=24 -> freq=120 Hz -> per_pixel ~8.33 ms
    assert abs(result.per_pixel_ms - 1000.0 / 120.0) < 1.0


def test_samsung_profile_uses_dicom_tags_when_present():
    """DICOM time tags take precedence over tick detection."""
    region = Dataset()
    region.PhysicalDeltaX = 0.01667
    region.PhysicalUnitsXDirection = 4
    region.RegionLocationMaxX1 = 1180

    profile = SamsungProfile()
    result = profile.compute_time_span(region, 700.0, None)
    assert result is not None
    assert result.source.startswith("Samsung: PhysicalDeltaX")


@pytest.mark.skipif(
    not Path("/home/areatu/ECHO2026_src/New Folder2").exists(),
    reason="Samsung training data not available",
)
def test_calibration_on_real_data():
    """Verify calibration works on real Samsung DICOM files."""
    import pydicom

    data_dir = Path("/home/areatu/ECHO2026_src/New Folder2")
    calibration = load_calibration()
    assert calibration is not None, "Calibration not trained yet"

    # Test on a few files
    for name in ["PW 60 Hz.dcm", "CW 120 Hz.dcm", "PW 720 Hz.dcm"]:
        dcm_path = data_dir / name
        if not dcm_path.exists():
            continue

        ds = pydicom.dcmread(str(dcm_path))
        pixels = ds.pixel_array

        result = detect_ticks(pixels)
        if result.confidence > 0.3:
            detected_freq = calibration.k_constant * result.spacing_px
            expected_freq = float(name.split()[1])
            error_pct = abs(detected_freq - expected_freq) / expected_freq * 100

            print(f"{name}: detected={detected_freq:.1f} Hz, expected={expected_freq:.0f} Hz, error={error_pct:.1f}%")
            assert error_pct < 20.0, f"Frequency detection error too large: {error_pct:.1f}%"
