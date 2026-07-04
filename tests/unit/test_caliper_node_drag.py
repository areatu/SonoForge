"""Caliper node drag/release tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
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


def _place_caliper(viewer: ViewerWidget, x_start: float, x_end: float, y: float = 32.0) -> None:
    scene_start = viewer._view.mapViewToScene(QPointF(x_start, y))
    ev_start = MagicMock()
    ev_start.button.return_value = Qt.MouseButton.LeftButton
    ev_start.scenePos.return_value = scene_start
    assert viewer._handle_linear_caliper_mouse_press(ev_start)

    scene_end = viewer._view.mapViewToScene(QPointF(x_end, y))
    ev_end = MagicMock()
    ev_end.button.return_value = Qt.MouseButton.LeftButton
    ev_end.scenePos.return_value = scene_end
    assert viewer._handle_linear_caliper_mouse_press(ev_end)


def _chain_click(viewer: ViewerWidget, x: float, y: float = 32.0) -> None:
    """Single click for a chained caliper (start already set by previous segment)."""
    scene = viewer._view.mapViewToScene(QPointF(x, y))
    ev = MagicMock()
    ev.button.return_value = Qt.MouseButton.LeftButton
    ev.scenePos.return_value = scene
    assert viewer._handle_linear_caliper_mouse_press(ev)


def _find_node_for_endpoint(
    viewer: ViewerWidget, caliper_key: tuple[str, int], endpoint: int
):
    for item in viewer._persistent_linear_graphics:
        if len(item) >= 4 and item[3] == caliper_key:
            return item[1] if endpoint == 0 else item[2]
    return None


def test_drag_endpoint_0_moves_start(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(_sample_state())

    viewer.start_linear_caliper_for("LVEDD")
    _place_caliper(viewer, 10.0, 50.0)

    key = list(viewer._stored_linear_measurements.keys())[0]
    m = viewer._stored_linear_measurements[key]
    assert m.start[0] == pytest.approx(10.0)
    assert m.end[0] == pytest.approx(50.0)

    node = _find_node_for_endpoint(viewer, key, 0)
    assert node is not None

    scene_pos = viewer._view.mapViewToScene(QPointF(5.0, 32.0))
    ev_press = MagicMock()
    ev_press.button.return_value = Qt.MouseButton.LeftButton
    ev_press.scenePos.return_value = scene_pos
    node.mousePressEvent(ev_press)

    assert viewer._caliper_drag_active
    assert viewer._caliper_drag_node == 0

    scene_move = viewer._view.mapViewToScene(QPointF(20.0, 32.0))
    ev_move = MagicMock()
    ev_move.button.return_value = Qt.MouseButton.LeftButton
    ev_move.scenePos.return_value = scene_move
    node.mouseDragEvent(ev_move)

    m2 = viewer._stored_linear_measurements[key]
    assert m2.start[0] == pytest.approx(20.0)
    assert m2.end[0] == pytest.approx(50.0)

    ev_release = MagicMock()
    ev_release.button.return_value = Qt.MouseButton.LeftButton
    node.mouseReleaseEvent(ev_release)

    assert not viewer._caliper_drag_active


def test_drag_endpoint_1_moves_end(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(_sample_state())

    viewer.start_linear_caliper_for("LVEDD")
    _place_caliper(viewer, 10.0, 50.0)

    key = list(viewer._stored_linear_measurements.keys())[0]
    node = _find_node_for_endpoint(viewer, key, 1)
    assert node is not None

    scene_pos = viewer._view.mapViewToScene(QPointF(50.0, 32.0))
    ev_press = MagicMock()
    ev_press.button.return_value = Qt.MouseButton.LeftButton
    ev_press.scenePos.return_value = scene_pos
    node.mousePressEvent(ev_press)

    assert viewer._caliper_drag_node == 1

    scene_move = viewer._view.mapViewToScene(QPointF(60.0, 32.0))
    ev_move = MagicMock()
    ev_move.button.return_value = Qt.MouseButton.LeftButton
    ev_move.scenePos.return_value = scene_move
    node.mouseDragEvent(ev_move)

    m2 = viewer._stored_linear_measurements[key]
    assert m2.start[0] == pytest.approx(10.0)
    assert m2.end[0] == pytest.approx(60.0)

    ev_release = MagicMock()
    ev_release.button.return_value = Qt.MouseButton.LeftButton
    node.mouseReleaseEvent(ev_release)


def test_drag_first_caliper_second_remains_visible(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(_sample_state())

    viewer.start_linear_caliper_sequence(("IVSd", "LVEDD"))
    _place_caliper(viewer, 5.0, 15.0)
    # Chain: start is already at end of first segment (15, 32), just click end
    _chain_click(viewer, 50.0)

    keys = list(viewer._stored_linear_measurements.keys())
    assert len(keys) == 2

    key0 = keys[0]
    node = _find_node_for_endpoint(viewer, key0, 0)
    assert node is not None

    scene_pos = viewer._view.mapViewToScene(QPointF(5.0, 32.0))
    ev_press = MagicMock()
    ev_press.button.return_value = Qt.MouseButton.LeftButton
    ev_press.scenePos.return_value = scene_pos
    node.mousePressEvent(ev_press)

    scene_move = viewer._view.mapViewToScene(QPointF(10.0, 32.0))
    ev_move = MagicMock()
    ev_move.button.return_value = Qt.MouseButton.LeftButton
    ev_move.scenePos.return_value = scene_move
    node.mouseDragEvent(ev_move)

    ev_release = MagicMock()
    ev_release.button.return_value = Qt.MouseButton.LeftButton
    node.mouseReleaseEvent(ev_release)

    assert len(viewer._stored_linear_measurements) == 2
    assert len(viewer._persistent_linear_graphics) == 2
    for item in viewer._persistent_linear_graphics:
        line_item = item[0]
        assert line_item.isVisible()


def test_esc_cancels_drag(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.set_state(_sample_state())

    viewer.start_linear_caliper_for("LVEDD")
    _place_caliper(viewer, 10.0, 50.0)

    key = list(viewer._stored_linear_measurements.keys())[0]
    original = viewer._stored_linear_measurements[key]
    node = _find_node_for_endpoint(viewer, key, 0)
    assert node is not None

    scene_pos = viewer._view.mapViewToScene(QPointF(5.0, 32.0))
    ev_press = MagicMock()
    ev_press.button.return_value = Qt.MouseButton.LeftButton
    ev_press.scenePos.return_value = scene_pos
    node.mousePressEvent(ev_press)

    scene_move = viewer._view.mapViewToScene(QPointF(20.0, 32.0))
    ev_move = MagicMock()
    ev_move.button.return_value = Qt.MouseButton.LeftButton
    ev_move.scenePos.return_value = scene_move
    node.mouseDragEvent(ev_move)

    ev_key = MagicMock()
    ev_key.key.return_value = Qt.Key.Key_Escape
    viewer.keyPressEvent(ev_key)

    assert not viewer._caliper_drag_active
    restored = viewer._stored_linear_measurements[key]
    assert restored.start == original.start
    assert restored.end == original.end


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
