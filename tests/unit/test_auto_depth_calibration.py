from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.services.auto_depth_calibration import (
    AutoCalibrationResult,
    try_auto_depth_calibration,
)


_rng = np.random.default_rng(42)


def _frame_with_regular_ticks(
    height: int = 400,
    width: int = 640,
    tick_spacing_px: int = 20,
    tick_x: int = 600,
) -> np.ndarray:
    frame = np.zeros((height, width), dtype=np.uint8)
    frame[:, 50:550] = _rng.integers(10, 60, (height, 500), dtype=np.uint8)
    for y in range(10, height - 10, tick_spacing_px):
        frame[y, tick_x : tick_x + 8] = 200
    return frame


def test_auto_calibration_returns_result() -> None:
    frame = _frame_with_regular_ticks(tick_spacing_px=20)
    result = try_auto_depth_calibration(frame)
    assert result is not None
    assert isinstance(result, AutoCalibrationResult)
    assert result.spacing[0] > 0
    assert result.tick_count >= 5
    assert result.confidence > 0


def test_auto_calibration_spacing_value() -> None:
    frame = _frame_with_regular_ticks(tick_spacing_px=20)
    result = try_auto_depth_calibration(frame, cm_per_major_tick=1.0)
    assert result is not None
    expected_mm_per_px = 10.0 / 20.0
    assert abs(result.spacing[0] - expected_mm_per_px) < 0.1


def test_auto_calibration_blank_frame() -> None:
    frame = np.zeros((400, 640), dtype=np.uint8)
    result = try_auto_depth_calibration(frame)
    assert result is None


def test_auto_calibration_irregular_spacing() -> None:
    frame = np.zeros((400, 640), dtype=np.uint8)
    frame[:, 50:550] = np.random.randint(10, 60, (400, 500), dtype=np.uint8)
    irregular_ys = [20, 30, 80, 200, 210, 350]
    for y in irregular_ys:
        frame[y, 600:608] = 200
    result = try_auto_depth_calibration(frame, max_spacing_cv=0.15)
    assert result is None


def test_auto_calibration_too_few_ticks() -> None:
    frame = np.zeros((400, 640), dtype=np.uint8)
    frame[50, 600:608] = 200
    frame[100, 600:608] = 200
    result = try_auto_depth_calibration(frame, min_ticks=5)
    assert result is None
