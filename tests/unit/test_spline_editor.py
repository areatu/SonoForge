"""Unit tests for the spline contour editor."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models import Contour
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
    assert list(manual_x) == [2.0, 8.0, 8.0, 2.0]
    assert list(manual_y) == [2.0, 2.0, 7.0, 2.0]
    assert list(ai_x) == [12.0, 18.0, 18.0, 12.0, 12.0]
    assert list(ai_y) == [12.0, 12.0, 18.0, 18.0, 12.0]

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

    with qtbot.waitSignal(viewer.contours_changed, timeout=1000) as blocker:
        viewer._update_contour_point(0, 1, 7.5, 8.5)

    assert contour.points[1] == (7.5, 8.5)
    assert blocker.args == [[contour]]
    x_values, y_values = viewer._contour_items[0].getData()
    assert list(x_values) == [1.0, 7.5, 5.0, 1.0]
    assert list(y_values) == [1.0, 8.5, 5.0, 1.0]
