"""Unit tests for the spline contour editor."""

from __future__ import annotations

import numpy as np
import pytest

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.domain.services.contour_geometry import (
    DEFAULT_NODE_COUNT,
    resample_open_arc,
)
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def test_apply_contours_renders_closed_lines_and_nodes(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((32, 32), dtype=np.uint8))

    manual = Contour(
        phase="ED",
        points=[(2.0, 2.0), (8.0, 2.0), (8.0, 7.0)],
        source="manual",
    )
    ai = Contour(
        phase="ES",
        points=[(12.0, 12.0), (18.0, 12.0), (18.0, 18.0), (12.0, 18.0)],
        source="ai",
    )

    viewer.apply_contours([manual, ai])

    assert viewer.contours() == [manual, ai]
    assert len(viewer._contour_items) == 2
    assert [len(nodes) for nodes in viewer._contour_nodes] == [3, 4]

    manual_x, manual_y = viewer._contour_items[0].getData()
    ai_x, ai_y = viewer._contour_items[1].getData()
    assert len(manual_x) >= 128
    assert len(ai_x) >= 128
    assert manual_x[0] == pytest.approx(manual_x[-1], abs=0.01)
    assert manual_y[0] == pytest.approx(manual_y[-1], abs=0.01)
    assert min(manual_x) == pytest.approx(2.0, abs=0.5)
    assert max(manual_x) == pytest.approx(8.0, abs=0.5)
    assert max(manual_y) == pytest.approx(7.0, abs=1.5)
    assert ai_x[0] == pytest.approx(ai_x[-1], abs=0.01)
    assert ai_y[0] == pytest.approx(ai_y[-1], abs=0.01)

    assert viewer._contour_items[0].opts["pen"].color().name() == "#ff6f00"
    assert viewer._contour_items[1].opts["pen"].color().name() == "#00bcd4"


def test_set_contour_from_domain_replaces_matching_phase(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((16, 16), dtype=np.uint8))

    first = Contour(
        phase="ED",
        points=[(1.0, 1.0), (4.0, 1.0), (4.0, 4.0)],
        source="manual",
    )
    replacement = Contour(
        phase="ED",
        points=[(2.0, 2.0), (6.0, 2.0), (6.0, 6.0)],
        source="ai",
    )

    viewer.set_contour_from_domain(first)
    viewer.set_contour_from_domain(replacement)

    assert viewer.contours() == [replacement]
    assert len(viewer._contour_items) == 1
    assert len(viewer._contour_nodes[0]) == 3
    assert viewer._contour_items[0].opts["pen"].color().name() == "#00bcd4"


def test_update_contour_point_mutates_domain_and_emits_change(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((20, 20), dtype=np.uint8))

    contour = Contour(
        phase="ED",
        points=[(1.0, 1.0), (5.0, 1.0), (5.0, 5.0)],
        source="manual",
    )
    viewer.apply_contours([contour])

    viewer._drag_contour_point(0, 1, 5.0, 1.0)
    viewer._drag_contour_point(0, 1, 6.5, 4.0)
    with qtbot.waitSignal(viewer.contours_changed, timeout=1000) as blocker:
        viewer._finalize_contour_point_drag(0, 1, 7.5, 8.5)

    assert contour.points[1][0] > 5.0
    assert contour.points[1][1] > 1.0
    assert blocker.args == [[contour]]


def test_update_contour_point_resamples_open_arc(qtbot) -> None:
    annulus = ((10.0, 40.0), (50.0, 40.0))
    arc = [(10.0, 40.0), (30.0, 10.0), (50.0, 40.0)]
    contour = Contour(
        phase="ED",
        mitral_annulus=annulus,
        points=resample_open_arc(arc, num_nodes=DEFAULT_NODE_COUNT),
        num_nodes=DEFAULT_NODE_COUNT,
    )
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.apply_contours([contour])
    mid = DEFAULT_NODE_COUNT // 2
    mx, my = contour.points[mid]
    viewer._drag_contour_point(0, mid, mx, my)
    viewer._drag_contour_point(0, mid, 30.0, 8.0)
    viewer._finalize_contour_point_drag(0, mid, 30.0, 5.0)
    updated = viewer.contours()[0]
    assert len(updated.points) == DEFAULT_NODE_COUNT
    assert updated.points[mid][1] < my


def test_open_arc_rbf_drag_moves_neighbors_not_ma(qtbot) -> None:
    annulus = ((10.0, 40.0), (50.0, 40.0))
    arc = [(10.0, 40.0), (30.0, 10.0), (50.0, 40.0)]
    contour = Contour(
        phase="ED",
        mitral_annulus=annulus,
        points=resample_open_arc(arc, num_nodes=DEFAULT_NODE_COUNT),
        num_nodes=DEFAULT_NODE_COUNT,
        source="manual",
    )
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.apply_contours([contour])

    mid = DEFAULT_NODE_COUNT // 2
    y_before = contour.points[mid][1]
    y_neighbor = contour.points[mid + 1][1]

    viewer._drag_contour_point(0, mid, 30.0, 8.0)
    viewer._drag_contour_point(0, mid, 30.0, 5.0)

    assert contour.points[0] == annulus[0]
    assert contour.points[-1] == annulus[1]
    assert contour.points[mid][1] < y_before
    assert contour.points[mid + 1][1] < y_neighbor


def test_scene_mouse_moved_applies_drag_during_session(qtbot) -> None:
    from unittest.mock import patch

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    annulus = ((10.0, 40.0), (50.0, 40.0))
    arc = [(10.0, 40.0), (30.0, 10.0), (50.0, 40.0)]
    contour = Contour(
        phase="ED",
        mitral_annulus=annulus,
        points=resample_open_arc(arc, num_nodes=DEFAULT_NODE_COUNT),
        num_nodes=DEFAULT_NODE_COUNT,
        source="manual",
    )
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.apply_contours([contour])

    mid = DEFAULT_NODE_COUNT // 2
    mx, my = contour.points[mid]
    viewer._begin_contour_node_drag(0, mid, mx, my)
    mapped = viewer._view.mapViewToScene(QPointF(mx, my - 4.0))
    with patch.object(QApplication, "mouseButtons", return_value=Qt.MouseButton.LeftButton):
        viewer._on_scene_mouse_moved(mapped)
    assert contour.points[mid][1] < my


def test_locked_tier_drag_moves_highlighted_neighbors(qtbot) -> None:
    annulus = ((10.0, 40.0), (50.0, 40.0))
    arc = [(10.0, 40.0), (30.0, 10.0), (50.0, 40.0)]
    contour = Contour(
        phase="ED",
        mitral_annulus=annulus,
        points=resample_open_arc(arc, num_nodes=DEFAULT_NODE_COUNT),
        num_nodes=DEFAULT_NODE_COUNT,
        source="manual",
    )
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((64, 64), dtype=np.uint8))
    viewer.apply_contours([contour])

    mid = DEFAULT_NODE_COUNT // 2
    y_neighbor = contour.points[mid + 1][1]
    viewer._start_drag_session(0, 30.0, 10.0, mid, 3)
    viewer._apply_rbf_drag_step(0, 30.0, 8.0, grab_index=mid)

    assert contour.points[mid][1] < 10.0
    assert contour.points[mid + 1][1] < y_neighbor


def test_closed_contour_rbf_drag_moves_multiple_points(qtbot) -> None:
    contour = Contour(
        phase="ED",
        points=[(2.0, 2.0), (8.0, 2.0), (8.0, 7.0), (2.0, 7.0)],
        source="manual",
    )
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((32, 32), dtype=np.uint8))
    viewer.apply_contours([contour])

    x1_before = contour.points[1][0]
    x2_before = contour.points[2][0]

    viewer._start_drag_session(0, 8.0, 2.0, 1, 3)
    viewer._apply_rbf_drag_step(0, 10.0, 2.0, grab_index=1)

    assert contour.points[1][0] > x1_before
    assert contour.points[2][0] > x2_before
