"""Freehand traces keep the drawn points: no magnetic snap, auto-snap, or optical flow."""

from __future__ import annotations

import numpy as np
import pytest

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
    viewer._magnetic_snap_enabled = True
    return viewer


def test_open_arc_trace_does_not_call_assistants(qtbot, monkeypatch) -> None:
    from echo_personal_tool.domain.services.contour_geometry import DEFAULT_NODE_COUNT, resample_open_arc
    from echo_personal_tool.domain.services.polygon_reduce import reduce_polygon_points

    viewer = _viewer(qtbot)
    viewer.set_lv_contour_input("trace")
    assert viewer.start_contour(phase="ED", view="A4C", chamber="LV") is True
    stroke = [(10.0, 50.0), (20.0, 20.0), (30.0, 10.0), (40.0, 20.0), (50.0, 50.0)]
    viewer._freehand_points = list(stroke)
    calls: list[str] = []
    monkeypatch.setattr(viewer, "_apply_magnetic_snap_to_contour", lambda *_a, **_k: calls.append("magnetic"))
    monkeypatch.setattr(viewer, "_apply_optical_flow_refinement", lambda *_a, **_k: calls.append("flow"))
    monkeypatch.setattr(viewer, "_auto_snap_new_contour", lambda *_a, **_k: calls.append("auto"))

    assert viewer._finish_freehand_open_arc() is True
    assert calls == []
    contour = viewer.contours()[-1]
    assert contour.unassisted is True
    reduced = reduce_polygon_points(stroke, epsilon=3.0, closed=False)
    expected = resample_open_arc(reduced, num_nodes=DEFAULT_NODE_COUNT)
    assert contour.points == expected


def test_freehand_area_skips_magnetic_snap(qtbot, monkeypatch) -> None:
    from echo_personal_tool.domain.services.polygon_reduce import reduce_polygon_points

    viewer = _viewer(qtbot)
    viewer.set_area_tool_mode("freehand")
    assert viewer.start_generic_area_contour() is True
    stroke = [(10.0, 10.0), (50.0, 10.0), (50.0, 50.0), (10.0, 50.0)]
    viewer._freehand_points = list(stroke)
    calls: list[str] = []
    monkeypatch.setattr(viewer, "_apply_magnetic_snap_to_contour", lambda *_a, **_k: calls.append("magnetic"))
    monkeypatch.setattr(viewer, "_apply_optical_flow_refinement", lambda *_a, **_k: calls.append("flow"))
    monkeypatch.setattr(viewer, "_auto_snap_new_contour", lambda *_a, **_k: calls.append("auto"))

    assert viewer._finish_freehand_contour() is True
    assert calls == []
    contour = viewer.contours()[-1]
    assert contour.unassisted is True
    reduced = reduce_polygon_points(stroke, epsilon=3.0, closed=False)
    if reduced[0] != reduced[-1]:
        reduced = [*reduced, reduced[0]]
    assert contour.points == reduced


def test_landmark_contour_still_auto_snaps(qtbot, monkeypatch) -> None:
    from echo_personal_tool.domain.models import Contour

    viewer = _viewer(qtbot)
    contour = Contour(phase="ED", view="A4C", chamber="LV", points=[(10.0, 10.0), (20.0, 30.0), (30.0, 10.0)])
    viewer.set_contour_from_domain(contour)
    calls: list[int] = []
    monkeypatch.setattr(viewer, "_apply_magnetic_snap_to_contour", lambda index, *_a, **_k: calls.append(index))

    viewer._auto_snap_new_contour(viewer.contours()[0])
    assert calls == [0]


def test_click_polygon_keeps_magnetic_snap(qtbot, monkeypatch) -> None:
    viewer = _viewer(qtbot)
    viewer.set_area_tool_mode("click")
    assert viewer.start_generic_area_contour() is True
    snapped: list[tuple[float, float]] = []

    def _snap(points, _edge_map):
        moved = [(point[0] + 1.0, point[1]) for point in points]
        snapped.append(moved[0])
        return moved

    monkeypatch.setattr(
        "echo_personal_tool.domain.services.contour_edge_snap.snap_closed_polygon",
        _snap,
    )
    monkeypatch.setattr(viewer, "_get_edge_map", lambda: object())
    viewer._active_arc_points = [(10.0, 10.0), (40.0, 10.0), (40.0, 40.0), (10.0, 40.0)]
    assert viewer._finish_closed_contour() is True
    assert snapped
    assert viewer.contours()[-1].unassisted is False
