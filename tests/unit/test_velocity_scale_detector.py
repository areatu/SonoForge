import numpy as np
import pytest

from echo_personal_tool.domain.models.doppler_roi import DopplerSpectrogramRoi
from echo_personal_tool.domain.services.velocity_scale_detector import (
    detect_velocity_scale_ticks,
)


def _make_frame_with_scale(
    height: int = 400,
    width: int = 640,
    roi: DopplerSpectrogramRoi | None = None,
    tick_ys: tuple[int, ...] = (80, 160, 240, 320),
    scale_x: int = 600,
) -> np.ndarray:
    frame = np.zeros((height, width), dtype=np.uint8)
    if roi is None:
        roi = DopplerSpectrogramRoi(x0=40, y0=20, width=540, height=360)
    # Spectrogram interior (dark) so the strip stands out
    frame[int(roi.y0):int(roi.y0 + roi.height), int(roi.x0):int(roi.x1)] = 30
    for y in tick_ys:
        # Tick mark in the strip to the right of the spectrogram
        frame[y, scale_x : scale_x + 10] = 220
    return frame


def test_detects_ticks_in_strip() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=20, width=540, height=360)
    frame = _make_frame_with_scale(roi=roi, tick_ys=(80, 160, 240, 320), scale_x=600)
    ticks = detect_velocity_scale_ticks(frame, roi=roi)
    assert len(ticks) == 4
    # Each detected tick within 4px of a planted tick
    for ty in (80, 160, 240, 320):
        assert any(abs(t - ty) <= 4 for t in ticks)


def test_no_ticks_returns_empty() -> None:
    roi = DopplerSpectrogramRoi(x0=40, y0=20, width=540, height=360)
    frame = np.zeros((400, 640), dtype=np.uint8)
    ticks = detect_velocity_scale_ticks(frame, roi=roi)
    assert ticks == []