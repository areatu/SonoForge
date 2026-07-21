"""Display quality tests: debug overlay, zoom modes, smooth scaling."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
pytestmark = pytest.mark.gui
from PySide6.QtWidgets import QApplication

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def _sample_instance() -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid="1.2.3.4.5",
        series_uid="1.2.3.4.6",
        modality="US",
        number_of_frames=10,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description="Test",
        path=Path("/tmp/test.dcm"),
    )


def _sample_state() -> ViewerState:
    return ViewerState(
        instance=_sample_instance(),
        current_frame_index=0,
        total_frames=10,
        frame_time_ms=33.3,
        is_playing=False,
    )


def test_debug_overlay_toggle(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show()
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(_sample_state())

    assert not viewer._debug_overlay_visible
    assert viewer._debug_overlay_label.isHidden()

    viewer.toggle_debug_overlay()

    assert viewer._debug_overlay_visible
    text = viewer._debug_overlay_label.text()
    assert "Native: 64x64" in text
    assert "Format: dicom" in text

    viewer.toggle_debug_overlay()

    assert not viewer._debug_overlay_visible
    assert viewer._debug_overlay_label.isHidden()


def test_zoom_mode_default_fit(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(_sample_state())

    assert viewer.zoom_mode == "fit"


def test_cycle_zoom_mode(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(_sample_state())

    assert viewer.zoom_mode == "fit"

    viewer.cycle_zoom_mode()
    assert viewer.zoom_mode == "100%"

    viewer.cycle_zoom_mode()
    assert viewer.zoom_mode == "200%"

    viewer.cycle_zoom_mode()
    assert viewer.zoom_mode == "fit"


def test_set_zoom_mode(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(_sample_state())

    viewer.set_zoom_mode("100%")
    assert viewer.zoom_mode == "100%"

    viewer.set_zoom_mode("invalid")
    assert viewer.zoom_mode == "100%"

    viewer.set_zoom_mode("fit")
    assert viewer.zoom_mode == "fit"


def test_graphics_view_smooth_hint(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)

    from PySide6.QtGui import QPainter

    hints = viewer._graphics.renderHints()
    assert bool(hints & QPainter.RenderHint.SmoothPixmapTransform)


def test_native_resolution_preserved(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    pixels = np.zeros((480, 640), dtype=np.uint8)
    viewer.show_frame(pixels)
    viewer.set_state(_sample_state())

    assert viewer._current_frame is not None
    h, w = viewer._current_frame.shape[:2]
    assert h == 480
    assert w == 640


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
