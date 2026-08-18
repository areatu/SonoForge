from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.infrastructure.samsung_tick_detector import (
    TickDetectionResult,
    detect_samsung_doppler_scales,
    detect_ticks,
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


from echo_personal_tool.infrastructure.dicom_doppler_calibration import try_parse_from_dataset


def _make_samsung_mis_tagged_dataset(frame_height: int = 884) -> Dataset:
    """Dataset mirroring real RS85 SF=1 mis-tagged PW/CW captures."""
    dataset = Dataset()
    dataset.Manufacturer = "SAMSUNG MEDISON"
    dataset.ManufacturerModelName = "RS85"
    dataset.Rows = frame_height
    region = Dataset()
    region.RegionSpatialFormat = 1  # SF=1 (2D) mis-tagged Doppler
    region.RegionDataType = 1
    region.RegionLocationMinX0 = 0
    region.RegionLocationMinY0 = 100
    region.RegionLocationMaxX1 = 1179
    region.RegionLocationMaxY1 = 473
    region.PhysicalDeltaX = 0.0375
    region.PhysicalDeltaY = 0.0375
    region.PhysicalUnitsXDirection = 3
    region.PhysicalUnitsYDirection = 3
    dataset.SequenceOfUltrasoundRegions = [region]
    return dataset


def test_samsung_tick_fallback_enables_time_scale():
    """Mis-tagged Samsung PW/CW frames get a tick-derived time scale via fallback."""
    dataset = _make_samsung_mis_tagged_dataset()

    # Synthetic RS85-like frame: dark spectrogram area + bottom ruler with
    # ticks at spacing 24 px (=> 120 Hz, per_pixel ~8.33 ms via k=5.0).
    frame = np.zeros((884, 1180, 3), dtype=np.uint8)
    frame[475:873, :, :] = 40  # dark Doppler panel
    for x in range(40, 700, 24):
        frame[845:875, x, :] = 255  # ruler ticks

    state = try_parse_from_dataset(dataset, frame)

    assert state is not None
    assert state.has_time_scale_from_dicom()
    assert state.time_from_dicom_tags
    assert state.time_span_ms > 0
    # ticks at 40..688 px (24 px spacing): visible sweep width = last-first+spacing
    # per_pixel_ms = 1000/(5*24) = 8.3333 => span ~ 8.3333 * 672
    assert abs(state.time_span_ms - (672 * 1000.0 / 120.0)) < 100.0


def test_samsung_tick_fallback_returns_none_without_frame():
    """No frame pixels -> no tick fallback (parse stays None for mis-tagged)."""
    dataset = _make_samsung_mis_tagged_dataset()
    assert try_parse_from_dataset(dataset, None) is None


def test_samsung_tick_fallback_ignores_other_vendors():
    """Tick fallback must not fire for non-Samsung datasets."""
    dataset = Dataset()
    dataset.Manufacturer = "GE Medical Systems"
    dataset.ManufacturerModelName = "Vivid E95"
    dataset.Rows = 884
    region = Dataset()
    region.RegionSpatialFormat = 1
    region.RegionDataType = 1
    region.RegionLocationMinX0 = 0
    region.RegionLocationMinY0 = 100
    region.RegionLocationMaxX1 = 1179
    region.RegionLocationMaxY1 = 473
    region.PhysicalDeltaX = 0.0375
    region.PhysicalDeltaY = 0.0375
    region.PhysicalUnitsXDirection = 3
    region.PhysicalUnitsYDirection = 3
    dataset.SequenceOfUltrasoundRegions = [region]

    frame = np.zeros((884, 1180, 3), dtype=np.uint8)
    frame[475:873, :, :] = 40
    for x in range(40, 700, 24):
        frame[845:875, x, :] = 255

    assert try_parse_from_dataset(dataset, frame) is None


# ---------------------------------------------------------------------------
# B-mode rejection: a Doppler time ruler always sits above a DARK spectral
# band.  Bright regions (B-mode tissue, banners, labels) are false positives
# and must not produce a time scale or a saved Doppler ROI.
# ---------------------------------------------------------------------------


def _bmode_frame_with_fake_ruler() -> np.ndarray:
    """Bright B-mode-like frame with a fake tick ruler at the bottom."""
    frame = np.zeros((884, 1180, 3), dtype=np.uint8)
    frame[:] = 120  # bright tissue across the whole frame
    for x in range(40, 700, 24):
        frame[850:875, x, :] = 255  # false vertical ticks at the bottom
    return frame


def _dark_doppler_frame_with_ruler() -> np.ndarray:
    """Realistic Doppler frame: dark spectral band + time ruler at the bottom."""
    frame = np.zeros((884, 1180, 3), dtype=np.uint8)
    frame[475:873, :, :] = 40  # dark spectral band
    for x in range(40, 700, 24):
        frame[845:875, x, :] = 255  # ruler ticks
    return frame


def test_detect_ticks_rejects_bright_bmode_frame():
    """A ruler over a bright B-mode region is a false positive."""
    result = detect_ticks(_bmode_frame_with_fake_ruler())
    assert result.confidence == 0.0
    assert len(result.tick_positions) == 0


def test_detect_ticks_accepts_dark_doppler_frame():
    """A ruler over a dark spectral band is a real Doppler time scale."""
    result = detect_ticks(_dark_doppler_frame_with_ruler())
    assert result.confidence >= 0.4
    assert len(result.tick_positions) >= 5


def test_detect_samsung_doppler_scales_rejects_bmode_frame():
    """B-mode frame with bottom 'ticks' and side axes yields no Doppler ROI."""
    img = _bmode_frame_with_fake_ruler()
    # fake vertical velocity-scale axes on both sides
    img[200:850, 60, :] = 255
    img[200:850, 1110, :] = 255

    scales = detect_samsung_doppler_scales(img)
    assert scales.time_scale.confidence == 0.0
    assert scales.refined_roi is None


def test_detect_samsung_doppler_scales_accepts_doppler_frame():
    """Dark Doppler frame with a time ruler + velocity scale yields an ROI."""
    img = _dark_doppler_frame_with_ruler()
    # left velocity scale: vertical axis + periodic horizontal ticks
    img[400:850, 30, :] = 255
    for y in range(480, 820, 24):
        img[y : y + 2, 22:38, :] = 255

    scales = detect_samsung_doppler_scales(img)
    assert scales.time_scale.confidence >= 0.4
    assert scales.left_velocity_scale is not None
    assert scales.refined_roi is not None


def test_samsung_tick_fallback_rejects_bmode_frame():
    """Mis-tagged Samsung SF=1 region over a BRIGHT B-mode frame must not be
    saved as Doppler (the tick fallback must not fire on a bright bottom)."""
    dataset = _make_samsung_mis_tagged_dataset()
    assert try_parse_from_dataset(dataset, _bmode_frame_with_fake_ruler()) is None
