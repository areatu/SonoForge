"""The click-to-zoom «лупа» of the viewer.

Acceptance list of 2026-10-23, item 4: «непонятно, что делает zoom — где фокус,
что именно увеличивается».  The contract pinned here: arming the tool swaps the
pointer for a magnifier, a click magnifies the point *under the pointer* (the
scene point stays put), Shift+click goes back, and Esc or «вписать» disarm it.
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from echo_personal_tool.presentation.viewer_widget import ViewerWidget


@pytest.fixture
def viewer(qtbot) -> ViewerWidget:
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    widget.resize(640, 480)
    widget.show()
    qtbot.waitExposed(widget)
    widget.show_frame(np.full((240, 320), 90, dtype=np.uint8))
    return widget


def _viewport(viewer: ViewerWidget):
    return viewer._graphics.viewport()


def _scene_point(viewer: ViewerWidget, x: float, y: float) -> QPointF:
    return viewer._graphics.mapToScene(QPointF(x, y).toPoint())


def test_zoom_keeps_the_point_under_the_pointer(viewer: ViewerWidget) -> None:
    x, y = _viewport(viewer).width() / 2 + 40, _viewport(viewer).height() / 2 - 30
    anchor = _scene_point(viewer, x, y)

    assert viewer.zoom_around(x, y, 2.0) is True

    assert viewer._zoom_factor == pytest.approx(2.0)
    after = _scene_point(viewer, x, y)
    assert after.x() == pytest.approx(anchor.x(), abs=1e-3)
    assert after.y() == pytest.approx(anchor.y(), abs=1e-3)


def test_zoom_is_clamped_to_the_supported_range(viewer: ViewerWidget) -> None:
    from echo_personal_tool.presentation.viewer_widget import _ZOOM_MAX, _ZOOM_MIN

    viewer.zoom_around(10, 10, 1e6)
    assert viewer._zoom_factor == pytest.approx(_ZOOM_MAX)
    viewer.zoom_around(10, 10, 1e-6)
    assert viewer._zoom_factor == pytest.approx(_ZOOM_MIN)


def test_loupe_click_magnifies_and_shift_click_restores(viewer: ViewerWidget) -> None:
    viewer.set_zoom_loupe_active(True)
    assert viewer.zoom_loupe_active() is True

    centre = _viewport(viewer).rect().center()
    QTest.mouseClick(_viewport(viewer), Qt.MouseButton.LeftButton, pos=centre)
    assert viewer._zoom_factor == pytest.approx(1.6)
    assert "160" in viewer._zoom_loupe_hint or "%" in viewer._zoom_loupe_hint

    QTest.mouseClick(
        _viewport(viewer),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        centre,
    )
    assert viewer._zoom_factor == pytest.approx(1.0)


def test_arming_the_loupe_changes_the_pointer(viewer: ViewerWidget) -> None:
    plain = _viewport(viewer).cursor().shape()
    viewer.set_zoom_loupe_active(True)
    arrow = _viewport(viewer).cursor().shape()
    viewer.set_zoom_loupe_active(False)
    restored = _viewport(viewer).cursor().shape()

    assert arrow != plain
    assert restored == plain


def test_esc_disarms_the_loupe(viewer: ViewerWidget) -> None:
    viewer.set_zoom_loupe_active(True)
    viewer.cancel_active_tool()
    assert viewer.zoom_loupe_active() is False


def test_fit_mode_returns_to_the_whole_frame(viewer: ViewerWidget) -> None:
    viewer.zoom_around(20, 20, 3.0)
    assert viewer._zoom_factor == pytest.approx(3.0)
    viewer.set_zoom_mode("fit")
    assert viewer._zoom_factor < 3.0


def test_loupe_click_is_ignored_without_a_frame(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.set_zoom_loupe_active(True)
    assert viewer._zoom_loupe_click(_FakeClick(QPointF(10, 10), Qt.KeyboardModifier.NoModifier)) is False


class _FakeClick:
    """The slice of QMouseEvent ``_zoom_loupe_click`` reads."""

    def __init__(self, position: QPointF, modifiers: Qt.KeyboardModifier) -> None:
        self._position = position
        self._modifiers = modifiers

    def position(self) -> QPointF:
        return self._position

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers
