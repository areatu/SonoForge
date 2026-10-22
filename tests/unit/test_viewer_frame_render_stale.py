"""A frame passed again from the same buffer must not render a stale frame.

Regression: ``show_frame_fast`` cached the grayscale conversion of a 3-channel
frame by the frame's memory address.  PHI masking builds a fresh temporary per
frame and the allocator recycles that address, so the cache false-hit and the
viewer kept re-rendering an older frame — playback froze and scrolling showed
stale frames.  Reusing a single buffer here reproduces the same false hit.
"""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models import InstanceMetadata, ViewerState

pytestmark = pytest.mark.gui
pytest.importorskip("pytestqt")


@pytest.fixture(autouse=True)
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _state() -> ViewerState:
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3.4.5.6",
        series_uid="1.2.3.4.5",
        modality="US",
        number_of_frames=8,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=None,
        media_format="dicom",
    )
    return ViewerState(
        instance=instance,
        current_frame_index=0,
        total_frames=8,
        frame_time_ms=33.3,
        is_playing=False,
    )


def _grayish(value: int, size: int = 16) -> np.ndarray:
    """3-channel frame with equal channels → classified as grayscale."""
    ramp = np.tile(np.arange(size, dtype=np.uint8), (size, 1))
    base = np.clip(ramp.astype(np.int16) + value, 0, 255).astype(np.uint8)
    return np.dstack([base, base, base])


def _make_viewer(qtbot):
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    w = ViewerWidget()
    qtbot.addWidget(w)
    w.resize(200, 200)
    w.show()
    qtbot.waitExposed(w)
    w.set_state(_state())
    w._phi_filter.set_enabled(False)
    return w


def test_reused_frame_buffer_renders_the_new_content(qtbot) -> None:
    w = _make_viewer(qtbot)

    frame = _grayish(0)
    assert w._resolve_display_mode(frame, "dicom") == (False, True)  # grayscale + W/L

    buffer = np.empty_like(frame)
    buffer[...] = frame
    w.show_frame_fast(buffer)
    first = np.array(w._image_item.image, copy=True)

    buffer[...] = _grayish(180)  # same address, different content
    w.show_frame_fast(buffer)
    second = np.array(w._image_item.image, copy=True)

    assert not np.array_equal(first, second), "reused buffer rendered a stale frame"


def test_streamed_frames_all_render(qtbot) -> None:
    w = _make_viewer(qtbot)
    rng = np.random.default_rng(0)
    outputs: list[np.ndarray] = []
    for _ in range(5):
        pattern = rng.integers(0, 16, (16, 16)).astype(np.uint8)
        w.show_frame_fast(np.dstack([pattern, pattern, pattern]))
        outputs.append(np.array(w._image_item.image, copy=True))
    # Same value range, different spatial pattern: with the levels cached from
    # the first frame, every later frame still renders its own content.
    for previous, current in zip(outputs, outputs[1:]):
        assert not np.array_equal(previous, current), "a streamed frame did not update"
