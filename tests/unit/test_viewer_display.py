"""Isolated contract tests for the ViewerDisplay owner (A2)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gui
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QWidget

from echo_personal_tool.imaging.display import compute_display_levels, dr_percentiles_from_slider
from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider
from echo_personal_tool.presentation.viewer.display import ViewerDisplay


class _ImageSink:
    """Minimal stand-in for pyqtgraph.ImageItem."""

    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.auto_levels: list[bool] = []

    def setImage(self, image: np.ndarray, autoLevels: bool = False) -> None:  # noqa: N802 - Qt API name
        self.frames.append(np.array(image, copy=True))
        self.auto_levels.append(autoLevels)


def _frame(seed: int = 0, *, dtype: type = np.uint8, shape: tuple[int, ...] = (32, 32)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        return rng.integers(info.min, info.max, shape, dtype=dtype)
    return rng.random(shape).astype(dtype)


class _Harness:
    def __init__(self, qtbot) -> None:
        self.host = QWidget()
        qtbot.addWidget(self.host)
        self.frame: np.ndarray | None = _frame()
        self.enabled = True
        self.color_source: np.ndarray | None = None
        self.color_active = False
        self.image = _ImageSink()
        self.edge_invalidations = 0
        self.display = ViewerDisplay(
            parent=self.host,
            frame_provider=lambda: self.frame,
            enabled_provider=lambda: self.enabled,
            color_source_provider=lambda: self.color_source,
            color_active_provider=lambda: self.color_active,
            image_item=self.image,
            invalidate_edge_map=self._invalidate,
        )

    def _invalidate(self) -> None:
        self.edge_invalidations += 1


@pytest.fixture
def harness(qtbot) -> _Harness:
    owner = _Harness(qtbot)
    yield owner
    owner.display.deleteLater()


def test_set_values_updates_pixels_and_blocks_slider_signals(harness: _Harness) -> None:
    harness.display.set_values(120, 60, 40)

    assert harness.display.values == (120, 60, 40)
    assert len(harness.image.frames) == 1
    assert harness.image.frames[0].dtype == np.uint8
    assert harness.image.auto_levels == [False]
    assert harness.edge_invalidations == 1


def test_set_values_without_display_leaves_the_image_untouched(harness: _Harness) -> None:
    harness.display.set_values(130, 70, 30, update_display=False)

    assert harness.display.values == (130, 70, 30)
    assert harness.image.frames == []


def test_update_levels_is_a_noop_when_disabled(harness: _Harness) -> None:
    harness.enabled = False
    harness.display.update_levels()

    assert harness.image.frames == []
    assert harness.edge_invalidations == 0


def test_update_levels_is_a_noop_for_an_empty_frame(harness: _Harness) -> None:
    harness.frame = np.empty((0, 0), dtype=np.uint8)
    harness.display.update_levels()

    assert harness.image.frames == []


def test_effective_levels_match_compute_display_levels(harness: _Harness) -> None:
    harness.display.set_values(80, 40, 60)
    frame = _frame(dtype=np.float64)
    harness.frame = frame
    dr_low, dr_high = dr_percentiles_from_slider(60)
    expected = compute_display_levels(
        frame,
        dr_low_pct=dr_low,
        dr_high_pct=dr_high,
        window_scale=0.8,
        level_offset=-0.2,
    )

    assert harness.display.effective_levels() == expected


def test_remember_and_restore_instance_round_trip(harness: _Harness) -> None:
    harness.display.set_values(140, 63, 37)
    harness.display.remember_instance("1.2.3")
    harness.display.set_values(75, 52, 48)
    rendered = len(harness.image.frames)

    assert harness.display.restore_instance("1.2.3") is True
    assert harness.display.values == (140, 63, 37)
    assert len(harness.image.frames) == rendered


def test_restore_unknown_instance_does_not_reset_values(harness: _Harness) -> None:
    harness.display.set_values(110, 55, 45)

    assert harness.display.restore_instance("9.9.9") is False
    assert harness.display.restore_instance(None) is False
    assert harness.display.values == (110, 55, 45)


def test_instance_cache_is_bounded_lru(harness: _Harness) -> None:
    for index in range(201):
        harness.display.set_values(100 + index % 50, 50, 50, update_display=False)
        harness.display.remember_instance(f"uid-{index}")

    assert harness.display.restore_instance("uid-0") is False
    assert harness.display.restore_instance("uid-1") is True
    assert harness.display.values == (101, 50, 50)
    assert harness.display.restore_instance("uid-200") is True


def test_set_current_path_remembers_each_file(harness: _Harness, tmp_path: Path) -> None:
    first = tmp_path / "a.dcm"
    second = tmp_path / "b.dcm"

    harness.display.set_current_path(first)
    assert harness.display.values == (100, 50, 50)
    harness.display.set_values(130, 65, 35)

    harness.display.set_current_path(second)
    assert harness.display.values == (100, 50, 50)
    harness.display.set_values(80, 45, 55)

    harness.display.set_current_path(first)
    assert harness.display.values == (130, 65, 35)
    harness.display.set_current_path(second)
    assert harness.display.values == (80, 45, 55)


def test_cached_key_setter_is_cleared_by_invalidation(harness: _Harness) -> None:
    harness.display.cached_levels_key = (-1, -2, -3)
    harness.display.invalidate_cached_levels()

    assert harness.display.cached_levels_key is None
    assert harness.image.frames == []


def test_flat_frame_is_an_outlier_and_keeps_previous_levels(harness: _Harness) -> None:
    harness.frame = _frame()
    harness.display.update_levels()
    cached = harness.display.cached_levels_key
    assert cached is not None

    harness.frame = np.full((32, 32), 3000, dtype=np.uint16)
    assert harness.display.is_levels_outlier(1000.0, 5000.0, harness.frame) is True
    harness.display.set_values(90, 50, 50)  # key changes, outlier path falls back
    # The outlier does not overwrite the good cache key.
    assert harness.display.cached_levels_key == cached


def test_color_frame_goes_through_the_rgb_projection(harness: _Harness) -> None:
    harness.color_active = True
    harness.color_source = _frame(dtype=np.uint8, shape=(16, 16, 3))

    harness.display.update_levels()

    assert len(harness.image.frames) == 1
    assert harness.image.frames[0].shape == (16, 16, 3)


def test_binding_external_slider_mirrors_values_and_enabled(harness: _Harness) -> None:
    window = TopLabeledSlider("W", minimum=1, maximum=400, value=100)
    level = TopLabeledSlider("L", minimum=0, maximum=100, value=50)
    dr = TopLabeledSlider("DR", minimum=0, maximum=100, value=50)
    harness.display.bind_external(window, level, dr)

    window.slider().setValue(160)
    assert harness.display.values[0] == 160

    harness.enabled = False
    harness.display.sync_external_enabled()
    assert window.isEnabled() is False
    assert harness.display.window_slider.isEnabled() is False

    harness.display.disconnect_external()
