from __future__ import annotations

from echo_personal_tool.presentation.calibration_snap import snap_y_to_nearest_tick


def test_snap_within_radius() -> None:
    ticks = [20.0, 40.0, 60.0, 80.0]
    assert snap_y_to_nearest_tick(42.0, ticks, radius_px=5) == 40.0


def test_snap_outside_radius_returns_original() -> None:
    ticks = [20.0, 40.0, 60.0, 80.0]
    assert snap_y_to_nearest_tick(50.0, ticks, radius_px=5) == 50.0


def test_snap_empty_ticks_returns_original() -> None:
    assert snap_y_to_nearest_tick(50.0, [], radius_px=5) == 50.0


def test_snap_picks_nearest() -> None:
    ticks = [20.0, 40.0, 60.0]
    assert snap_y_to_nearest_tick(47.0, ticks, radius_px=10) == 40.0
    assert snap_y_to_nearest_tick(53.0, ticks, radius_px=10) == 60.0
