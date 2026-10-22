"""Display levels must be computed once per slider change, not once per frame.

Two independent defects made `_update_levels()` run `compute_display_levels()` - a
full-frame percentile pass, 12.7-19.7 ms at 1280x720 - on every frame of a MONOCHROME2
cine:

1. Key order mismatch: `show_frame_fast()` stamped `_cached_levels_key` as
   `(dr, window, level)` while `_update_levels()` compared it against
   `(window, level, dr)`, so the cache never hit at any resolution.
2. 8-bit outlier heuristic: `_is_levels_outlier()` tested raw pixel statistics against
   `mean < 5 / mean > 250 / std < 3`. For uint16 frames (mean ~1500-15000) the answer was
   always "outlier", so levels were never stored and the W/L window was recomputed - and
   visibly drifted - frame after frame.

Measured at 1280x720 MONO16 after the fix: `show_frame_fast` 19.95 -> 2.44 ms, playback
18.6 -> 30.8 FPS, main-thread load 85% -> 32% of the frame budget.
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui
pytest.importorskip("pytestqt")

from echo_personal_tool.domain.models import InstanceMetadata, ViewerState
from echo_personal_tool.presentation import viewer_widget as vw
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def _make_viewer(qtbot) -> ViewerWidget:
    w = ViewerWidget()
    qtbot.addWidget(w)
    w.resize(320, 240)
    w.show()
    qtbot.waitExposed(w)
    return w


def _make_state(uid: str = "1.2.3.4.5.6", total: int = 8) -> ViewerState:
    instance = InstanceMetadata(
        sop_instance_uid=uid,
        series_uid="1.2.3.4.5",
        modality="US",
        number_of_frames=total,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=None,
        media_format="dicom",
    )
    return ViewerState(
        instance=instance,
        current_frame_index=0,
        total_frames=total,
        frame_time_ms=33.3,
        is_playing=False,
    )


def _mono16_frame(seed: int) -> np.ndarray:
    """uint16 frame with realistic ultrasound statistics (mean ~3000, std ~1500)."""
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(3000.0, 1500.0, (64, 64)), 0, 65535).astype(np.uint16)


def _color_frame(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)


@pytest.fixture
def levels_spy(monkeypatch):
    """Record every `compute_display_levels()` call made by the viewer."""
    calls: list[dict] = []
    real = vw.compute_display_levels

    def _spy(frame, **kwargs):
        calls.append(kwargs)
        return real(frame, **kwargs)

    monkeypatch.setattr(vw, "compute_display_levels", _spy)
    return calls


class TestLevelsCacheHits:
    def test_computed_once_while_sliders_are_static(self, qtbot, levels_spy) -> None:
        w = _make_viewer(qtbot)
        w.set_state(_make_state())

        for seed in range(3):
            w.show_frame_fast(_mono16_frame(seed))

        assert len(levels_spy) == 1
        assert w._cached_levels_key == w._levels_sliders_key()

    def test_slider_move_recomputes_and_is_then_cached(self, qtbot, levels_spy) -> None:
        w = _make_viewer(qtbot)
        w.set_state(_make_state())
        w.show_frame_fast(_mono16_frame(0))
        assert len(levels_spy) == 1

        w._window_slider.setValue(w._window_slider.value() + 10)
        assert len(levels_spy) == 2

        w.show_frame_fast(_mono16_frame(1))
        assert len(levels_spy) == 2

    def test_key_order_is_window_level_dynamic_range(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w._window_slider.setValue(70)
        w._level_slider.setValue(60)
        w._dr_slider.setValue(40)

        assert w._levels_sliders_key() == (70, 60, 40)

    def test_show_frame_fast_does_not_stamp_the_key(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_state(_make_state())
        w.show_frame_fast(_color_frame(0))  # establishes the per-instance display mode
        assert w._is_color_frame is True
        assert w._window_level_enabled is False

        sentinel = (-1, -2, -3)
        w._cached_levels_key = sentinel
        w.show_frame_fast(_color_frame(1))

        assert w._cached_levels_key == sentinel


class TestOutlierHeuristic:
    def test_uint16_frame_with_normal_statistics_is_not_an_outlier(self, qtbot) -> None:
        w = _make_viewer(qtbot)

        assert w._is_levels_outlier(1000.0, 5000.0, _mono16_frame(0)) is False

    def test_uint8_frame_is_judged_on_the_same_scale(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        frame = np.random.default_rng(0).integers(0, 255, (32, 32), dtype=np.uint8)

        assert w._is_levels_outlier(20.0, 200.0, frame) is False

    def test_signed_16bit_uses_the_dtype_range(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        rng = np.random.default_rng(0)
        frame = np.clip(rng.normal(0.0, 2000.0, (32, 32)), -32768, 32767).astype(np.int16)

        # The old 8-bit thresholds saw mean ~0 and called every such frame an outlier.
        assert w._is_levels_outlier(-4000.0, 4000.0, frame) is False

    def test_dark_frames_are_still_outliers(self, qtbot) -> None:
        w = _make_viewer(qtbot)

        assert w._is_levels_outlier(5.0, 15.0, np.full((32, 32), 10, dtype=np.uint16)) is True
        assert w._is_levels_outlier(0.0, 4.0, np.full((32, 32), 2, dtype=np.uint8)) is True

    def test_flat_and_narrow_ranges_are_still_outliers(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        flat = np.full((32, 32), 128, dtype=np.uint8)

        assert w._is_levels_outlier(128.0, 128.5, flat) is True
        assert w._is_levels_outlier(100.0, 4000.0, np.full((32, 32), 60000, dtype=np.uint16)) is True

    def test_empty_frame_is_an_outlier(self, qtbot) -> None:
        w = _make_viewer(qtbot)

        assert w._is_levels_outlier(0.0, 255.0, np.zeros((0, 0), dtype=np.uint8)) is True
