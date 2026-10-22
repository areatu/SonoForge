"""Area/planimeter click handling: every click places a point unless it is a
deliberate finish gesture.

Regression coverage for the "fast clicking drops points" bug: Qt reports the
second click of a rapid pair as a double-click (time-based only), and the
viewer used to treat *any* double-click as "close the contour".
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class FakeClickEvent:
    """Mimics the pyqtgraph MouseClickEvent surface used by the viewer."""

    def __init__(
        self,
        *,
        view: tuple[float, float],
        screen: tuple[float, float],
        double: bool = False,
        button=None,
    ) -> None:
        from PySide6.QtCore import QPointF, Qt

        self._view = QPointF(view[0], view[1])
        self._screen = QPointF(screen[0], screen[1])
        self._double = double
        self._button = button if button is not None else Qt.MouseButton.LeftButton
        self.accepted = False

    def button(self):
        return self._button

    def double(self) -> bool:
        return self._double

    def scenePos(self):
        return self._view

    def screenPos(self):
        return self._screen

    def accept(self) -> None:
        self.accepted = True


def _make_viewer(qtbot, *, frame_size: int = 64):
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((frame_size, frame_size), dtype=np.uint8))
    viewer._magnetic_snap_enabled = False
    # Identity mapping: scene coordinates are used as view coordinates.
    viewer._view.mapSceneToView = lambda pos: pos  # type: ignore[method-assign]
    return viewer


def _click(viewer, view, screen, *, double=False, button=None) -> FakeClickEvent:
    event = FakeClickEvent(view=view, screen=screen, double=double, button=button)
    assert viewer._handle_contour_mouse_click(event) is True
    return event


class TestFastClickingPlacesEveryPoint:
    def test_rapid_clicks_far_apart_are_not_a_finish_gesture(self, qtbot) -> None:
        """Qt flags the 2nd/4th click as double, yet all four points must land."""
        viewer = _make_viewer(qtbot)
        assert viewer.start_generic_area_contour() is True

        clicks = [
            ((10.0, 10.0), (100.0, 100.0), False),
            ((30.0, 10.0), (160.0, 100.0), True),  # Qt: "double" (time only)
            ((50.0, 10.0), (220.0, 100.0), False),
            ((50.0, 40.0), (220.0, 180.0), True),  # Qt: "double" (time only)
        ]
        completed: list = []
        viewer.contour_completed.connect(completed.append)
        for view, screen, double in clicks:
            _click(viewer, view, screen, double=double)

        assert len(viewer._active_arc_points) == 4
        assert completed == []
        assert viewer._contour_mode_active is True

    def test_slow_clicks_place_points(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        assert viewer.start_generic_area_contour() is True
        for index, (x, y) in enumerate([(10.0, 10.0), (30.0, 10.0), (30.0, 40.0)]):
            _click(viewer, (x, y), (100.0 + index * 60, 100.0))
        assert len(viewer._active_arc_points) == 3


class TestFinishGestures:
    def test_double_click_in_place_closes_polygon(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        assert viewer.start_generic_area_contour() is True
        completed: list = []
        viewer.contour_completed.connect(completed.append)

        _click(viewer, (10.0, 10.0), (100.0, 100.0))
        _click(viewer, (40.0, 10.0), (200.0, 100.0))
        _click(viewer, (40.0, 40.0), (200.0, 200.0))
        # Finish: two clicks on the same spot.
        _click(viewer, (10.0, 40.0), (100.0, 200.0))
        _click(viewer, (10.0, 40.0), (101.0, 200.0), double=True)

        assert len(completed) == 1
        assert completed[0].chamber.upper() == "AREA"
        assert len(completed[0].points) == 4  # no duplicate closing point
        assert viewer._contour_mode_active is False

    def test_double_click_in_place_too_early_is_ignored(self, qtbot) -> None:
        """Two points are not a polygon: the gesture must not throw the work away."""
        viewer = _make_viewer(qtbot)
        assert viewer.start_generic_area_contour() is True
        completed: list = []
        viewer.contour_completed.connect(completed.append)

        _click(viewer, (10.0, 10.0), (100.0, 100.0))
        _click(viewer, (40.0, 10.0), (200.0, 100.0))
        _click(viewer, (40.0, 10.0), (200.0, 100.0), double=True)

        assert completed == []
        assert len(viewer._active_arc_points) == 2
        assert viewer._contour_mode_active is True

    def test_click_on_first_point_closes_polygon(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        assert viewer.start_generic_area_contour() is True
        completed: list = []
        viewer.contour_completed.connect(completed.append)

        _click(viewer, (10.0, 10.0), (100.0, 100.0))
        _click(viewer, (40.0, 10.0), (200.0, 100.0))
        _click(viewer, (40.0, 40.0), (200.0, 200.0))
        _click(viewer, (10.0, 11.0), (103.0, 103.0))  # back on the first point

        assert len(completed) == 1
        assert len(completed[0].points) == 3


class TestUndoLastPoint:
    def test_right_click_removes_last_point(self, qtbot) -> None:
        from PySide6.QtCore import Qt

        viewer = _make_viewer(qtbot)
        assert viewer.start_generic_area_contour() is True
        _click(viewer, (10.0, 10.0), (100.0, 100.0))
        _click(viewer, (40.0, 10.0), (200.0, 100.0))

        event = _click(viewer, (0.0, 0.0), (0.0, 0.0), button=Qt.MouseButton.RightButton)

        assert event.accepted is True
        assert len(viewer._active_arc_points) == 1
        assert viewer._contour_mode_active is True

    def test_right_click_without_points_is_not_handled(self, qtbot) -> None:
        from PySide6.QtCore import Qt

        viewer = _make_viewer(qtbot)
        assert viewer.start_generic_area_contour() is True
        event = FakeClickEvent(view=(0.0, 0.0), screen=(0.0, 0.0), button=Qt.MouseButton.RightButton)
        assert viewer._handle_contour_mouse_click(event) is False


class TestPolygonCleanup:
    def test_dedupe_drops_repeated_points(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        points = [(0.0, 0.0), (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
        assert viewer._dedupe_closed_polygon(points) == [
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
        ]

    def test_collinear_points_do_not_create_a_contour(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        assert viewer.start_generic_area_contour() is True
        viewer._active_arc_points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
        assert viewer._finish_closed_contour() is False
        # The points are kept so the operator can fix the contour.
        assert len(viewer._active_arc_points) == 3
        assert viewer._contour_mode_active is True

    def test_too_few_points_keeps_the_drawing(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        assert viewer.start_generic_area_contour() is True
        viewer._active_arc_points = [(0.0, 0.0), (10.0, 0.0)]
        assert viewer._finish_closed_contour() is False
        assert len(viewer._active_arc_points) == 2


class TestLiveProgressLabel:
    def test_label_shows_provisional_area(self, qtbot) -> None:
        viewer = _make_viewer(qtbot)
        assert viewer.start_generic_area_contour() is True
        _click(viewer, (0.0, 0.0), (100.0, 100.0))
        _click(viewer, (10.0, 0.0), (200.0, 100.0))
        _click(viewer, (10.0, 10.0), (200.0, 200.0))
        # Triangle 10x10/2 = 50 px² → 0.50 cm² with the default 1 px spacing.
        assert "0.50" in viewer._measurement_label.text()

        _click(viewer, (0.0, 10.0), (100.0, 200.0))
        # Full 10x10 square = 100 px² → 1.00 cm².
        assert "1.00" in viewer._measurement_label.text()
