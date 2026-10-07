"""Tests for the freehand (trace) manual LV contour input mode."""

from __future__ import annotations

from unittest.mock import MagicMock

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


def _make_viewer(qtbot):
    from echo_personal_tool.presentation.viewer_widget import ViewerWidget

    w = ViewerWidget()
    qtbot.addWidget(w)
    w.show_frame(np.zeros((64, 64), dtype=np.uint8))
    return w


class TestLvContourInputGetterSetter:
    def test_default_is_landmarks(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.lv_contour_input() == "landmarks"

    def test_set_trace(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_lv_contour_input("trace")
        assert w.lv_contour_input() == "trace"

    def test_invalid_ignored(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_lv_contour_input("trace")
        w.set_lv_contour_input("nonsense")
        assert w.lv_contour_input() == "trace"


class TestStartContourTrace:
    def test_landmarks_mode_uses_stages(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.start_contour(phase="ED", view="A4C", chamber="LV") is True
        assert w._contour_stage == "ma_septal"
        assert w._freehand_recording is False
        assert w._freehand_open_arc is False

    def test_trace_mode_starts_recording_line_only(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_lv_contour_input("trace")
        assert w.start_contour(phase="ED", view="A4C", chamber="LV") is True
        assert w._contour_stage == "trace"
        assert w._freehand_recording is True
        assert w._freehand_open_arc is True
        # No per-sample marker while tracing — a single continuous line.
        assert w._active_contour_item.opts.get("symbol") is None


class TestFinishFreehandOpenArc:
    def _started_trace(self, qtbot):
        w = _make_viewer(qtbot)
        w.set_lv_contour_input("trace")
        w.start_contour(phase="ED", view="A4C", chamber="LV")
        return w

    def test_insufficient_points_returns_false(self, qtbot) -> None:
        w = self._started_trace(qtbot)
        w._freehand_points = [(10.0, 10.0), (12.0, 10.0)]
        assert w._finish_freehand_open_arc() is False

    def test_builds_open_arc_with_annulus(self, qtbot) -> None:
        w = self._started_trace(qtbot)
        completed: list = []
        w.contour_completed.connect(completed.append)

        # Septal (left), apex (top), lateral (right): an open endocardial arc.
        w._freehand_points = [(10.0, 50.0), (20.0, 20.0), (30.0, 10.0), (40.0, 20.0), (50.0, 50.0)]

        assert w._finish_freehand_open_arc() is True
        assert len(completed) == 1
        contour = completed[0]
        assert contour.chamber == "LV"
        assert contour.source == "manual"
        assert contour.is_open_arc is True
        assert contour.mitral_annulus == ((10.0, 50.0), (50.0, 50.0))
        assert contour.apex_landmark is not None
        assert len(contour.points) == contour.num_nodes
        assert w._freehand_recording is False
        assert w._freehand_open_arc is False
        assert w._freehand_points == []

    def test_finish_contour_routes_trace_stage(self, qtbot) -> None:
        w = self._started_trace(qtbot)
        w._freehand_points = [(10.0, 50.0), (30.0, 10.0), (50.0, 50.0)]
        assert w.finish_contour() is True
        assert w._contour_mode_active is False


class TestTraceClickAddsNode:
    def test_plain_click_appends_point(self, qtbot) -> None:
        from PySide6.QtCore import QPointF, Qt

        w = _make_viewer(qtbot)
        w.set_lv_contour_input("trace")
        w.start_contour(phase="ED", view="A4C", chamber="LV")

        ev = MagicMock()
        ev.button.return_value = Qt.MouseButton.LeftButton
        ev.double.return_value = False
        ev.screenPos.return_value = None
        ev.scenePos.return_value = QPointF(5.0, 5.0)

        assert w._handle_contour_mouse_click(ev) is True
        assert len(w._freehand_points) == 1
