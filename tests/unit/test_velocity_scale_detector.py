import numpy as np

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.velocity_scale_detector import (
    detect_velocity_scale_ticks,
    find_scale_strip_x,
)


def _make_frame_with_scale(
    height: int = 600,
    width: int = 640,
    roi: DopplerSpectrogramRoi | None = None,
    tick_ys: tuple[int, ...] = (150, 250, 350, 450),
    scale_x: int = 600,
    bmode_brightness: int = 200,
) -> np.ndarray:
    """Build a synthetic frame with ticks in the scale strip.

    The upper ``roi.y0`` rows are filled with *bmode_brightness* to simulate a
    B-mode region; the lower portion is dark (spectrogram).
    Tick marks are placed in the scale strip at *scale_x*.
    """
    frame = np.zeros((height, width), dtype=np.uint8)
    if roi is None:
        roi = DopplerSpectrogramRoi(x0=40, y0=100, width=540, height=480)
    # B-mode area (upper part)
    bmode_h = int(roi.y0)
    frame[:bmode_h, :] = bmode_brightness
    # Spectrogram interior (dark) so the strip stands out
    frame[int(roi.y0):int(roi.y0 + roi.height), int(roi.x0):int(roi.x1)] = 30
    for y in tick_ys:
        frame[y, scale_x : scale_x + 10] = 220
    return frame


def test_detects_ticks_in_strip() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=100, width=540, height=480)
    frame = _make_frame_with_scale(roi=roi, tick_ys=(150, 250, 350, 450), scale_x=600)
    ticks = detect_velocity_scale_ticks(frame, roi=roi)
    assert len(ticks) >= 4
    for ty in (150, 250, 350, 450):
        assert any(abs(t - ty) <= 6 for t in ticks)


def test_no_ticks_returns_empty() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=100, width=540, height=480)
    frame = np.zeros((600, 640), dtype=np.uint8)
    ticks = detect_velocity_scale_ticks(frame, roi=roi)
    assert ticks == []


def test_detects_ticks_with_full_frame_roi_and_baseline() -> None:
    """When ROI is the full frame, ticks are found via the right-strip fallback,
    restricted to the y-range around the baseline (not searching B-mode area)."""
    h, w = 600, 640
    roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=float(w), height=float(h))
    frame = _make_frame_with_scale(
        height=h, width=w, roi=roi,
        tick_ys=(150, 250, 350, 450, 550), scale_x=600,
    )
    baseline_y = 350.0
    ticks = detect_velocity_scale_ticks(frame, roi=roi, baseline_y=baseline_y)
    assert len(ticks) >= 4
    for t in ticks:
        assert t >= 50.0


def test_baseline_y_excludes_bmode_area() -> None:
    """With baseline_y set and full-frame ROI, the B-mode region (top) is
    excluded from the tick search so no false ticks are detected there."""
    h, w = 600, 640
    roi = DopplerSpectrogramRoi(x0=0.0, y0=0.0, width=float(w), height=float(h))
    frame = np.zeros((h, w), dtype=np.uint8)
    frame[:100, :] = 200  # B-mode top area
    # Plant false ticks in the B-mode area
    for y in (20, 40, 60, 80):
        frame[y, 600:610] = 220
    # Real ticks in spectrogram area
    for y in (150, 250, 350, 450, 550):
        frame[y, 600:610] = 220
    baseline_y = 350.0
    ticks = detect_velocity_scale_ticks(frame, roi=roi, baseline_y=baseline_y)
    # None of the detected ticks should be in the B-mode area (y < 100)
    for t in ticks:
        assert t >= 100.0


def test_find_scale_strip_x_returns_strip_column() -> None:
    """find_scale_strip_x returns the x-column of the scale strip."""
    h, w = 600, 640
    roi = DopplerSpectrogramRoi(x0=40, y0=100, width=540, height=480)
    frame = _make_frame_with_scale(
        height=h, width=w, roi=roi,
        tick_ys=(150, 250, 350, 450, 550), scale_x=600,
    )
    x = find_scale_strip_x(frame, roi=roi, baseline_y=350.0)
    assert 580 <= x <= 615