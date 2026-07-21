"""Wheel debounce coalesces rapid scroll into one frame_selected emission."""

from __future__ import annotations

import sys

import pytest
pytestmark = pytest.mark.gui
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from echo_personal_tool.domain.models import InstanceMetadata
from echo_personal_tool.domain.models.viewer_state import ViewerState
from echo_personal_tool.presentation.viewer_widget import ViewerWidget

pytest.importorskip("pytestqt")


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class _WheelEvent:
    def __init__(self, delta_y: int) -> None:
        self._delta_y = delta_y

    def angleDelta(self) -> QPoint:
        return QPoint(0, self._delta_y)

    def accept(self) -> None:
        pass


def _viewer_with_frames(qtbot, frame_count: int = 10) -> ViewerWidget:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    instance = InstanceMetadata(
        sop_instance_uid="1.2.3",
        series_uid="1.2.3.4",
        modality="US",
        number_of_frames=frame_count,
        pixel_spacing=None,
        frame_time_ms=33.3,
        series_description="Test",
        path=None,
        media_format="dicom",
    )
    state = ViewerState(
        instance=instance,
        current_frame_index=0,
        total_frames=frame_count,
        frame_time_ms=33.3,
        is_playing=False,
    )
    viewer.set_state(state)
    viewer.set_scroll_debounce_ms(50)
    return viewer


def test_wheel_debounce_emits_once_after_pause(qtbot) -> None:
    viewer = _viewer_with_frames(qtbot)
    emitted: list[int] = []
    viewer.scroll_frame_selected.connect(emitted.append)

    for _ in range(5):
        viewer._handle_wheel(_WheelEvent(120))

    assert emitted == []
    qtbot.wait(100)
    assert len(emitted) == 1
    assert emitted[0] == 5


def test_wheel_debounce_last_index_wins(qtbot) -> None:
    viewer = _viewer_with_frames(qtbot, frame_count=20)
    viewer._current_state = ViewerState(
        instance=viewer._current_state.instance,
        current_frame_index=3,
        total_frames=20,
        frame_time_ms=33.3,
        is_playing=False,
    )
    emitted: list[int] = []
    viewer.scroll_frame_selected.connect(emitted.append)

    viewer._handle_wheel(_WheelEvent(-120))
    viewer._handle_wheel(_WheelEvent(-120))
    viewer._handle_wheel(_WheelEvent(120))

    qtbot.wait(100)
    assert len(emitted) == 1
    assert emitted[0] == 4
