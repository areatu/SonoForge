"""Contour domain model and point handling tests."""

from __future__ import annotations

import numpy as np

from echo_personal_tool.domain.models import Contour
from echo_personal_tool.presentation.viewer_widget import ViewerWidget


def test_contour_dataclass_defaults() -> None:
    contour = Contour(phase="ED")

    assert contour.phase == "ED"
    assert contour.view == "A4C"
    assert contour.points == []
    assert contour.source == "manual"


def test_viewer_widget_finishes_closed_contour(qtbot) -> None:
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.show_frame(np.zeros((32, 32), dtype=np.uint8))

    completed: list[Contour] = []
    viewer.contour_completed.connect(completed.append)

    viewer.start_contour()
    viewer.handle_contour_click((3.0, 4.0))
    viewer.handle_contour_click((8.0, 4.0))
    viewer.handle_contour_click((8.0, 9.0))

    assert viewer.finish_contour()
    assert not viewer.is_contour_mode_active
    assert completed and completed[0].points == [
        (3.0, 4.0),
        (8.0, 4.0),
        (8.0, 9.0),
    ]
    assert viewer.contours[-1] == completed[0]
