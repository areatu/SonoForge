"""Tests for area_tool_mode wiring into ViewerWidget (Task 5)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
    return w


# ── Step 2: set_area_tool_mode / area_tool_mode ──────────────────────


class TestAreaToolModeGetterSetter:
    def test_default_is_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w.area_tool_mode() == "click"

    def test_set_click(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_area_tool_mode("click")
        assert w.area_tool_mode() == "click"

    def test_set_freehand(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_area_tool_mode("freehand")
        assert w.area_tool_mode() == "freehand"

    def test_set_invalid_ignored(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.set_area_tool_mode("freehand")
        w.set_area_tool_mode("invalid")
        assert w.area_tool_mode() == "freehand"


# ── Step 3: start_generic_area_contour branches on mode ──────────────


class TestStartGenericAreaContourMode:
    def test_click_mode_default(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        result = w.start_generic_area_contour()
        assert result is True
        assert w._active_contour_chamber == "AREA"
        assert w._freehand_recording is False

    def test_freehand_mode_sets_flag(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_area_tool_mode("freehand")
        result = w.start_generic_area_contour()
        assert result is True
        assert w._freehand_recording is True
        assert w._freehand_points == []


# ── Step 4: _handle_contour_mouse_click freehand behavior ────────────


class TestHandleContourMouseClickFreehand:
    def test_single_click_ignored_in_freehand(self, qtbot) -> None:
        from PySide6.QtCore import Qt

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_area_tool_mode("freehand")
        w.start_generic_area_contour()
        assert w._contour_mode_active is True

        ev = MagicMock()
        ev.button.return_value = Qt.MouseButton.LeftButton
        ev.double.return_value = False
        ev.accept = MagicMock()

        result = w._handle_contour_mouse_click(ev)
        assert result is True
        ev.accept.assert_called_once()

    def test_double_click_finishes_freehand(self, qtbot) -> None:
        from PySide6.QtCore import Qt

        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_area_tool_mode("freehand")
        w.start_generic_area_contour()
        w._freehand_points = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]

        ev = MagicMock()
        ev.button.return_value = Qt.MouseButton.LeftButton
        ev.double.return_value = True
        ev.accept = MagicMock()

        result = w._handle_contour_mouse_click(ev)
        assert result is True


# ── Step 5: _distance helper ─────────────────────────────────────────


class TestDistanceHelper:
    def test_same_point(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._distance((0.0, 0.0), (0.0, 0.0)) == 0.0

    def test_horizontal(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._distance((0.0, 0.0), (3.0, 0.0)) == pytest.approx(3.0)

    def test_vertical(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._distance((0.0, 0.0), (0.0, 4.0)) == pytest.approx(4.0)

    def test_diagonal(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        assert w._distance((0.0, 0.0), (3.0, 4.0)) == pytest.approx(5.0)


# ── Step 7: _finish_freehand_contour ─────────────────────────────────


class TestFinishFreehandContour:
    def test_insufficient_points_clears(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_area_tool_mode("freehand")
        w.start_generic_area_contour()
        w._freehand_points = [(0.0, 0.0), (1.0, 1.0)]

        result = w._finish_freehand_contour()
        assert result is False
        assert w._freehand_recording is False

    def test_creates_contour_from_freehand(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_area_tool_mode("freehand")
        w.start_generic_area_contour()

        completed: list = []
        w.contour_completed.connect(completed.append)

        w._freehand_points = [
            (10.0, 10.0),
            (50.0, 10.0),
            (50.0, 50.0),
            (10.0, 50.0),
        ]

        result = w._finish_freehand_contour()
        assert result is True
        assert len(completed) == 1
        assert completed[0].chamber == "AREA"
        assert len(completed[0].points) >= 3
        assert w._freehand_recording is False
        assert w._freehand_points == []


# ── Step 8: _clear_active_contour_drawing clears freehand state ──────


class TestClearActiveContourDrawingFreehand:
    def test_clears_freehand_state(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w.set_area_tool_mode("freehand")
        w.start_generic_area_contour()
        w._freehand_recording = True
        w._freehand_points = [(0.0, 0.0), (1.0, 1.0)]

        w._clear_active_contour_drawing()

        assert w._freehand_recording is False
        assert w._freehand_points == []


# ── Step 9: _finish_closed_contour uses snap_closed_polygon ──────────


class TestFinishClosedContourSnap:
    def test_snap_not_called_when_disabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._magnetic_snap_enabled = False
        w.start_generic_area_contour()

        completed: list = []
        w.contour_completed.connect(completed.append)

        w._active_arc_points = [
            (10.0, 10.0),
            (50.0, 10.0),
            (50.0, 50.0),
            (10.0, 50.0),
        ]

        with patch("echo_personal_tool.domain.services.contour_edge_snap.snap_closed_polygon") as mock_snap:
            result = w._finish_closed_contour()
            assert result is True
            mock_snap.assert_not_called()

    def test_snap_called_when_enabled(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._magnetic_snap_enabled = True
        w.start_generic_area_contour()

        completed: list = []
        w.contour_completed.connect(completed.append)

        w._active_arc_points = [
            (10.0, 10.0),
            (50.0, 10.0),
            (50.0, 50.0),
            (10.0, 50.0),
        ]

        with patch(
            "echo_personal_tool.domain.services.contour_edge_snap.snap_closed_polygon",
            return_value=w._active_arc_points,
        ) as mock_snap:
            with patch.object(w, "_get_edge_map", return_value=MagicMock()):
                result = w._finish_closed_contour()
                assert result is True
                mock_snap.assert_called_once()


class TestAreaCompareContourPersistence:
    def test_area_compare_contour_is_persisted(self, qtbot) -> None:
        """Completed contour in area-comparison mode must stay stored (visible/editable)."""
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._magnetic_snap_enabled = False

        assert w.start_area_compare() is True
        assert w._comparison_state.kind == "area"

        w._active_arc_points = [
            (10.0, 10.0),
            (50.0, 10.0),
            (50.0, 50.0),
            (10.0, 50.0),
        ]

        completed: list = []
        w.contour_completed.connect(completed.append)

        assert w._finish_closed_contour() is True
        assert len(completed) == 1
        assert len(w._stored_contours) == 1
        assert w._stored_contours[0].chamber.upper() == "AREA"
        assert len(w._stored_contours[0].points) >= 4


# ── Step 10: per-click snap in handle_contour_click polygon branch ───


class TestPerClickSnapPolygon:
    def test_snap_not_called_with_few_points(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._magnetic_snap_enabled = True
        w.start_generic_area_contour()

        with patch("echo_personal_tool.domain.services.contour_edge_snap.snap_magnetic_point") as mock_snap:
            w.handle_contour_click((10.0, 10.0))
            mock_snap.assert_not_called()

    def test_snap_called_with_enough_points(self, qtbot) -> None:
        w = _make_viewer(qtbot)
        w.show_frame(np.zeros((64, 64), dtype=np.uint8))
        w._magnetic_snap_enabled = True
        w.start_generic_area_contour()

        w._active_arc_points = [
            (10.0, 10.0),
            (20.0, 10.0),
            (30.0, 10.0),
            (40.0, 10.0),
        ]

        with patch(
            "echo_personal_tool.domain.services.contour_edge_snap.snap_magnetic_point",
            return_value=None,
        ) as mock_snap:
            with patch(
                "echo_personal_tool.domain.services.contour_edge_snap.outward_normal_at_index_closed",
                return_value=(0.0, 1.0),
            ):
                with patch.object(w, "_get_edge_map", return_value=MagicMock()):
                    w.handle_contour_click((50.0, 10.0))
                    mock_snap.assert_called_once()
                    assert len(w._active_arc_points) == 5
