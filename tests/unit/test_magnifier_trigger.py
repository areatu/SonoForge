"""Loupe appears on Z without a mouse move, and stays for linear calipers when asked."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _viewer(qtbot):
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((80, 80), dtype=np.uint8))
    viewer.show()
    return viewer


def _press_z(viewer) -> None:
    viewer.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.NoModifier))


def _click(viewer, x: float, y: float) -> None:
    event = type("E", (), {})()
    event.button = lambda: Qt.MouseButton.LeftButton
    event.scenePos = lambda: QPointF(x, y)
    assert viewer._handle_linear_caliper_mouse_press(event) is True


def test_z_shows_loupe_immediately_when_cursor_is_over_viewer(qtbot, monkeypatch) -> None:
    viewer = _viewer(qtbot)
    monkeypatch.setattr(viewer, "_scene_pos_under_cursor", lambda: QPointF(20.0, 20.0))
    _press_z(viewer)
    assert viewer._magnifier_lens is not None
    assert viewer._magnifier_lens.isVisible() is True


def test_z_without_cursor_does_not_show_loupe(qtbot, monkeypatch) -> None:
    viewer = _viewer(qtbot)
    monkeypatch.setattr(viewer, "_scene_pos_under_cursor", lambda: None)
    _press_z(viewer)
    assert viewer._magnifier_held is True
    assert viewer._magnifier_lens is None or viewer._magnifier_lens.isVisible() is False


def test_persistent_loupe_survives_the_first_point_and_hides_on_the_second(qtbot, monkeypatch) -> None:
    viewer = _viewer(qtbot)
    viewer._magnifier_linear_persistent = True
    monkeypatch.setattr(viewer, "_scene_pos_under_cursor", lambda: QPointF(12.0, 12.0))
    assert viewer.start_linear_caliper_for("IVSd") is True
    assert viewer._magnifier_persistent_active is True
    assert viewer._magnifier_lens is not None and viewer._magnifier_lens.isVisible()

    _click(viewer, 10.0, 10.0)
    assert viewer._magnifier_persistent_active is True
    assert viewer._magnifier_lens.isVisible() is True

    _click(viewer, 30.0, 10.0)
    assert viewer._linear_caliper_active is False
    assert viewer._magnifier_persistent_active is False


def test_disabled_preference_hides_loupe_on_the_first_click(qtbot) -> None:
    viewer = _viewer(qtbot)
    viewer._magnifier_linear_persistent = False
    viewer._magnifier_held = True
    viewer._ensure_magnifier_lens().show()
    assert viewer.start_linear_caliper_for("AV") is True
    assert viewer._magnifier_persistent_active is False
    _click(viewer, 8.0, 8.0)
    assert viewer._magnifier_held is False


def test_doppler_and_vessel_do_not_arm_persistent_loupe(qtbot) -> None:
    viewer = _viewer(qtbot)
    viewer._magnifier_linear_persistent = True
    viewer._doppler.set_tool_mode("peak")
    assert viewer.start_linear_caliper_for("IVSd") is True
    assert viewer._magnifier_persistent_active is False

    viewer._doppler.set_tool_mode("none")
    viewer._doppler.set_vessel_mode()
    viewer._clear_linear_caliper()
    assert viewer.start_linear_caliper_for("AV") is True
    assert viewer._magnifier_persistent_active is False
